# arc -- Agent Router CLI

## Design Document v4 (Final)

> A lightweight Python CLI and daemon for agent dispatch, scheduled tasks, and
> Discord integration. Replaces OpenClaw with minimal code, leveraging `acpx` for
> Claude Code session management and Ollama for local/remote models.

---

## 1. Overview

`arc` is a personal AI agent platform that runs as a daemon on a Linux machine
(LXC container on Proxmox). It receives requests from three sources (CLI, Discord,
cron), resolves which agent should handle the request, dispatches to the appropriate
model via `acpx` (Claude Code) or `httpx` (Ollama), and returns results.

### Core Principles

- **No API keys required.** Claude uses your existing subscription via `acpx`/Claude
  Code. Local models are free via Ollama.
- **Agent-centric routing.** Each agent has a default model. The model is a property
  of the agent, not a separate routing layer.
- **Stateful Discord, stateless everything else.** Discord threads use persistent
  `acpx` named sessions. Cron jobs and CLI one-offs use `acpx exec` (one-shot).
- **OpenClaw-compatible.** Agent identity files (AGENTS.md, IDENTITY.md, SOUL.md,
  USER.md, TOOLS.md) are used unchanged.
- **Config-driven.** YAML config directory governs all behavior. Setup wizard
  generates defaults on first install.

### Tech Stack

| Component | Package | Purpose |
|-----------|---------|---------|
| CLI framework | typer | Subcommands, flags, help, shell completions |
| Claude dispatch | acpx (npm) | ACP sessions to Claude Code (subscription) |
| Local model dispatch | httpx | Ollama API (local + remote endpoints) |
| Scheduler | apscheduler | Cron job execution |
| Discord bot | discord.py | Discord gateway |
| Config parsing | pyyaml | All YAML config files |
| IPC | stdlib (socket) | Unix domain socket between CLI and daemon |

### Why These Tools

- **acpx** replaces raw `claude -p` subprocess calls. It provides persistent named
  sessions (for Discord threads), one-shot mode (for cron/CLI), prompt queueing,
  crash reconnect, and structured output. It spawns Claude Code as a subprocess via
  ACP protocol, so it uses your Claude subscription directly. It is an independent
  MIT-licensed CLI from OpenClaw's acpx repo -- it does NOT require OpenClaw to run.
  Requires Node.js >= 22.12.0.

- **No LiteLLM.** All non-Claude models are accessed through Ollama, which already
  speaks OpenAI-compatible API. Nothing to normalize.

- **No RouteLLM / CrewAI.** Agents define their own models. No classifier needed.

- **No OpenClaw.** Replaced entirely. Agent identity files carry over unchanged.

---

## 2. Architecture

### 2.1 Request Flow

```
                    +------------------+
                    |   Request Source  |
                    | CLI | Discord |   |
                    | Cron             |
                    +--------+---------+
                             |
                    +--------v---------+
                    | Agent Resolution |
                    | (channel -> agent|
                    |  or --agent flag)|
                    +--------+---------+
                             |
                    +--------v---------+
                    | Model Override?   |
                    | --model flag or   |
                    | /model in Discord |
                    +--------+---------+
                             |
               +-------------v--------------+
               | Dispatcher                 |
               | Claude? -> acpx            |
               | Ollama? -> httpx POST      |
               +-------------+--------------+
                             |
               +-------------v--------------+
               | Post-processing            |
               | - log routing decision     |
               | - notify Discord (cron)    |
               +-----------------------------+
```

### 2.2 Two Dispatch Paths

**Claude path (subscription, via acpx):**

Global flags (`--cwd`, `--approve-all`, `--system-prompt`) go **before** the agent
name. Session flags (`-s`, `exec`) go **after** the agent name.

Discord (persistent session):
```bash
acpx --cwd /workspace/fitness-coach \
  --model claude-sonnet-4-6 \
  --approve-all \
  --system-prompt "$COMBINED_SYSTEM_PROMPT" \
  claude -s "coach-thread-123" \
  --file /tmp/prompt.md
```

Cron/CLI (one-shot, no session saved):
```bash
acpx --cwd /workspace/fitness-coach \
  --model claude-sonnet-4-6 \
  --approve-all \
  --system-prompt "$COMBINED_SYSTEM_PROMPT" \
  claude exec \
  --file /tmp/prompt.md
```

Notes:
- Model is set via `--model` flag (acpx global flag). `ANTHROPIC_MODEL` env var also works
  but the flag is more explicit and was confirmed working in Phase 1 live tests.
- `--approve-all` replaces Claude Code's `--permission-mode bypassPermissions`. acpx uses
  its own permission model.
- `--system-prompt` is injected once on `session/new` and persisted in
  `session_options`. Follow-up messages to the same session do NOT re-send it.
- Known bug: Bash subprocesses spawned inside Claude Code may see `/` as cwd despite
  `--cwd`. File tool operations respect cwd correctly. Workaround: inject workspace path
  into system prompt if Bash cwd matters for the agent.

**Ollama path (local or remote, free):**
```python
response = httpx.post(
    f"{model.endpoint}/chat/completions",
    json={"model": model.ollama_name, "messages": messages}
)
```

### 2.3 Session Strategy

| Source | acpx mode | Session name | Why |
|--------|-----------|-------------|-----|
| Cron jobs | `acpx claude exec` | none (one-shot) | Self-contained. Agent reads files, does work, exits. No accumulated context. |
| CLI one-offs | `acpx claude exec` | none (one-shot) | Same reasoning. Clean context every time. |
| Discord thread (new) | `acpx claude -s <agent>-<thread_id>` | agent + thread ID | Starts persistent session. Claude reads identity files, gains context. |
| Discord thread (follow-up) | `acpx claude -s <agent>-<thread_id>` | same session | Continues conversation. Context preserved from first message. |
| Discord thread (idle > 15 min) | session auto-expires via TTL | -- | acpx queue owner TTL handles this. Default 300s, configurable. |

**Why this works without session management code:** acpx handles all session
lifecycle internally. Named sessions survive process restarts. Crash reconnect
is automatic. The daemon just calls `acpx` with the right session name and
acpx handles the rest. No session ID tracking, no idle timers, no cleanup cron
needed in `arc`.

### 2.4 System Prompt Injection

Each agent has multiple identity files (AGENTS.md, IDENTITY.md, SOUL.md, USER.md,
TOOLS.md). The dispatcher concatenates them and passes via `--system-prompt`:

```python
async def build_system_prompt(agent: AgentConfig) -> str:
    """Read and concatenate all agent identity files."""
    parts = []
    for filename in agent.system_prompt_files:
        path = Path(agent.workspace) / filename
        if path.exists():
            parts.append(f"# {filename}\n\n{path.read_text()}")
    return "\n\n---\n\n".join(parts)
```

For Claude, this combined string is passed to acpx via `--system-prompt`.
This preserves Claude Code's built-in capabilities (file tools, shell, etc.)
while adding the agent's persona.

