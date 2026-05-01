import asyncio
import tempfile
from pathlib import Path

import httpx

from arc.agents import build_system_prompt
from arc.config import ArcConfig, load_config
from arc.types import AgentConfig, DispatchResult


class DispatchError(Exception):
    pass


async def dispatch(
    prompt: str,
    agent: AgentConfig,
    model_override: str | None = None,
    session_name: str | None = None,
    one_shot: bool = True,
    config: ArcConfig | None = None,
) -> DispatchResult:
    """Route a prompt to the appropriate backend."""
    cfg = config or load_config()
    model = model_override or agent.model

    if model_override and agent.allowed_models:
        if model not in agent.allowed_models:
            raise DispatchError(
                f"Model '{model}' is not allowed for agent '{agent.name}'. "
                f"Allowed: {', '.join(agent.allowed_models)}"
            )

    if model.startswith("ollama/"):
        return await dispatch_ollama(prompt, agent, model, cfg)
    else:
        return await dispatch_acpx(prompt, agent, model, session_name, one_shot, cfg)


_ACPX_PERMISSION_MAP = {
    # acpx native values (pass through)
    "approve-all": "--approve-all",
    "approve-reads": "--approve-reads",
    "deny-all": "--deny-all",
    # Claude Code legacy values mapped to closest acpx equivalent
    "bypassPermissions": "--approve-all",
    "auto": "--approve-all",
    "acceptEdits": "--approve-reads",
    "default": "--approve-reads",
}


def _acpx_permission_flag(permission_mode: str) -> str:
    """Map an agent permission_mode to the correct acpx flag."""
    flag = _ACPX_PERMISSION_MAP.get(permission_mode)
    if flag is None:
        raise DispatchError(
            f"Unknown permission_mode '{permission_mode}'. "
            f"Valid: {', '.join(_ACPX_PERMISSION_MAP)}"
        )
    return flag


def _build_acpx_base(
    config: ArcConfig,
    agent: AgentConfig,
    model: str,
    system_prompt: str,
) -> list[str]:
    """Build the acpx global flags that precede the agent name."""
    perm_flag = _acpx_permission_flag(agent.permission_mode)
    cmd = [
        config.acpx.command,
        "--format", "quiet",
        "--cwd", agent.workspace,
        "--model", model,
        perm_flag,
    ]
    if system_prompt:
        # --system-prompt replaces Claude Code's default "I am a coding assistant"
        # identity, letting the agent persona (Coach Kai, etc.) take effect.
        # Tool use is defined at the ACP protocol level and is unaffected.
        cmd.extend(["--system-prompt", system_prompt])
    return cmd


async def _ensure_session(
    config: ArcConfig,
    agent: AgentConfig,
    session_name: str,
    system_prompt: str,
) -> None:
    """Ensure a named acpx session exists, creating it with the system prompt if needed.

    acpx applies --system-prompt only on session/new, so it must be passed
    here (not on subsequent prompts) to set it correctly for the session lifetime.
    """
    cmd = [
        config.acpx.command,
        "--cwd", agent.workspace,
        config.acpx.default_agent,
        "sessions", "ensure",
        "--name", session_name,
    ]
    if system_prompt:
        agent_idx = cmd.index(config.acpx.default_agent)
        cmd[agent_idx:agent_idx] = ["--system-prompt", system_prompt]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.wait(), timeout=30)


async def dispatch_acpx(
    prompt: str,
    agent: AgentConfig,
    model: str,
    session_name: str | None,
    one_shot: bool,
    config: ArcConfig,
) -> DispatchResult:
    """Dispatch via acpx to Claude Code."""
    system_prompt = await build_system_prompt(agent)

    prompt_file: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as pf:
            pf.write(prompt)
            prompt_file = pf.name

        # For named sessions: ensure the session exists first.
        # --append-system-prompt is only applied on session/new, so it is passed
        # to ensure (not to the prompt call) to set the persona on first creation.
        if session_name and not one_shot:
            await _ensure_session(config, agent, session_name, system_prompt)

        # Build the prompt command. System prompt is NOT re-passed here for sessions
        # (already set at creation time); it IS passed for one-shot exec.
        base = _build_acpx_base(config, agent, model,
                                 system_prompt if one_shot else "")
        cmd = base + [config.acpx.default_agent]

        if one_shot:
            cmd.append("exec")
        elif session_name:
            cmd.extend(["-s", session_name])

        cmd.extend(["--file", prompt_file])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.timeouts.acpx_request,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise DispatchError(
                f"acpx timed out after {config.timeouts.acpx_request}s"
            )

        if proc.returncode != 0:
            raise DispatchError(f"acpx exited {proc.returncode}: {stderr.decode().strip()}")

        return DispatchResult(
            output=stdout.decode().strip(),
            model_used=model,
            dispatch_type="acpx",
        )

    finally:
        if prompt_file:
            Path(prompt_file).unlink(missing_ok=True)


async def dispatch_ollama(
    prompt: str,
    agent: AgentConfig,
    model: str,
    config: ArcConfig,
) -> DispatchResult:
    """Dispatch via httpx to Ollama-compatible API."""
    model_parts = model.removeprefix("ollama/")

    if "/" in model_parts:
        endpoint_name, ollama_model = model_parts.split("/", 1)
        if endpoint_name not in config.ollama.endpoints:
            raise DispatchError(
                f"Unknown Ollama endpoint '{endpoint_name}'. "
                f"Configured: {', '.join(config.ollama.endpoints)}"
            )
        endpoint = config.ollama.endpoints[endpoint_name].url
    else:
        ollama_model = model_parts
        if "local" not in config.ollama.endpoints:
            raise DispatchError("No 'local' Ollama endpoint configured.")
        endpoint = config.ollama.endpoints["local"].url

    messages: list[dict] = []

    system_prompt = await build_system_prompt(agent)
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if agent.local_context_files:
        context_parts = []
        for fname in agent.local_context_files:
            path = Path(agent.workspace) / fname
            if path.exists():
                context_parts.append(f"--- {fname} ---\n{path.read_text()}")
        if context_parts:
            messages.append({
                "role": "system",
                "content": "Reference files:\n\n" + "\n\n".join(context_parts),
            })

    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=config.timeouts.ollama_request) as client:
            response = await client.post(
                f"{endpoint}/chat/completions",
                json={"model": ollama_model, "messages": messages, "stream": False},
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise DispatchError(f"Ollama timed out after {config.timeouts.ollama_request}s")
    except httpx.ConnectError:
        raise DispatchError(
            f"Cannot connect to Ollama at {endpoint}. Is Ollama running?"
        )
    except httpx.HTTPStatusError as e:
        raise DispatchError(f"Ollama returned HTTP {e.response.status_code}: {e.response.text}")

    data = response.json()
    return DispatchResult(
        output=data["choices"][0]["message"]["content"],
        model_used=model,
        dispatch_type="ollama",
    )
