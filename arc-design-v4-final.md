# arc design v4 final

arc is a Python CLI and daemon for agent dispatch, cron scheduling, and Discord
integration. It replaces OpenClaw with roughly 800 lines of Python.

## Goals

- Single binary (`arc`) that works as both a one-shot CLI and a long-running daemon
- Route prompts from three sources (CLI, Discord, cron) to the right agent and model
- Manage named Claude Code sessions for persistent Discord threads
- No large framework dependencies; minimal surface area

## Tech stack

| Concern | Library |
|---|---|
| CLI | typer |
| Claude dispatch | acpx (external npm CLI) |
| Ollama dispatch | httpx |
| Scheduling | apscheduler |
| Discord | discord.py |
| Config | pyyaml |
| Build | hatchling, src layout |
| Tests | pytest, pytest-asyncio, pytest-httpx |
| Lint | ruff |

Python 3.11+ required. Node.js 22.12+ required for acpx.

## File structure

```
src/arc/
  __init__.py
  __main__.py         # entry point
  cli.py              # typer app; all user-facing commands
  daemon.py           # ArcDaemon class; asyncio event loop
  dispatcher.py       # acpx + Ollama dispatch logic
  agents.py           # agent YAML loading and system prompt assembly
  cron.py             # APScheduler wrapper
  discord_bridge.py   # discord.py bot
  ipc.py              # Unix socket protocol (daemon <-> CLI)
  config.py           # config loading and validation
  setup_wizard.py     # first-run setup
  import_openclaw.py  # OpenClaw migration
  types.py            # shared dataclasses
  utils.py            # shared helpers
```

## Config layout

```
~/.arc/
  config.yaml         # main config
  .env                # secrets (DISCORD_BOT_TOKEN); never in config.yaml
  agents/             # one .yaml file per agent
  cron/
    jobs.yaml
  logs/
  arc.sock            # Unix socket (daemon only)
  arc.pid
```

## Agent config schema

```yaml
name: coach
description: "Coach Kai - personal fitness coach"
workspace: /workspace/fitness-coach

system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md

model: claude-sonnet-4-6
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5

permission_mode: approve-all   # approve-all | approve-reads | deny-all

discord:
  channel_id: "1484079455025627307"

# Ollama agents only: inject file contents into the request body
local_context_files:
  - programs/current.md
```

`system_prompt_files` are loaded from `workspace/` and concatenated into a single
system prompt. `local_context_files` are injected as a second system message for
Ollama agents that cannot read the filesystem.

## Dispatch paths

**Claude (acpx):** any model beginning with `claude-`.

acpx wraps Claude Code sessions. Discord threads use persistent named sessions;
CLI and cron use one-shot exec mode. Command structure:

```
acpx --format quiet --cwd <workspace> --model <model> --approve-all \
     --system-prompt <prompt> claude exec --file <prompt_file>
```

For named sessions the system prompt is applied on `sessions ensure` (creation),
not on subsequent prompts.

**Ollama (httpx):** any model beginning with `ollama/`.

Calls the Ollama-compatible REST API. Model syntax:
- `ollama/qwen3:8b` - uses the `local` endpoint
- `ollama/kyle/qwen3:8b` - uses the `kyle` named endpoint

## Model resolution order

1. `--model` CLI flag or `/model` Discord slash command
2. Agent `model` field (default)

Models not in `allowed_models` are rejected with an error.

## IPC protocol

The CLI connects to the daemon over a Unix socket (`~/.arc/arc.sock`).
Messages are newline-delimited JSON.

Request:
```json
{"prompt": "...", "agent": "coach", "model": null, "source": "cli"}
```

Response:
```json
{"status": "ok", "result": "..."}
{"status": "error", "error": "..."}
```

If the socket is not reachable, the CLI falls back to direct dispatch (no daemon needed).

## Cron

Jobs are stored in `~/.arc/cron/jobs.yaml`. APScheduler runs inside the daemon
process. Each job dispatches a prompt to its configured agent.

```yaml
jobs:
  weekly-plan:
    schedule: "0 19 * * 0"
    agent: coach
    prompt: >
      It's a new week. Pull my Strava data and generate the weekly plan.
    notify: discord
    enabled: true
```

## Discord

The bot listens in channels bound to agents (via `discord.channel_id` in agent
config). Each new conversation spawns a thread; the session name is derived from
the thread ID. The session persists in acpx across messages so context is retained.

Slash commands:
- `/model <name>` - override model for the channel
- `/model reset` - revert to agent default

Bot token lives in `~/.arc/.env` (mode 600):
```
DISCORD_BOT_TOKEN=your-token-here
```

## Token observability (codeburn integration)

arc dispatches to Claude Code via acpx. Claude Code records every session's token
usage in `~/.claude/projects/<encoded-workspace-path>/`. codeburn reads this store
and provides usage reports.

`arc tokens` is a thin CLI wrapper around `codeburn` that adds agent-awareness:
it knows each agent's workspace and can pass `--project <name>` to scope the
report to a single agent.

```
arc tokens                    # all arc agents' workspaces; today
arc tokens --agent coach      # scoped to the coach agent's workspace only
arc tokens --period week      # week/month/all instead of today
arc tokens --cmd report       # full interactive codeburn TUI
arc tokens --cmd export       # CSV/JSON export via codeburn
```

Without `--agent`, arc passes `--project <basename>` for every configured agent,
so codeburn shows only arc-related spend. If no agents are configured it falls back
to showing all Claude Code projects.

The `--project` filter matches on workspace directory basename. If two agents share
a basename the filter includes both; rename workspaces to avoid this.

codeburn is invoked as a subprocess. arc prefers a global `codeburn` install; if
not found it falls back to `npx --yes codeburn`. If neither is available `arc tokens`
prints an install hint and exits 1.

Install codeburn globally:
```bash
npm install -g codeburn
```

## Shell completions

Typer generates completion scripts for bash, zsh, fish, and PowerShell.

Install for your current shell (one-time):
```bash
arc --install-completion
```

Print the script without installing:
```bash
arc --show-completion
```

## Security

- Run the daemon as a non-root `arc` user
- `permission_mode: approve-all` is the safe default; avoid `bypassPermissions`
  unless the agent specifically requires headless operation
- Store the Discord token in `~/.arc/.env` (mode 600), never in `config.yaml`
- Workspaces should contain only agent files, never SSH keys or credentials
- The LXC container provides the outer security boundary

## Implementation phases

- [x] Phase 1: types, config, agents, dispatcher, `arc ask`, tests
- [ ] Phase 2: daemon + IPC
- [ ] Phase 3: Discord
- [ ] Phase 4: cron
- [ ] Phase 5: setup wizard + OpenClaw migration
- [ ] Phase 6: polish (logging, `arc log`, `arc config`, completions docs)
