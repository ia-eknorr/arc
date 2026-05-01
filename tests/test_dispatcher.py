from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arc.config import load_config
from arc.dispatcher import (
    DispatchError,
    _acpx_permission_flag,
    dispatch,
    dispatch_acpx,
    dispatch_ollama,
)
from arc.types import AgentConfig


@pytest.fixture
def coach(config_dir: Path, workspace: Path, coach_agent_yaml: dict) -> AgentConfig:
    from arc.agents import load_agent
    return load_agent("coach", config_dir)


@pytest.fixture
def trainer(config_dir: Path, workspace: Path, trainer_agent_yaml: dict) -> AgentConfig:
    from arc.agents import load_agent
    return load_agent("trainer", config_dir)


# --- Model routing ---


async def test_dispatch_routes_claude(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    with patch("arc.dispatcher.dispatch_acpx", new_callable=AsyncMock) as mock_acpx:
        from arc.types import DispatchResult
        mock_acpx.return_value = DispatchResult("hello", "claude-sonnet-4-6", "acpx")
        result = await dispatch("Hello", coach, config=cfg)
    mock_acpx.assert_awaited_once()
    assert result.dispatch_type == "acpx"


async def test_dispatch_routes_ollama(config_dir: Path, trainer: AgentConfig) -> None:
    cfg = load_config(config_dir)
    with patch("arc.dispatcher.dispatch_ollama", new_callable=AsyncMock) as mock_ollama:
        from arc.types import DispatchResult
        mock_ollama.return_value = DispatchResult("hi", "ollama/qwen3:8b", "ollama")
        result = await dispatch("Hello", trainer, config=cfg)
    mock_ollama.assert_awaited_once()
    assert result.dispatch_type == "ollama"


async def test_dispatch_model_override_allowed(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    with patch("arc.dispatcher.dispatch_acpx", new_callable=AsyncMock) as mock_acpx:
        from arc.types import DispatchResult
        mock_acpx.return_value = DispatchResult("ok", "claude-haiku-4-5", "acpx")
        await dispatch("Q", coach, model_override="claude-haiku-4-5", config=cfg)
    called_model = mock_acpx.call_args[0][2]
    assert called_model == "claude-haiku-4-5"


async def test_dispatch_model_override_not_allowed(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    with pytest.raises(DispatchError, match="not allowed"):
        await dispatch("Q", coach, model_override="claude-opus-4-7", config=cfg)


async def test_dispatch_unknown_model(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    coach.allowed_models = ["gpt-4"]
    with pytest.raises(DispatchError, match="Unknown model type"):
        await dispatch("Q", coach, model_override="gpt-4", config=cfg)


# --- acpx dispatch ---


async def test_dispatch_acpx_success(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"Coach response", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await dispatch_acpx(
            "Hello", coach, "claude-sonnet-4-6", None, True, cfg
        )

    assert result.output == "Coach response"
    assert result.model_used == "claude-sonnet-4-6"
    assert result.dispatch_type == "acpx"

    cmd = mock_exec.call_args[0]
    assert "acpx" in cmd
    assert "exec" in cmd
    assert "--cwd" in cmd
    assert "--format" in cmd
    # acpx uses --approve-* flags, not --permission-mode
    assert any(f in cmd for f in ("--approve-all", "--approve-reads", "--deny-all"))
    # Global flags (--cwd, --format, --model) come before the agent name
    acpx_idx = cmd.index("acpx")
    agent_idx = cmd.index("claude")
    cwd_idx = cmd.index("--cwd")
    assert acpx_idx < cwd_idx < agent_idx


async def test_dispatch_acpx_session(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"reply", b""))
    mock_proc.wait = AsyncMock(return_value=0)  # used by _ensure_session

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await dispatch_acpx(
            "msg", coach, "claude-sonnet-4-6", "coach-thread-123", False, cfg
        )

    # Two calls: ensure then prompt. Check the prompt call (last).
    all_calls = mock_exec.call_args_list
    assert len(all_calls) == 2
    ensure_cmd = all_calls[0][0]
    prompt_cmd = all_calls[1][0]

    # ensure call: sessions ensure --name <session>
    assert "sessions" in ensure_cmd
    assert "ensure" in ensure_cmd
    assert "coach-thread-123" in ensure_cmd

    # prompt call: claude -s <session>
    assert "-s" in prompt_cmd
    assert "coach-thread-123" in prompt_cmd
    assert "exec" not in prompt_cmd


async def test_dispatch_acpx_failure(config_dir: Path, coach: AgentConfig) -> None:
    cfg = load_config(config_dir)
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(DispatchError, match="acpx exited 1"):
            await dispatch_acpx("Q", coach, "claude-sonnet-4-6", None, True, cfg)


async def test_dispatch_acpx_timeout(config_dir: Path, coach: AgentConfig) -> None:
    import asyncio as _asyncio

    cfg = load_config(config_dir)
    cfg.timeouts.acpx_request = 1

    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=_asyncio.TimeoutError)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("asyncio.wait_for", side_effect=_asyncio.TimeoutError):
            with pytest.raises(DispatchError, match="timed out"):
                await dispatch_acpx("Q", coach, "claude-sonnet-4-6", None, True, cfg)


async def test_dispatch_acpx_prompt_tempfile_cleaned_up(
    config_dir: Path, coach: AgentConfig, tmp_path: Path
) -> None:
    cfg = load_config(config_dir)
    created_files: list[str] = []

    original_ntf = __import__("tempfile").NamedTemporaryFile

    def tracking_ntf(*args, **kwargs):
        f = original_ntf(*args, **kwargs)
        created_files.append(f.name)
        return f

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    with patch("tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await dispatch_acpx("Q", coach, "claude-sonnet-4-6", None, True, cfg)

    for path in created_files:
        assert not Path(path).exists(), f"Temp file not cleaned up: {path}"


async def test_dispatch_acpx_uses_model_flag(
    config_dir: Path, coach: AgentConfig
) -> None:
    cfg = load_config(config_dir)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await dispatch_acpx("Q", coach, "claude-haiku-4-5", None, True, cfg)

    cmd = mock_exec.call_args[0]
    assert "--model" in cmd
    assert cmd[list(cmd).index("--model") + 1] == "claude-haiku-4-5"
    # No env override needed -- --model flag is used instead
    assert "env" not in mock_exec.call_args[1]


async def test_dispatch_acpx_format_quiet(
    config_dir: Path, coach: AgentConfig
) -> None:
    cfg = load_config(config_dir)
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await dispatch_acpx("Q", coach, "claude-sonnet-4-6", None, True, cfg)

    cmd = mock_exec.call_args[0]
    assert "--format" in cmd
    assert cmd[list(cmd).index("--format") + 1] == "quiet"


# --- Permission mode mapping ---


def test_permission_flag_approve_all() -> None:
    assert _acpx_permission_flag("approve-all") == "--approve-all"


def test_permission_flag_approve_reads() -> None:
    assert _acpx_permission_flag("approve-reads") == "--approve-reads"


def test_permission_flag_legacy_bypass() -> None:
    assert _acpx_permission_flag("bypassPermissions") == "--approve-all"


def test_permission_flag_legacy_auto() -> None:
    assert _acpx_permission_flag("auto") == "--approve-all"


def test_permission_flag_legacy_accept_edits() -> None:
    assert _acpx_permission_flag("acceptEdits") == "--approve-reads"


def test_permission_flag_unknown() -> None:
    with pytest.raises(DispatchError, match="Unknown permission_mode"):
        _acpx_permission_flag("totally-made-up")


# --- Ollama dispatch ---


async def test_dispatch_ollama_local(
    config_dir: Path, trainer: AgentConfig, httpx_mock
) -> None:
    cfg = load_config(config_dir)
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "Ollama says hello"}}]
        },
    )
    result = await dispatch_ollama("Hello", trainer, "ollama/qwen3:8b", cfg)
    assert result.output == "Ollama says hello"
    assert result.model_used == "ollama/qwen3:8b"
    assert result.dispatch_type == "ollama"