For Ollama, the same string is injected as a system message in the chat
completions request.

### 2.5 Security

**Container isolation (LXC):**

The LXC container is the primary security boundary. Claude Code runs inside
the container and cannot access the Proxmox host or other LXCs.

**Non-root execution:**

Create a dedicated `arc` user in the LXC. The daemon, Claude Code, and acpx
all run as this user. Never run as root.

```bash
useradd -m -s /bin/bash arc
# Workspace owned by arc user
chown -R arc:arc /workspace
```

The systemd service runs as the `arc` user (user service, not system service).

**Network isolation:**

Restrict outbound network access from the LXC using iptables. Only allow:

```bash
# Allow loopback
iptables -A OUTPUT -o lo -j ACCEPT

# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow DNS
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# Allow Anthropic API (Claude Code auth + inference)
iptables -A OUTPUT -d api.anthropic.com -j ACCEPT
iptables -A OUTPUT -d claude.ai -j ACCEPT

# Allow GitHub (git push/pull)
iptables -A OUTPUT -d github.com -j ACCEPT

# Allow Discord API
iptables -A OUTPUT -d discord.com -j ACCEPT
iptables -A OUTPUT -d gateway.discord.gg -j ACCEPT

# Allow Ollama endpoints
iptables -A OUTPUT -d <LOCAL_OLLAMA_IP> -p tcp --dport 11434 -j ACCEPT
iptables -A OUTPUT -d <KYLE_TAILSCALE_IP> -p tcp --dport 11434 -j ACCEPT

# Block everything else
iptables -A OUTPUT -j DROP
```

This prevents a compromised agent from exfiltrating data to arbitrary servers.

**Permission mode:**

Instead of `bypassPermissions` (which disables all safety checks), prefer
Claude Code's `auto` mode. Auto mode uses a server-side classifier to catch
dangerous actions while letting safe ones through. This reduces permission
prompts by ~84% while maintaining security.

```yaml
# In agent config
permission_mode: auto      # preferred over bypassPermissions
```

If `auto` mode causes issues in headless operation, fall back to
`bypassPermissions` but rely on the LXC + network isolation as the
security boundary.

**Secrets management:**

- Discord bot token stored in `~/.arc/.env` with `chmod 600`, owned by `arc` user
- `.env` added to `.gitignore` (never committed)
- SSH keys for git: use repo-scoped deploy keys, not personal SSH keys.
  Read-only deploy keys for repos that don't need writes. Write-access deploy
  keys scoped to specific repos (e.g. fitness-data) for repos that do.
- No API keys, passwords, or credentials stored in workspace directories.
  Audit workspace contents before deploying.

**Claude Code workspace restrictions:**

Claude Code with `--cwd /workspace/fitness-coach` can read and write anything
in that directory tree. Ensure workspaces contain only:
- Agent identity files (AGENTS.md, SOUL.md, etc.)
- Agent data files (plans, logs, profiles)
- Agent skills (.claude/skills/)

Do NOT store in workspaces:
- SSH keys or credentials
- Personal documents
- System configuration files

### 2.6 Component Diagram

```
+-----------------------------------------------------------+
|                   arc daemon (Python)                      |
|                   systemd user service                     |
|                                                           |
|  +------------+  +------------+  +---------------------+  |
|  | Unix Socket|  | Discord Bot|  | APScheduler         |  |
|  | Listener   |  | (discord.py|  | (cron jobs)         |  |
|  +-----+------+  +-----+------+  +----------+----------+  |
|        |               |                    |              |
|        +-------+-------+--------------------+              |
|                |                                           |
|        +-------v--------+                                  |
|        | Request Handler |                                 |
|        +-------+--------+                                  |
|                |                                           |
|        +-------v--------+                                  |
|        | Dispatcher      |                                 |
|        | acpx | httpx    |                                 |
|        +----------------+                                  |
+-----------------------------------------------------------+
         |                    |
         v                    v
  acpx -> Claude Code     Ollama (local/remote)
  (subscription)           (free)
```

---

## 3. Project Structure

```
arc/
├── pyproject.toml
├── README.md
├── tests/
│   ├── conftest.py
│   ├── test_dispatcher.py
│   ├── test_agents.py
│   ├── test_cron.py
│   ├── test_discord_bridge.py
│   ├── test_cli.py
│   ├── test_ipc.py
│   ├── test_config.py
│   ├── test_setup.py
│   ├── test_import_openclaw.py
│   └── test_integration.py
├── src/
│   └── arc/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py                  # Typer app, all subcommands
│       ├── daemon.py               # long-running process, socket, lifecycle
│       ├── dispatcher.py           # acpx (Claude) + httpx (Ollama)
│       ├── agents.py               # agent config loader, system prompt builder
│       ├── cron.py                 # APScheduler wrapper, job CRUD
│       ├── discord_bridge.py       # discord.py bot
│       ├── ipc.py                  # Unix socket client/server
│       ├── config.py               # config loading, defaults, validation
│       ├── setup_wizard.py         # interactive first-run setup
│       ├── import_openclaw.py      # one-time migration
│       ├── types.py                # shared dataclasses
│       └── utils.py                # logging, git ops, helpers
└── scripts/
    ├── install.sh                  # LXC setup, deps, clone repos, run wizard
    └── arc-daemon.service          # systemd unit template
```

### pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "arc-cli"
version = "0.1.0"
description = "Agent Router CLI -- lightweight agent dispatch and scheduling"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "httpx>=0.27",
    "apscheduler>=3.10,<4",
    "discord.py>=2.3",
    "pyyaml>=6.0",
]

[project.scripts]
arc = "arc.cli:app"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "pytest-cov>=5.0",
    "ruff>=0.4",
]
```

**Note:** `acpx` is installed separately via npm (`npm install -g acpx@latest`).
It is a Node.js CLI tool, not a Python package. The daemon shells out to it.

### Runtime Config Directory

```
~/.arc/
├── config.yaml                     # main config
├── agents/
│   ├── coach.yaml
│   ├── main.yaml
│   └── trainer.yaml
├── cron/
│   └── jobs.yaml
├── .env                            # DISCORD_BOT_TOKEN
├── logs/
│   ├── daemon.log
│   ├── routing.jsonl
│   └── cron.jsonl
└── arc.sock                        # Unix domain socket (runtime)
```

---

## 4. Agent Configuration

### 4.1 Agent YAML Schema

Each agent maps to a set of OpenClaw identity files in a workspace directory.
The agent config tells `arc` which files to load and which model to use.

```yaml
# ~/.arc/agents/coach.yaml
name: coach
description: "Coach Kai - personal fitness coach"
workspace: /workspace/fitness-coach

# Identity files to concatenate as system prompt
# Order matters -- they are joined in this order
system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md

# Default model for this agent
model: claude-sonnet-4-6

# Models this agent is allowed to use (for /model override)
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5

# acpx permission mode for headless operation
permission_mode: auto

# Discord channel binding
discord:
  channel_id: "1484079455025627307"
