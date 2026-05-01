# arc

[![Lint](https://github.com/ia-eknorr/arc/actions/workflows/lint.yml/badge.svg)](https://github.com/ia-eknorr/arc/actions/workflows/lint.yml)
[![Unit Tests](https://github.com/ia-eknorr/arc/actions/workflows/test.yml/badge.svg)](https://github.com/ia-eknorr/arc/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/ia-eknorr/arc?color=orange)](https://github.com/ia-eknorr/arc/releases)
[![license](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
[![docs](https://img.shields.io/badge/docs-ia--eknorr.github.io-blue)](https://ia-eknorr.github.io/arc/)

A lightweight Python CLI and daemon for agent dispatch, scheduled tasks, and Discord integration. Replaces OpenClaw with minimal code, using `acpx` for Claude Code session management and `httpx` for Ollama.

## What it does

- Receives prompts from the CLI, Discord, or cron
- Routes each prompt to the right agent (coach, trainer, main, etc.)
- Dispatches to Claude (via `acpx`) or a local/remote Ollama model (via `httpx`)
- Logs routing decisions for debugging and token usage tracking

## Requirements

- Python 3.11+
- Node.js 22.12.0+ (for `acpx`)
- `acpx` CLI: `npm install -g acpx@latest`
- Claude Code CLI: `curl -fsSL https://claude.ai/install.sh | bash`
- Ollama (optional, for local models)

## Install

```bash
git clone git@github.com:ia-eknorr/arc.git
cd arc
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

First run:

```bash
arc setup
```

This creates `~/.arc/` with default config, agent directories, and log directories.

## Usage

### Ask an agent

```bash
# Use agent's default model
arc ask --agent coach "What's my workout today?"

# Override model
arc ask --agent coach --model haiku "Quick question"

# Use a local Ollama model
arc ask --agent trainer --model ollama/qwen3:8b "Summarize my week"

# Pipe stdin
cat report.md | arc ask --agent main

# Show dispatch info (model used, type)
arc ask --pretty --agent coach "Explain periodization"
```

### Agents

```bash
arc agent list
arc agent show coach
arc agent create --name coach --model sonnet --workspace /workspace/fitness-coach
arc agent create --from ./coach.yaml   # from existing YAML file
arc agent edit coach
arc agent clone coach coach-dev        # clone (clears discord channel_id)
arc agent delete old-agent
```

### Cron jobs

```bash
arc cron list
arc cron add --name weekly-plan --schedule "0 19 * * 0" \
  --agent coach --prompt "Write the weekly training plan."
arc cron enable weekly-plan
arc cron disable heartbeat
arc cron run daily-workout        # run immediately
arc cron next                     # show next scheduled times
arc cron history daily-workout --last 5
```

### Daemon

```bash
arc daemon start
arc daemon start --foreground     # for systemd
arc daemon stop
arc daemon status
arc daemon restart
arc daemon install                # generate systemd unit file
```

### Logs

```bash
arc log routing --last 20
arc log cron --last 10
arc log tail
```

### Config

```bash
arc config show
arc config edit
arc config set daemon.auto_start false
```

### Token usage

```bash
# All Claude Code projects - today's totals
arc tokens

# Scoped to one agent's workspace
arc tokens --agent coach

# Change the period
arc tokens --period week
arc tokens --period month
arc tokens --period all

# Full interactive codeburn dashboard (charts, breakdowns)
arc tokens --cmd report

# Today's or this month's dashboard
arc tokens --cmd today
arc tokens --cmd month

# Export to CSV or JSON (piped through codeburn)
arc tokens --cmd export
```

`arc tokens` is a wrapper around [codeburn](https://github.com/getagentseal/codeburn).
Install it globally to avoid npx cold-start overhead:

```bash
npm install -g codeburn
```

By default, the report is scoped to all arc-configured agents. Pass `--agent` to
narrow to one. If no agents are configured, codeburn shows all Claude Code projects.

### Import from OpenClaw

```bash
arc import-openclaw                  # from ~/.openclaw/
arc import-openclaw --from /path/
arc import-openclaw --dry-run
```

## Config

Main config lives at `~/.arc/config.yaml`. Created with defaults on first run.

```yaml
daemon:
  auto_start: true
  socket_path: ~/.arc/arc.sock
  log_level: info

acpx:
  command: acpx
  default_agent: claude
  session_ttl: 300        # seconds to keep session warm

ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1
    kyle:
      url: http://kyle-nuc.tailnet:11434/v1

discord:
  enabled: false
  token_env: DISCORD_BOT_TOKEN
  guild_id: ""

timeouts:
  acpx_request: 300
  ollama_request: 120
```

## Agent config

Each agent has a YAML file in `~/.arc/agents/`. Example for the fitness coach:

```yaml
# ~/.arc/agents/coach.yaml
name: coach
description: "Coach Kai - personal fitness coach"
workspace: /workspace/fitness-coach

system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md

model: sonnet
allowed_models:
  - sonnet
  - haiku

permission_mode: auto         # auto preferred; bypassPermissions if headless issues

discord:
  channel_id: "1484079455025627307"
```

The `system_prompt_files` are loaded from `workspace/` and concatenated into a single system prompt passed to Claude or Ollama on each request.

For Ollama agents that can't read the filesystem, add `local_context_files` to inject file contents directly into the request:

```yaml
model: ollama/qwen3:8b
local_context_files:
  - programs/current.md
  - weeks/current.md
```

## Cron jobs

```yaml
# ~/.arc/cron/jobs.yaml
jobs:
  weekly-plan:
    description: "Generate weekly training plan every Sunday at 7 PM"
    schedule: "0 19 * * 0"
    agent: coach
    prompt: >
      It's a new week. Pull my Strava data, review what I completed vs planned,
      and generate the new weekly plan file.
    notify: discord
    enabled: true

  heartbeat:
    description: "Background log scanner"
    schedule: "*/30 * * * *"
    agent: coach
    model: haiku              # cheaper model for frequent runs
    prompt: >
      Read HEARTBEAT.md and follow it strictly.
    notify: discord_on_urgent
    enabled: true
```

## Discord

The bot responds to messages in channels bound to agents. By default (`require_mention: false`) it replies to every message in the channel. Set `require_mention: true` on an agent to only respond when @mentioned.

Responses are inline by default. Set `thread_mode: true` in config to have the bot create a thread for each new conversation. Discord threads use persistent named `acpx` sessions so context is preserved across messages.

Commands in Discord:
- `/model haiku` - switch model for this channel (use acpx alias, not full model ID)
- `/model reset` - revert to agent default

Store the bot token in `~/.arc/.env` (not in config.yaml):

```bash
echo "DISCORD_BOT_TOKEN=your-token-here" > ~/.arc/.env
chmod 600 ~/.arc/.env
```

## Dispatch paths

**Claude (via acpx):** For any model that does not start with `ollama/`. Uses acpx aliases (`sonnet`, `haiku`, `default`). Discord threads use persistent named sessions; CLI and cron use one-shot exec mode.

**Ollama (via httpx):** For any model starting with `ollama/`. Calls the Ollama-compatible REST API at the configured endpoint. The model name after `ollama/` is passed to the API. To use a named endpoint: `ollama/kyle/qwen3:8b`.

## Model resolution priority

1. `--model` CLI flag
2. `/model` Discord command (sticky per channel)
3. Agent config `model` field (default)

Requests for models not in `allowed_models` are rejected with an error message.

## Security

- Run the daemon as a dedicated non-root `arc` user
- Default `permission_mode: approve-all` is the safe default; avoid `bypassPermissions` unless the agent requires headless operation
- Store the Discord bot token in `~/.arc/.env` (mode 600), not in config
- Use repo-scoped deploy keys for git, not personal SSH keys
- The LXC container provides the outer security boundary; restrict outbound network with iptables (see `scripts/install.sh`)
- Workspaces should contain only agent files, never SSH keys or credentials

## Shell completions

Typer generates completion scripts for bash, zsh, fish, and PowerShell.

Install for your current shell (one-time setup):

```bash
arc --install-completion
```

Print the script without installing (useful for system-wide or manual setup):

```bash
arc --show-completion
```

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=arc --cov-report=term-missing

# Lint
ruff check src/ tests/
```

## TUI

`arc tui` opens a k9s-style terminal management interface for common operational tasks.

```bash
arc tui
```

Four panes, navigated with `h`/`l` (or click the tab headers):

| Pane | What you can do |
|------|-----------------|
| **Status** | See daemon state, agents, and upcoming cron jobs |
| **Agents** | Browse agents, change model, create/delete, open in `$EDITOR` |
| **Cron** | Toggle jobs on/off, run now, create/delete |
| **Config** | Edit common config fields inline, open full file in `$EDITOR` |

Keybindings:

| Key | Action |
|-----|--------|
| `h` / `l` | Previous / next tab |
| `j` / `k` | Move cursor up/down in list |
| `g` / `G` | Jump to top / bottom of list |
| `q` | Quit |
| `r` | Run selected cron job now |
| `s` | Start / stop daemon (Status pane) |
| `space` | Toggle cron job enabled/disabled, or toggle boolean config |
| `n` | New agent or cron job |
| `d` | Delete selected item (with confirmation) |
| `e` | Open selected file in `$EDITOR` |
| `c` | Change model for selected agent |
| `enter` | Edit selected config field |

## Implementation status

- [x] Phase 1: Foundation (types, config, agents, dispatcher, `arc ask`, `arc status`, `arc tokens`)
- [x] Phase 2: Daemon + IPC (Unix socket, `arc daemon` commands)
- [x] Phase 3: Discord (bot, channel routing, rate limiting, `/model` command)
- [x] Phase 4: Cron (APScheduler, `arc cron` commands, Discord notifications)
- [x] Phase 5: Setup wizard, OpenClaw migration (`arc setup`, `arc import-openclaw`)
- [x] Phase 6: Polish (`arc agent`, `arc log`, `arc config`, `arc cron` add/remove/edit/history, shell completions)
- [x] Phase 7: TUI (`arc tui` -- k9s-style interface, all four panes, h/j/k/l navigation)