async def test_dispatch_ollama_named_endpoint(
    config_dir: Path, trainer: AgentConfig, httpx_mock
) -> None:
    cfg = load_config(config_dir)
    httpx_mock.add_response(
        url="http://kyle.local:11434/v1/chat/completions",
        json={"choices": [{"message": {"content": "From kyle"}}]},
    )
    result = await dispatch_ollama("Q", trainer, "ollama/kyle/qwen3:8b", cfg)
    assert result.output == "From kyle"
    assert result.model_used == "ollama/kyle/qwen3:8b"


async def test_dispatch_ollama_connect_error(
    config_dir: Path, trainer: AgentConfig, httpx_mock
) -> None:
    import httpx as _httpx

    cfg = load_config(config_dir)
    httpx_mock.add_exception(_httpx.ConnectError("refused"))
    with pytest.raises(DispatchError, match="Cannot connect to Ollama"):
        await dispatch_ollama("Q", trainer, "ollama/qwen3:8b", cfg)


async def test_dispatch_ollama_unknown_endpoint(
    config_dir: Path, trainer: AgentConfig
) -> None:
    cfg = load_config(config_dir)
    with pytest.raises(DispatchError, match="Unknown Ollama endpoint"):
        await dispatch_ollama("Q", trainer, "ollama/unknown/model", cfg)


async def test_dispatch_ollama_injects_system_prompt(
    config_dir: Path, trainer: AgentConfig, httpx_mock
) -> None:
    cfg = load_config(config_dir)
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={"choices": [{"message": {"content": "ok"}}]},
    )
    await dispatch_ollama("Q", trainer, "ollama/qwen3:8b", cfg)
    request = httpx_mock.get_requests()[0]
    import json
    body = json.loads(request.content)
    roles = [m["role"] for m in body["messages"]]
    assert "system" in roles
    assert "user" in roles