```

```yaml
# ~/.arc/agents/main.yaml
name: main
description: "General assistant"
workspace: /workspace/main
system_prompt_files:
  - agent.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md
model: claude-haiku-4-5        # cheaper model for general chat
allowed_models:
  - claude-haiku-4-5
  - claude-sonnet-4-6
  - ollama/qwen3:8b            # can also use local
permission_mode: auto
discord:
  channel_id: "1481112048367570976"
```

```yaml
# ~/.arc/agents/trainer.yaml
name: trainer
description: "Training-specific agent"
workspace: /workspace/trainer
system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md
model: ollama/qwen3:8b          # runs on local model by default
allowed_models:
  - ollama/qwen3:8b
  - ollama/kyle-deepseek
  - claude-haiku-4-5
permission_mode: auto
```

### 4.2 How Models Are Resolved

Priority order:
1. `--model` CLI flag (highest priority)
2. `/model` Discord command (sticky per channel until reset)
3. Agent config `model` field (default)

If the requested model is not in the agent's `allowed_models`, the request
is rejected with an error message.

---

## 5. Config Schema

### 5.1 `~/.arc/config.yaml`

```yaml
daemon:
  auto_start: true
  socket_path: ~/.arc/arc.sock
  log_level: info
  pid_file: ~/.arc/daemon.pid

acpx:
  command: acpx                     # path to acpx binary
  default_agent: claude             # acpx agent name (claude, codex, etc.)
  session_ttl: 300                  # seconds to keep session warm after last prompt
  output_format: text               # text | ndjson | quiet

ollama:
  endpoints:                        # named Ollama endpoints
    local:
      url: http://localhost:11434/v1
    kyle:
      url: http://kyle-nuc.tailnet:11434/v1

discord:
  enabled: false
  token_env: DISCORD_BOT_TOKEN
  guild_id: ""
  thread_mode: true
  rate_limit:
    messages_per_minute: 5

git:
  auto_pull: true
  auto_commit: true
  auto_push: false

timeouts:
  acpx_request: 300
  ollama_request: 120
  ipc_connect: 5

output:
  default_format: raw
  color: true

logging:
  log_routing: true
```

### 5.2 Cron Jobs

```yaml
# ~/.arc/cron/jobs.yaml
jobs:
  weekly-plan:
    description: "Generate weekly training plan every Sunday at 7 PM"
    schedule: "0 19 * * 0"
    agent: coach
    prompt: >
      It's a new week. Pull my Strava data from the past week, review what I
      actually completed vs what was planned, check flags.md for any issues,
      and generate the new weekly plan file following the standard format.
    notify: discord
    enabled: true

  daily-workout:
    description: "Morning workout briefing"
    schedule: "0 7 * * *"
    agent: coach
    prompt: >
      Deliver today's workout briefing.
    notify: discord
    enabled: true

  heartbeat:
    description: "Background log scanner"
    schedule: "*/30 * * * *"
    agent: coach
    model: claude-haiku-4-5          # override: use cheaper model for heartbeat
    prompt: >
      Read HEARTBEAT.md and follow it strictly.
    notify: discord_on_urgent
    enabled: true
```

**Note:** Cron jobs can override the agent's default model with a `model` field.
The heartbeat runs every 30 minutes; using Haiku instead of Sonnet saves
significant subscription tokens.

---

## 6. Module Specifications

### 6.1 `dispatcher.py`

Two dispatch paths. No abstraction layer.

```python
import asyncio
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass

import httpx

from arc.agents import AgentConfig, build_system_prompt
from arc.config import ArcConfig


@dataclass
class DispatchResult:
    output: str
    model_used: str
    dispatch_type: str      # "acpx" or "ollama"


class DispatchError(Exception):
    pass


async def dispatch(
    prompt: str,
    agent: AgentConfig,
    model_override: str | None = None,
    session_name: str | None = None,
    one_shot: bool = False,
) -> DispatchResult:
    """Route a prompt to the appropriate backend."""
    model = model_override or agent.model

    # Validate model is allowed for this agent
    if model_override and agent.allowed_models:
        if model not in agent.allowed_models:
            raise DispatchError(
                f"Model '{model}' is not allowed for agent '{agent.name}'. "
                f"Allowed: {', '.join(agent.allowed_models)}"
            )

    if model.startswith("ollama/"):
        return await dispatch_ollama(prompt, agent, model)
    elif model.startswith("claude-"):
        return await dispatch_acpx(
            prompt, agent, model, session_name, one_shot
        )
    else:
        raise DispatchError(f"Unknown model type: {model}")


async def dispatch_acpx(
    prompt: str,
    agent: AgentConfig,
    model: str,
    session_name: str | None = None,
    one_shot: bool = False,
) -> DispatchResult:
    """Dispatch via acpx to Claude Code."""
    config = load_config()

    # Build combined system prompt from agent identity files
    system_prompt = await build_system_prompt(agent)

    # Write system prompt to temp file to avoid shell argument limits
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', delete=False
    ) as f:
        f.write(system_prompt)
        system_prompt_file = f.name

    try:
        # Build acpx command
        cmd = [config.acpx.command, config.acpx.default_agent]

        if one_shot:
            cmd.append("exec")
        elif session_name:
            cmd.extend(["-s", session_name])

        cmd.extend([
            "--cwd", agent.workspace,
            "--permission-mode", agent.permission_mode,
            "--format", "quiet",
        ])

        # Set model via environment variable
        env = {
            **dict(os.environ),
            "CLAUDE_CODE_MODEL": model,
        }

        # Pass prompt via --file to avoid shell escaping issues
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False
        ) as pf:
            pf.write(prompt)
            prompt_file = pf.name

        cmd.extend(["--file", prompt_file])

        # Run acpx
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.timeouts.acpx_request
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise DispatchError(
                f"acpx timed out after {config.timeouts.acpx_request}s"
            )

        if proc.returncode != 0:
            raise DispatchError(
                f"acpx exited {proc.returncode}: {stderr.decode()}"
            )

        return DispatchResult(
            output=stdout.decode().strip(),
            model_used=model,
            dispatch_type="acpx"
        )

    finally:
        Path(system_prompt_file).unlink(missing_ok=True)
        Path(prompt_file).unlink(missing_ok=True)


async def dispatch_ollama(
    prompt: str,
    agent: AgentConfig,
    model: str,
) -> DispatchResult:
    """Dispatch via httpx to Ollama API."""
    config = load_config()

    # Parse model string: "ollama/qwen3:8b" or "ollama/kyle/deepseek:32b"
    model_parts = model.removeprefix("ollama/")

    # Determine endpoint
    if "/" in model_parts:
        endpoint_name, ollama_model = model_parts.split("/", 1)
        endpoint = config.ollama.endpoints[endpoint_name].url
    else:
        ollama_model = model_parts
        endpoint = config.ollama.endpoints["local"].url

    # Build messages
    messages = []

    # Inject system prompt from agent identity files
    system_prompt = await build_system_prompt(agent)
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Inject context files for local models (they can't read filesystem)
    if agent.local_context_files:
        context_parts = []
        for f in agent.local_context_files:
            path = Path(agent.workspace) / f
            if path.exists():
                context_parts.append(f"--- {f} ---\n{path.read_text()}")
        if context_parts:
            messages.append({
                "role": "system",
                "content": "Reference files:\n\n" + "\n\n".join(context_parts)
            })

    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(
            timeout=config.timeouts.ollama_request
        ) as client:
            response = await client.post(
                f"{endpoint}/chat/completions",
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "stream": False
                }
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise DispatchError(f"Ollama timed out after {config.timeouts.ollama_request}s")
    except httpx.ConnectError:
        raise DispatchError(f"Cannot connect to Ollama at {endpoint}")

    data = response.json()
    return DispatchResult(
        output=data["choices"][0]["message"]["content"],
        model_used=model,
        dispatch_type="ollama"
    )
```

### 6.2 `agents.py`

```python
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class AgentConfig:
    name: str
    workspace: str
    system_prompt_files: list[str]
    model: str
    description: str = ""
    allowed_models: list[str] = field(default_factory=list)
    permission_mode: str = "bypassPermissions"
    local_context_files: list[str] = field(default_factory=list)
    discord: dict = field(default_factory=dict)


def load_agent(name: str) -> AgentConfig:
    """Load agent config from ~/.arc/agents/<name>.yaml."""
    path = Path("~/.arc/agents").expanduser() / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Agent '{name}' not found at {path}")
    data = yaml.safe_load(path.read_text())
    return AgentConfig(**data)


def list_agents() -> list[AgentConfig]:
    """List all configured agents."""
    agents_dir = Path("~/.arc/agents").expanduser()
    agents = []
    for path in sorted(agents_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        agents.append(AgentConfig(**data))
    return agents


async def build_system_prompt(agent: AgentConfig) -> str:
    """Concatenate all agent identity files into a single system prompt."""
    parts = []
    for filename in agent.system_prompt_files:
        path = Path(agent.workspace) / filename
        if path.exists():
            parts.append(f"# {filename}\n\n{path.read_text()}")
        else:
            # Log warning but don't fail -- some files may be optional
            import logging
            logging.getLogger("arc").warning(
                f"Agent '{agent.name}': identity file not found: {path}"
            )
    return "\n\n---\n\n".join(parts)


def resolve_agent_for_channel(channel_id: str) -> AgentConfig | None:
    """Find the agent bound to a Discord channel."""
    for agent in list_agents():
        if agent.discord.get("channel_id") == channel_id:
            return agent
    return None
```

### 6.3 `daemon.py`

The daemon runs three subsystems: Unix socket listener, Discord bot, APScheduler.

```python
class ArcDaemon:
    def __init__(self, config: ArcConfig):
        self.config = config
        self.scheduler = AsyncIOScheduler()
        self.discord_bot = None
        self.model_overrides: dict[str, str] = {}  # channel_id -> model

    async def start(self):
        write_pid(self.config.daemon.pid_file)

        # Start Unix socket listener
        self.socket_server = await start_socket_server(
            self.config.daemon.socket_path,
            self.handle_request
        )

        # Load and start cron jobs
        jobs = load_cron_jobs()
        for job in jobs:
            if job.enabled:
                self.scheduler.add_job(
                    self.run_cron_job,
                    CronTrigger.from_crontab(job.schedule),
                    args=[job], id=job.name
                )
        self.scheduler.start()

        # Start Discord bot if enabled
        if self.config.discord.enabled:
            self.discord_bot = ArcDiscordBot(self.config, self)
            asyncio.create_task(self.discord_bot.start())

        log.info("arc daemon started")

        try:
            await asyncio.Event().wait()
        finally:
            await self.shutdown()

    async def handle_request(self, request: dict) -> dict:
        """Central request handler."""
        prompt = request["prompt"]
        agent_name = request.get("agent")
        model_override = request.get("model")
        source = request.get("source", "cli")     # cli | discord | cron
        thread_id = request.get("thread_id")

        # Resolve agent
        agent = load_agent(agent_name) if agent_name else None
        if not agent:
            return {"status": "error", "error": f"Unknown agent: {agent_name}"}

        # Check for /model override (Discord only)
        channel_id = request.get("channel_id")
        if not model_override and channel_id in self.model_overrides:
            model_override = self.model_overrides[channel_id]

        # Determine session strategy
        if source == "discord" and thread_id:
            session_name = f"{agent.name}-{thread_id}"
            one_shot = False
        else:
            session_name = None
            one_shot = True

        # Git pull if agent has a workspace
        if agent.workspace and self.config.git.auto_pull:
            await git_pull(agent.workspace)

        # Dispatch
        try:
            result = await dispatch(
                prompt=prompt,
                agent=agent,
                model_override=model_override,
                session_name=session_name,
                one_shot=one_shot,
            )
        except DispatchError as e:
            return {"status": "error", "error": str(e)}

        # Log routing decision
        if self.config.logging.log_routing:
            append_jsonl("~/.arc/logs/routing.jsonl", {
                "timestamp": now_iso(),
                "agent": agent.name,
                "model": result.model_used,
                "dispatch_type": result.dispatch_type,
                "source": source,
                "one_shot": one_shot,
                "prompt_preview": prompt[:100],
            })

        return {"status": "ok", "result": result.output}

    async def run_cron_job(self, job):
        """Execute a cron job."""
        log.info(f"Cron job running: {job.name}")
        try:
            result = await self.handle_request({
                "prompt": job.prompt,
                "agent": job.agent,
                "model": job.model,      # optional per-job model override
                "source": "cron",
            })

            if result["status"] == "ok":
                # Notify
                if job.notify == "discord" and self.discord_bot:
                    await self.discord_bot.send_to_default_channel(
                        result["result"], job.agent
                    )
                elif (job.notify == "discord_on_urgent"
                      and self.discord_bot
                      and "urgent" in result["result"].lower()):
                    await self.discord_bot.send_to_default_channel(
                        result["result"], job.agent
                    )

            # Log
            append_jsonl("~/.arc/logs/cron.jsonl", {
                "timestamp": now_iso(),
                "job": job.name,
                "status": result["status"],
                "output_preview": result.get("result", "")[:200],
            })

        except Exception as e:
            log.error(f"Cron job failed: {job.name}: {e}")

    def set_model_override(self, channel_id: str, model: str | None):
        """Set or clear a /model override for a Discord channel."""
        if model:
            self.model_overrides[channel_id] = model
        else:
            self.model_overrides.pop(channel_id, None)
```

### 6.4 `discord_bridge.py`

```python
class ArcDiscordBot(discord.Client):
    def __init__(self, config, daemon):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.daemon = daemon

    async def on_message(self, message):
        if message.author == self.user:
            return

        if str(message.guild.id) != self.config.discord.guild_id:
            return

        # Resolve agent from channel
        agent = resolve_agent_for_channel(str(message.channel.id))
        # Also check parent channel if this is a thread
        if not agent and isinstance(message.channel, discord.Thread):
            agent = resolve_agent_for_channel(str(message.channel.parent_id))
        if not agent:
            return

        # Check if bot was mentioned (or always respond in bound channels)
        if self.user not in message.mentions:
            return

        prompt = message.content.replace(f"<@{self.user.id}>", "").strip()

        # Handle /model command
        if prompt.startswith("/model"):
            parts = prompt.split(maxsplit=1)
            if len(parts) == 2:
                model = parts[1].strip()
                if model == "reset":
                    self.daemon.set_model_override(
                        str(message.channel.id), None
                    )
                    await message.reply(f"Model reset to agent default.")
                elif model in (agent.allowed_models or []):
                    self.daemon.set_model_override(
                        str(message.channel.id), model
                    )
                    await message.reply(f"Model set to {model}.")
                else:
                    allowed = ", ".join(agent.allowed_models or ["(none)"])
                    await message.reply(
                        f"Model '{model}' not allowed. Options: {allowed}"
                    )
            else:
                current = self.daemon.model_overrides.get(
                    str(message.channel.id), agent.model
                )
                await message.reply(f"Current model: {current}")
            return

        # Get or create thread
        if (self.config.discord.thread_mode
                and not isinstance(message.channel, discord.Thread)):
            thread = await message.create_thread(name=prompt[:50])
            target = thread
            thread_id = str(thread.id)
        else:
            target = message.channel
            thread_id = str(message.channel.id)

        # Dispatch
        async with target.typing():
            result = await self.daemon.handle_request({
                "prompt": prompt,
                "agent": agent.name,
                "source": "discord",
                "thread_id": thread_id,
                "channel_id": str(message.channel.id),
            })

        # Send response
        output = result.get("result", result.get("error", "No response"))
        for chunk in split_message(output, max_length=2000):
            await target.send(chunk)

    async def send_to_default_channel(self, content, agent_name):
        """Send cron output to the agent's configured channel."""
        agent = load_agent(agent_name)
        channel_id = agent.discord.get("channel_id")
        if channel_id:
            channel = self.get_channel(int(channel_id))
            if channel:
                for chunk in split_message(content, max_length=2000):
                    await channel.send(chunk)
```

---

## 7. CLI Command Reference

### 7.1 `arc ask`

```bash
# With agent (uses agent's default model)
arc ask --agent coach "What's my workout today?"

# Override model
arc ask --agent coach --model claude-haiku-4-5 "What day is leg day?"

# Local model
arc ask --agent trainer --model ollama/qwen3:8b "Quick question"

# No agent (one-shot, no system prompt)
arc ask --model claude-sonnet-4-6 "What's 2+2?"

# Pipe stdin
echo "Summarize this" | arc ask --agent main

# Pretty output
arc ask --pretty --agent coach "Explain periodization"
```

### 7.2 `arc agent`

```bash
arc agent list
arc agent show coach
arc agent create                     # interactive
arc agent create --from ./coach.yaml
arc agent edit coach                 # opens $EDITOR
arc agent delete old-agent
arc agent clone coach hiking-coach
```

### 7.3 `arc cron`

```bash
arc cron list
arc cron add                         # interactive
arc cron add --name strava-summary --schedule "0 18 * * 5" \
  --agent coach --prompt "Summarize training this week"
arc cron edit weekly-plan
arc cron enable/disable strava-summary
arc cron run daily-workout           # execute immediately
arc cron remove strava-summary
arc cron history daily-workout --last 5
arc cron next
```

### 7.4 `arc status`

```bash
arc status
```

Shows daemon state, all configured agents, and next cron fire times in one command.
Falls back gracefully when the daemon is not running by reading config files directly
and computing next fire times via APScheduler's `CronTrigger`.

```
daemon    running (pid=12345, socket=~/.arc/arc.sock)

agents
  coach    claude-sonnet-4-6   /workspace/fitness-coach   discord 9999
  trainer  ollama/qwen3:8b     /workspace/trainer

cron
  weekly-plan   next: in 3h 14m
  heartbeat     next: in 8 min   disabled
```

Sends `{"op": "status"}` over IPC. The daemon responds with agent list, cron
next-run times (from live APScheduler `job.next_run_time`), and PID.

### 7.5 `arc tokens`

```bash
# Scoped to all arc agents (default)
arc tokens

# Scoped to one agent's workspace
arc tokens --agent coach

# Change period
arc tokens --period week
arc tokens --period month
arc tokens --period all

# Full interactive codeburn TUI with charts
arc tokens --cmd report

# Export CSV or JSON
arc tokens --cmd export
```

Thin wrapper around [codeburn](https://github.com/getagentseal/codeburn), which reads
Claude Code's `~/.claude/projects/` usage store written by acpx on every dispatch.

By default scopes to all arc agent workspaces via `--project <workspace-basename>`.
Without `--agent`, passes one `--project` flag per configured agent. With `--agent`,
scopes to that agent only. Falls back to global output if no agents are configured.

Requires codeburn: `npm install -g codeburn`. Falls back to `npx codeburn` if not
globally installed.

### 7.6 `arc daemon`

```bash
arc daemon start
arc daemon start --foreground        # for systemd
arc daemon stop
arc daemon restart
arc daemon status
arc daemon install                   # generate systemd unit
```

### 7.5 `arc setup`

```bash
arc setup                            # interactive first-run wizard
```

### 7.6 `arc import-openclaw`

```bash
arc import-openclaw                  # from ~/.openclaw/
arc import-openclaw --from /path/
arc import-openclaw --dry-run
```

### 7.7 `arc log`

```bash
arc log routing --last 20
arc log cron --last 10
arc log tail
```

### 7.8 `arc config`

```bash
arc config show
arc config edit
arc config set daemon.auto_start false
```

---

## 8. Installation

### 8.1 LXC Container

```bash
# Proxmox host
pct create 200 local:vztmpl/ubuntu-24.04-standard_24.04-1_amd64.tar.zst \
  --hostname arc \
  --cores 2 \
  --memory 4096 \
  --rootfs local-lvm:20 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1 \
  --start 1

# Bind-mount workspace
mkdir -p /opt/arc-workspace
chown -R 100000:100000 /opt/arc-workspace
pct set 200 -mp0 /opt/arc-workspace,mp=/workspace
```

### 8.2 Inside the LXC

```bash
# Create non-root user
useradd -m -s /bin/bash arc
usermod -aG sudo arc    # only for initial setup, remove after

# System deps
apt-get update
apt-get install -y python3 python3-pip python3-venv git curl iptables

# Node.js >= 22.12.0 (required for acpx)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# Switch to arc user for everything below
su - arc

# Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash
# Authenticate (headless: device code flow)
claude auth login

# Configure Claude Code for headless operation (prefer auto mode)
claude config set permissions.defaultMode "auto"

# acpx
npm install -g acpx@latest

# arc
git clone git@github.com:eknorr/arc.git /opt/arc
cd /opt/arc
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Clone workspaces (use deploy keys, not personal SSH key)
git clone git@github.com:eknorr/fitness-data.git /workspace/fitness-coach
# ... other agent workspaces

# Secure .env
touch ~/.arc/.env
chmod 600 ~/.arc/.env

# Setup
arc setup

# Network isolation (run as root, then drop back to arc user)
exit  # back to root
# Apply iptables rules (see section 2.5 for full ruleset)
# Save with: iptables-save > /etc/iptables.rules
# Restore on boot via /etc/network/if-pre-up.d/iptables

# Remove sudo access from arc user (no longer needed)
deluser arc sudo

# Start as arc user
su - arc
arc daemon start
# Or: arc daemon install && systemctl --user enable --now arc-daemon
```

### 8.3 Verify

```bash
# Test acpx directly
acpx claude exec --cwd /workspace/fitness-coach "echo hello"

# Test arc
arc ask --agent coach "What's my workout today?"

# Test Discord
arc daemon start   # then @mention in Discord
```

---

## 9. Error Handling

| Error | Handling |
|-------|----------|
| acpx returns non-zero exit | Log stderr, return error to user |
| acpx times out | Kill process after configurable timeout, return error |
| Ollama endpoint unreachable | Return error with clear message ("Is Ollama running?") |
| Ollama request timeout | Return error |
| Agent not found | Return error listing available agents |
| Model not in allowed_models | Return error listing allowed models |
| Identity file missing | Log warning, continue with available files |
| Discord message send fails | Log error, retry once |
| Cron job fails | Log to cron.jsonl, don't retry (next run will try again) |
| IPC socket connection lost | CLI prints "daemon not running" |
| Config file corrupt | Print error, exit on startup. Log and keep old config on reload |
| Git pull fails | Log warning, continue with stale data |
| acpx session crash | acpx auto-reconnects (built-in crash reconnect) |
| Node.js/acpx not installed | Setup wizard detects and provides install instructions |

---

## 10. Implementation Plan

### Phase 1: Foundation -- COMPLETE
- [x] Project scaffolding: pyproject.toml, src layout, pytest config
- [x] `types.py`: dataclasses (AgentConfig, CronJob, DispatchResult, etc.)
- [x] `config.py`: load/save/validate config.yaml, create defaults
- [x] `agents.py`: load_agent(), list_agents(), build_system_prompt(),
      resolve_agent_for_channel()
- [x] `dispatcher.py`: dispatch(), dispatch_acpx(), dispatch_ollama()
- [x] `utils.py`: helpers (git ops, JSONL logging, split_message, PID, load_dotenv)
- [x] `cli.py`: `arc ask` command (direct dispatch, no daemon yet)
- [x] Tests: test_config, test_agents, test_dispatcher (mocked)
- **Milestone:** `arc ask --agent coach "Hello"` returns a response via acpx ✓
- **Milestone:** `arc ask --agent trainer --model ollama/qwen3:8b "Hello"` works ✓

### Phase 2: Daemon + IPC -- COMPLETE
- [x] `ipc.py`: Unix socket protocol (JSON over length-prefixed framing)
- [x] `daemon.py`: ArcDaemon class, socket listener, handle_request(),
      model_overrides dict, `op: status` handler
- [x] `arc daemon start/stop/status/restart/install`
- [x] Auto-start: daemon starts on first CLI command if configured
- [x] Refactor `arc ask` to send over IPC when daemon is running
- [x] Tests: test_ipc, test_daemon (mocked)
- **Milestone:** daemon runs, `arc ask` talks to it over socket ✓

### Phase 3: Discord -- COMPLETE
- [x] `discord_bridge.py`: ArcDiscordBot, on_message, channel-to-agent
      resolution, /model command, rate limiting
- [x] `require_mention` per-agent flag (defaults false, matching OpenClaw behavior)
- [x] Wire into daemon
- [x] Load DISCORD_BOT_TOKEN from ~/.arc/.env
- [x] Tests: test_discord_bridge (mocked)
- **Milestone:** message in Discord channel, get agent response inline ✓
- **Milestone:** `/model haiku` switches model for channel ✓
- **Note:** thread creation dropped -- `thread_mode: false` is the default.
  Thread mode is still configurable via config.yaml but off by default.

### Phase 4: Cron -- COMPLETE
- [x] `cron.py`: CronManager, load_jobs, set_job_enabled, APScheduler integration
- [x] `arc cron list/run/next/enable/disable`
- [x] Wire into daemon
- [x] Per-job model override (e.g. heartbeat on Haiku)
- [x] Notification dispatch (discord, discord_on_urgent)
- [x] Tests: test_cron
- **Milestone:** cron job runs on schedule, output posts to Discord ✓ (verified live)
- **Known gap:** `arc cron run` (manual) dispatches but skips Discord notify and
  cron.jsonl logging. Scheduled runs go through `run_cron_job` and behave correctly.
  Fix: route `arc cron run` through `run_cron_job` via a dedicated IPC op.
- **Missing:** `arc cron add/remove/edit/history` -- deferred to Phase 6.

### Phase 5: Setup + Migration -- COMPLETE
- [x] `setup_wizard.py`: dep checks, dir creation, default config, Discord config
- [x] `import_openclaw.py`: parse openclaw.json, convert agents + cron to arc format
- [x] `arc setup` command (interactive, prompts for Discord token/guild)
- [x] `arc import-openclaw [--from <dir>] [--dry-run]`
- [x] `scripts/install.sh`: LXC bootstrap (apt, Node 22, Claude Code, acpx, arc, iptables)
- [x] `scripts/arc-daemon.service`: systemd unit template
- [x] Tests: test_setup, test_import_openclaw
- **Milestone:** fresh install to working system in one session ✓

### Phase 6: Polish
- [x] `arc tokens` - codeburn integration for per-agent token observability (gh #1 for --all flag)
- [x] `arc status` - daemon state, agents, cron next-run in one command
- [x] Shell completions (zsh, hand-written at ~/.zfunc/_arc)
- [ ] `arc log` commands
- [ ] `arc config show/edit/set`
- [ ] `arc agent list/show/create/edit/delete/clone`
- [ ] `arc cron add/remove/edit/history`
- [ ] Fix `arc cron run` to trigger Discord notify and cron logging
- [ ] README.md with full usage docs
- [ ] Error messages review
- [ ] Final test pass
- [ ] `arc --version`
- **Milestone:** all tests pass, README complete

### Phase 7: TUI (arc tui)

> Tracked in gh #5. Depends on Phase 6 being complete -- the TUI wraps the same
> underlying operations as the Phase 6 CLI commands, so those must exist first.

A k9s-style management interface for arc. Goal: common operational tasks (changing
an agent's model, toggling a cron job, checking status) without hand-editing YAML.
Not a replacement for `arc ask` -- prompt dispatch stays in the CLI.

**Library:** [Textual](https://textual.textualize.io/) (`pip install textual`)

Add to `pyproject.toml` dependencies. New files:

```
src/arc/
  tui/
    __init__.py
    app.py          # ArcTUI(App) -- entry point, screen routing
    screens/
      agents.py     # AgentsScreen
      cron.py       # CronScreen
      config.py     # ConfigScreen
      status.py     # StatusScreen
    widgets/
      agent_detail.py
      cron_detail.py
```

Invoked via `arc tui`.

#### Screens

**Status screen (default/home)**

Shown on launch. Auto-refreshes every 5 seconds via Textual's `set_interval`.

```
arc  [Agents]  [Cron]  [Config]  [Status*]           q:quit  r:refresh

  daemon    running  pid=12345  socket=~/.arc/arc.sock

  AGENTS
  coach    claude-sonnet-4-6   /workspace/fitness-coach   discord 9999
  trainer  ollama/qwen3:8b     /workspace/trainer

  CRON
  weekly-plan   next: in 3h 14m   enabled
  heartbeat     next: in 8 min    enabled
  daily-brief   --                disabled
```

Sends `{"op": "status"}` IPC op (already implemented). Falls back to config-file
read when daemon is not running (same logic as `arc status` CLI command).

Keybindings:
- `r` - manual refresh
- `s` - start/stop daemon (calls `arc daemon start/stop` as subprocess)
- `tab` - cycle to next screen

**Agents screen**

```
arc  [Agents*]  [Cron]  [Config]  [Status]           q:quit  n:new  d:delete

  coach    claude-sonnet-4-6   /workspace/fitness-coach
  trainer  ollama/qwen3:8b     /workspace/trainer

  ── coach ──────────────────────────────────────────────────────
  name:              coach
  description:       Coach Kai - personal fitness coach
  workspace:         /workspace/fitness-coach
  model:             claude-sonnet-4-6          [change]
  allowed_models:    claude-sonnet-4-6
                     claude-haiku-4-5           [+ add]  [- remove]
  permission_mode:   approve-all                [change]
  system_prompt_files:
                     AGENTS.md
                     IDENTITY.md
                     SOUL.md
  discord channel:   9999
```

Selecting an agent opens its detail panel in a split view. All edits write directly
to `~/.arc/agents/<name>.yaml` on confirmation.

Keybindings:
- `arrow up/down` - navigate agent list
- `enter` - open detail panel
- `e` - open agent YAML in `$EDITOR` (escape hatch for complex edits)
- `n` - new agent (prompts for name, workspace, model -- creates YAML with defaults)
- `d` - delete selected agent (confirm prompt)
- `c` - change model (opens model picker from `allowed_models`)

**Cron screen**

```
arc  [Agents]  [Cron*]  [Config]  [Status]       q:quit  n:new  space:toggle

  NAME           SCHEDULE       AGENT    NEXT          STATUS
  weekly-plan    0 19 * * 0     coach    in 3h 14m     enabled
  heartbeat      */30 * * * *   coach    in 8 min      enabled
  daily-brief    0 7 * * *      coach    --            disabled

  ── weekly-plan ────────────────────────────────────────────────
  schedule:    0 19 * * 0  (Sundays at 7 PM)
  agent:       coach
  model:       (agent default)
  notify:      discord
  prompt:
    It's a new week. Pull my Strava data from the past week...
```

Keybindings:
- `space` - toggle enabled/disabled for selected job
- `r` - run selected job now (sends `{"op": "cron_run", "job": name}` IPC op)
- `e` - open job in `$EDITOR`
- `n` - new job (interactive form)
- `d` - delete job (confirm prompt)

**Config screen**

Editable view of `~/.arc/config.yaml`. Shows only the most commonly changed
settings inline; opens `$EDITOR` for full file editing.

```
arc  [Agents]  [Cron]  [Config*]  [Status]              q:quit  e:edit-file

  DAEMON
  auto_start:      true       [toggle]
  log_level:       info       [change: debug / info / warning / error]
  socket_path:     ~/.arc/arc.sock
  pid_file:        ~/.arc/daemon.pid

  TIMEOUTS
  acpx_request:    300s       [edit]
  ollama_request:  120s       [edit]

  OLLAMA ENDPOINTS
  local:           http://localhost:11434/v1    [edit]  [- remove]
  kyle:            http://kyle.local:11434/v1  [edit]  [- remove]
                                                        [+ add]

  DISCORD
  enabled:         false      [toggle]
  guild_id:        1234
```

Keybindings:
- `e` - open full `config.yaml` in `$EDITOR`
- `enter` on a field - inline edit (opens input widget)
- `space` on a boolean - toggle

#### Persistence

All writes go through the same YAML load/save functions used by the CLI:
- Agents: read/write `~/.arc/agents/<name>.yaml`
- Cron: read/write `~/.arc/cron/jobs.yaml`
- Config: read/write `~/.arc/config.yaml`

The TUI does not write through the daemon. It edits files directly and the daemon
picks up changes on the next relevant operation. Daemon restart is not required for
agent or cron changes (the daemon re-reads on each dispatch). Config changes that
affect the daemon process (log level, socket path) do require a restart; the Config
screen will show a warning when such a field is edited.

#### Graceful degradation

The TUI must work when the daemon is not running:
- Status screen shows "daemon not running" and reads config files for agent/cron data
- Agents and Config screens work fully (file-based reads/writes)
- Cron screen shows jobs but grays out "run now" (requires daemon)
- Start daemon button available on Status screen

#### Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
tui = ["textual>=0.80"]
```

Kept as an optional extra so the core arc install stays minimal. Install with:
`pip install -e ".[tui]"`. The `arc tui` command prints a helpful error if Textual
is not installed.

#### Testing

Textual has a testing framework (`textual.testing.AppTest`) that simulates key
presses and inspects rendered output. Tests go in `tests/test_tui/`.

Test coverage targets:
- Each screen renders without error (daemon running and not running)
- Agent model change writes correct YAML
- Cron enable/disable toggle writes correct YAML
- Config field edit writes correct value
- `arc tui` exits cleanly on `q`

Do not test visual layout or colors. Test state changes and file writes.

#### Definition of done

- [ ] `arc tui` launches and shows Status screen
- [ ] All four screens reachable via tab/click
- [ ] Status screen auto-refreshes every 5 seconds
- [ ] Agent model can be changed inline and persists to YAML
- [ ] Agent can be created with required fields via `n` shortcut
- [ ] Agent can be deleted with confirmation
- [ ] Cron job can be enabled/disabled via `space`
- [ ] Cron job can be triggered immediately via `r` (daemon must be running)
- [ ] Config boolean fields toggle correctly and persist
- [ ] Config numeric fields (timeouts) edit inline and persist
- [ ] All screens degrade gracefully when daemon is not running
- [ ] `$EDITOR` escape hatch works on Agents, Cron, and Config screens
- [ ] `arc tui` prints install hint if Textual not installed
- [ ] All tests pass (`pytest tests/test_tui/`)
- [ ] No regressions in existing CLI tests

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **acpx is alpha** | CLI interface may change, breaking arc's dispatcher | Pin acpx version in install.sh. Dispatcher is ~50 lines; easy to update if acpx changes. Monitor acpx releases. |
| **acpx requires Node.js >= 22.12.0** | Extra runtime dependency on the LXC | Install via nodesource. Node.js is lightweight. Only used for acpx, not for arc itself. |
| **Claude Code permission bugs in headless mode** | Some operations may still prompt despite bypassPermissions | Use auto mode as fallback. Container is the real sandbox. Monitor Claude Code issues for fixes. |
| **System prompt too large for shell args** | Concatenated identity files may exceed arg limits | Already mitigated: dispatcher writes to temp file and passes via --file. |
| **Subscription token exhaustion** | Heavy cron usage + Discord + personal use competes for 5-hour window | Use Haiku for heartbeat/simple tasks. Monitor with arc log. Upgrade to Max if needed. |
| **acpx session state corruption** | Named sessions may become stale or corrupted | acpx has crash reconnect. Sessions stored in ~/.acpx/sessions/. Can be manually cleared. |
| **Ollama endpoint down (Kyle's machine)** | Agents using remote models fail | Agent config allows fallback models in allowed_models. User can /model switch. |

---

## 12. Design Decisions Log

| Decision | Rationale |
|----------|-----------|
| acpx over raw `claude -p` | Persistent named sessions for Discord threads, one-shot mode for cron, prompt queueing, crash reconnect. Solves session management without custom code. |
| No LiteLLM | All non-Claude models use Ollama (same API). Nothing to normalize. |
| No classifier/router | Model is a property of the agent, not a per-request decision. Simpler, predictable, no wasted tokens on classification. |
| Agent-centric architecture | Mirrors OpenClaw's agent structure. Identity files carry over unchanged. |
| Stateless cron, stateful Discord | Agents are designed for stateless ("wake up fresh"). Files are the memory. Discord threads benefit from session continuity for multi-turn. |
| Python over Go | Faster iteration, discord.py is excellent, can rewrite later. |
| No OpenClaw | Security issues, resource consumption, token waste, complexity. arc does less but does it correctly. |
| Temp files for prompts | Avoids shell escaping issues and argument length limits. Cleaned up after each call. |
| bypassPermissions in LXC | Container IS the sandbox. Permission prompts can't be answered headlessly. |
| Per-agent allowed_models | Prevents accidentally routing Coach Kai to a 3B model that can't write files. |
| Cron per-job model override | Heartbeat every 30 min on Sonnet wastes tokens. Override to Haiku saves 80%+ on that job. |
| `--system-prompt` not `--append-system-prompt` | Append puts agent persona AFTER Claude Code's default identity, which wins for general questions. Replace (`--system-prompt`) overrides it fully. Verified live: Coach Kai now returns "Coach Kai. Eric's personal fitness coach." |
| `require_mention` defaults to false | OpenClaw's `requireMention: false` means agents respond to all messages in bound channels. Per-agent opt-in via `discord.require_mention: true` for channels where mention is needed. |
| thread_mode defaults to false | User preference: inline responses match OpenClaw behavior. Thread mode remains configurable via `discord.thread_mode: true` for future use. |
| Named sessions need `sessions ensure` | `acpx claude -s name` exits code 4 if session doesn't exist. Dispatcher calls `acpx claude sessions ensure --name` before prompting. System prompt passed to ensure so it's applied on session/new. |
| MCP/CLI tools handled at workspace level | Arc dispatches prompts only. Tool access (Strava, Garmin, Discord MCP) is configured in Claude Code's workspace settings, not in arc. No arc changes needed. |

---

## 13. Open Questions -- RESOLVED

All questions resolved via research against acpx v0.6.1 docs, source, and release notes.

1. **acpx `--system-prompt` support.**
   - **Resolved: Yes, supported.** Added in acpx v0.6.0. It is a global flag (placed
     before the agent name). It forwards via ACP `_meta.systemPrompt` on `session/new`.
   - The value is persisted in `session_options.system_prompt` on disk, so session
     restarts replay it automatically.
   - Passing it to an existing session has no effect (stored value is already in use).
   - No changes needed to dispatcher.py.

2. **acpx `--cwd` support.**
   - **Resolved: Yes, supported.** It is a global acpx flag placed before the agent name.
     Example: `acpx --cwd /workspace/fitness-coach claude exec "prompt"`.
   - **Known bug:** Claude Code's Bash tool subprocesses may still see `/` as cwd
     despite the flag (upstream issue #46985). Claude Code's file tools (Read, Write,
     Edit) are unaffected. Workaround: inject workspace path into system prompt if
     the agent uses Bash for path-sensitive operations.
   - Dispatcher updated: `--cwd` now placed before agent name.

3. **acpx `--permission-mode` support.**
   - **Resolved: Not supported.** acpx uses its own permission system:
     `--approve-all`, `--approve-reads`, `--deny-all`.
   - The `AgentConfig.permission_mode` field now maps to these acpx flags:
     - `approve-all` / `bypassPermissions` / `auto` -> `--approve-all`
     - `approve-reads` / `acceptEdits` / `default` -> `--approve-reads`
     - `deny-all` -> `--deny-all`
   - Default changed from `auto` to `approve-all` (headless agents need all tools
     approved). Dispatcher updated accordingly.

4. **acpx session naming with special characters.**
   - **Resolved: No issue.** Session names `coach-1484079455025627307` use
     alphanumeric + hyphens only. No length restriction found in docs or source.
     Safe to use.

5. **CLAUDE_CODE_MODEL environment variable.**
   - **Resolved: Wrong env var.** `CLAUDE_CODE_MODEL` does not exist. The correct
     variable is `ANTHROPIC_MODEL`. Claude Code also recognizes `ANTHROPIC_DEFAULT_SONNET_MODEL`
     and `ANTHROPIC_DEFAULT_HAIKU_MODEL` for pinning aliases.
   - Dispatcher updated: now sets `ANTHROPIC_MODEL` instead of `CLAUDE_CODE_MODEL`.

6. **acpx + system prompt interaction.**
   - **Resolved: Token-efficient.** System prompt is sent once on `session/new` only
     and persisted. Follow-up messages to the same named session do NOT resend it.
   - The daemon can safely pass `--system-prompt` on every call without wasting
     tokens on Discord follow-up messages.
   - No session tracking code needed in the daemon.

7. **Git SSH from systemd.**
   - **Resolved: Use per-repo deploy keys.** Generate a deploy key per workspace repo.
     Add to `~/.ssh/config`:

     ```
     Host github.com-fitness-coach
       HostName github.com
       User git
       IdentityFile ~/.ssh/fitness_coach_deploy_key
     ```

     Clone with: `git clone git@github.com-fitness-coach:eknorr/fitness-data.git`
     No passphrase on the key so systemd user service inherits without `SSH_AUTH_SOCK`.
     Document in `scripts/install.sh`.
