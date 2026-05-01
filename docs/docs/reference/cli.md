---
id: cli
title: CLI Reference
sidebar_position: 1
---

# CLI Reference

All commands are accessed via the `arc` binary. Use `arc --help` or `arc <command> --help` for inline help.

## arc ask

Send a prompt to an agent and print the response.

```
arc ask [OPTIONS] [PROMPT]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `PROMPT` | | string | | Prompt text. If omitted, stdin is required. |
| `--agent` | `-a` | string | | Agent name from `~/.arc/agents/` |
| `--model` | `-m` | string | | Override model (e.g. `haiku`, `sonnet`, `ollama/qwen3:8b`) |
| `--pretty` | | flag | false | Print dispatch info header before the response |

**Behavior:** The CLI first tries the daemon via IPC. If the daemon is not running and `daemon.auto_start` is true, it spawns the daemon and retries. If still unreachable, it dispatches directly.

You must provide `--agent` or `--model` (or both). Without either, the command exits with an error.

**Examples:**

```bash
# Basic
arc ask --agent coach "What's my workout today?"

# Override model (use acpx alias for Claude, ollama/ prefix for Ollama)
arc ask --agent coach --model haiku "Quick question"

# Local Ollama model
arc ask --agent coach --model ollama/qwen3:8b "Summarize my week"

# Pipe stdin
cat report.md | arc ask --agent main

# Stdin and argument combined (concatenated with blank line)
cat context.md | arc ask --agent main "Given the above, what should I do next?"

# Show dispatch metadata
arc ask --agent coach --pretty "Hello"
# [acpx / sonnet]
#
# Hello! How can I help?
```

---

## arc status

Show daemon state, configured agents, and scheduled cron jobs.

```
arc status [OPTIONS]
```

No options. Queries the daemon via IPC if running; otherwise reads config files directly.

**Example output:**

```
daemon    running (pid=12345, socket=/Users/you/.arc/arc.sock)

agents
  coach            sonnet            /workspace/fitness-coach  discord 1234567890123456789
  trainer          ollama/qwen3:8b              /workspace/fitness-coach

cron
  weekly-plan      next: in 3h 14m
  heartbeat        next: in 12 min
  daily-summary    disabled
```

---

## arc version

Print the installed arc version.

```
arc version
```

**Example:**

```bash
arc version
# arc 0.1.0
```

---

## arc setup

Interactive first-run setup wizard.

```
arc setup [OPTIONS]
```

Checks for `acpx` and `claude` in PATH, creates `~/.arc/` with subdirectories, writes a default `config.yaml`, and optionally configures Discord.

**Example:**

```bash
arc setup
# arc setup -- configuring /Users/you/.arc
#
#   [ok] acpx: /usr/local/bin/acpx
#   [ok] claude: /usr/local/bin/claude
#
# Created /Users/you/.arc/config.yaml
# Created /Users/you/.arc/.env (chmod 600)
#
# Set up Discord bot? [y/N]: y
# Discord bot token: ...
# Discord guild ID: ...
# Discord configured. Restart daemon to apply.
#
# Setup complete. Run: arc daemon start
```

---

## arc tokens

Show Claude Code token usage via `codeburn`.

```
arc tokens [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--agent` | `-a` | string | | Scope to a single agent's workspace |
| `--period` | `-p` | string | `today` | Period: `today`, `week`, `month`, `all` |
| `--cmd` | | string | `status` | codeburn subcommand: `status`, `report`, `today`, `month`, `export` |

Requires `codeburn` to be installed: `npm install -g codeburn`

**Examples:**

```bash
# Today's token usage across all configured agents
arc tokens

# Scoped to one agent
arc tokens --agent coach

# Weekly usage
arc tokens --period week

# Full interactive report
arc tokens --cmd report

# This month's dashboard
arc tokens --cmd month

# Export to CSV
arc tokens --cmd export
```

---

## arc import-openclaw

Import agents and cron jobs from an OpenClaw installation.

```
arc import-openclaw [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--from` | path | `~/.openclaw` | OpenClaw config directory |
| `--dry-run` | flag | false | Preview without writing files |

**Examples:**

```bash
# Dry run (preview only)
arc import-openclaw --dry-run

# Import from default location
arc import-openclaw

# Import from a custom path
arc import-openclaw --from /opt/openclaw
```

---

## arc daemon

Manage the arc background daemon.

### arc daemon start

```
arc daemon start [OPTIONS]
```

| Option | Type | Default | Description |
|---|---|---|---|
| `--foreground` | flag | false | Run in the foreground (for systemd, do not background) |

If the daemon is already running, exits with a message. Otherwise spawns the daemon as a detached background process.

```bash
arc daemon start
# Daemon started.

arc daemon start --foreground
# (runs until SIGTERM)
```

### arc daemon stop

```
arc daemon stop
```

Sends SIGTERM to the daemon process. Reads the PID from `~/.arc/daemon.pid`.

```bash
arc daemon stop
# Daemon stopped (pid=12345).
```

### arc daemon status

```
arc daemon status
```

Prints running status, PID, and socket path. Exits with code 1 if not running.

```bash
arc daemon status
# Daemon running (pid=12345, socket=/Users/you/.arc/arc.sock)
```

### arc daemon restart

```
arc daemon restart
```

Sends SIGTERM to the existing process (if any), waits briefly, then spawns a new daemon.

```bash
arc daemon restart
# Daemon restarted.
```

### arc daemon install

```
arc daemon install
```

Generates a systemd user service unit file at `~/.config/systemd/user/arc-daemon.service`.

```bash
arc daemon install
# Wrote /home/user/.config/systemd/user/arc-daemon.service
# To enable: systemctl --user enable --now arc-daemon
```

---

## arc agent

Manage arc agent configurations.

### arc agent list

```
arc agent list
```

Lists all YAML files in `~/.arc/agents/` with name, model, workspace, and Discord channel.

```bash
arc agent list
# coach            sonnet            /workspace/fitness-coach  channel=1234567890123456789
# trainer          ollama/qwen3:8b              /workspace/fitness-coach
```

### arc agent show

```
arc agent show NAME
```

Prints the raw YAML for the named agent.

```bash
arc agent show coach
```

### arc agent create

```
arc agent create [OPTIONS]
```

| Option | Short | Type | Description |
|---|---|---|---|
| `--from` | | path | Copy from an existing YAML file |
| `--name` | `-n` | string | Agent name |
| `--workspace` | `-w` | string | Workspace directory path |
| `--model` | `-m` | string | Default model |

Without `--from`, prompts for missing values interactively.

```bash
# Interactive
arc agent create

# With flags
arc agent create --name coach --workspace /workspace/fitness-coach --model sonnet

# From a YAML file
arc agent create --from ./my-agent.yaml --name my-renamed-agent
```

### arc agent edit

```
arc agent edit NAME
```

Opens the agent YAML in `$EDITOR`.

```bash
arc agent edit coach
```

### arc agent delete

```
arc agent delete NAME [OPTIONS]
```

| Option | Short | Description |
|---|---|---|
| `--yes` | `-y` | Skip confirmation prompt |

```bash
arc agent delete old-agent
# Delete agent 'old-agent'? [y/N]: y
# Deleted agent 'old-agent'.

arc agent delete old-agent --yes
# Deleted agent 'old-agent'.
```

### arc agent clone

```
arc agent clone SOURCE_NAME NEW_NAME
```

Copies an agent YAML under a new name. Clears `discord.channel_id` to avoid conflicts.

```bash
arc agent clone coach coach-dev
# Cloned 'coach' -> 'coach-dev'. Edit /Users/you/.arc/agents/coach-dev.yaml to configure.
```

---

## arc cron

Manage scheduled cron jobs.

### arc cron list

```
arc cron list
```

Lists all jobs in `~/.arc/cron/jobs.yaml` with status, schedule, and options.

```bash
arc cron list
# weekly-plan          [enabled]   0 19 * * 0
#   Generate weekly training plan every Sunday at 7 PM
# heartbeat            [enabled]   */30 * * * *  model=haiku  notify=discord_on_urgent
# daily-summary        [disabled]  0 20 * * *
```

### arc cron add

```
arc cron add [OPTIONS]
```

| Option | Short | Type | Description |
|---|---|---|---|
| `--name` | `-n` | string | Job name |
| `--schedule` | `-s` | string | Cron expression |
| `--agent` | `-a` | string | Agent name |
| `--prompt` | `-p` | string | Prompt text |
| `--notify` | | string | `discord` or `discord_on_urgent` |
| `--model` | `-m` | string | Model override |

Prompts for missing required values. Writes to `jobs.yaml` and reminds you to restart the daemon.

```bash
arc cron add \
  --name weekly-plan \
  --schedule "0 19 * * 0" \
  --agent coach \
  --prompt "Write the weekly training plan." \
  --notify discord
# Added job 'weekly-plan'. Restart daemon to schedule it.
```

### arc cron remove

```
arc cron remove NAME
```

Removes a job from `jobs.yaml`.

```bash
arc cron remove old-job
# Removed job 'old-job'. Restart daemon to apply.
```

### arc cron edit

```
arc cron edit NAME
```

Opens `~/.arc/cron/jobs.yaml` in `$EDITOR`.

```bash
arc cron edit heartbeat
```

### arc cron enable

```
arc cron enable NAME
```

Sets `enabled: true` for the named job. Requires daemon restart.

```bash
arc cron enable daily-summary
# Enabled daily-summary. Restart the daemon to apply.
```

### arc cron disable

```
arc cron disable NAME
```

Sets `enabled: false` for the named job. Requires daemon restart.

```bash
arc cron disable heartbeat
# Disabled heartbeat. Restart the daemon to apply.
```

### arc cron run

```
arc cron run NAME
```

Runs a job immediately. Routes through daemon IPC if running (enables Discord notifications and logging); falls back to direct dispatch if the daemon is not running.

```bash
arc cron run weekly-plan
```

### arc cron next

```
arc cron next
```

Shows the next scheduled run time for each enabled job. Computes times directly from the cron expression without requiring the daemon.

```bash
arc cron next
# weekly-plan          2026-05-03 19:00 MDT
# heartbeat            2026-04-30 22:30 MDT
# daily-summary        [disabled]
```

### arc cron history

```
arc cron history [NAME] [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `NAME` | | string | | Filter to a specific job (optional) |
| `--last` | `-n` | int | 10 | Number of entries to show |

Reads from `~/.arc/logs/cron.jsonl`.

```bash
arc cron history
arc cron history heartbeat --last 5
# 2026-04-30 21:30  heartbeat            [ok]   No urgent items found.
# 2026-04-30 21:00  heartbeat            [ok]   No urgent items found.
```

---

## arc log

View arc log files.

### arc log routing

```
arc log routing [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--last` | `-n` | int | 20 | Number of entries to show |
| `--agent` | `-a` | string | | Filter to a specific agent |

Reads from `~/.arc/logs/routing.jsonl`.

```bash
arc log routing
arc log routing --agent coach --last 5
# 2026-04-30 21:00  coach        sonnet            discord  What's my workout today?
```

### arc log cron

```
arc log cron [OPTIONS]
```

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--last` | `-n` | int | 10 | Number of entries to show |
| `--job` | `-j` | string | | Filter to a specific job |

Reads from `~/.arc/logs/cron.jsonl`.

```bash
arc log cron
arc log cron --job weekly-plan --last 3
```

### arc log tail

```
arc log tail
```

Runs `tail -f` on both `routing.jsonl` and `cron.jsonl`. Press Ctrl+C to stop.

```bash
arc log tail
```

---

## arc config

Manage arc configuration.

### arc config show

```
arc config show
```

Prints the current `~/.arc/config.yaml`.

```bash
arc config show
```

### arc config edit

```
arc config edit
```

Opens `~/.arc/config.yaml` in `$EDITOR`.

```bash
arc config edit
```

### arc config set

```
arc config set KEY VALUE
```

Sets a single config value using dot-notation. Type coercion: `true`/`false` become booleans, numeric strings become integers, everything else stays a string.

```bash
arc config set daemon.auto_start false
arc config set daemon.log_level debug
arc config set discord.enabled true
arc config set discord.rate_limit.messages_per_minute 10
arc config set timeouts.acpx_request 600
```

---

## Global options

The `--config-dir` option is available on all commands (hidden from help by default). It overrides the `~/.arc` directory for testing or running multiple isolated arc instances:

```bash
arc --config-dir /tmp/arc-test ask --agent main "Hello"
arc --config-dir /tmp/arc-test daemon start
```

Shell completions are installed with `arc --install-completion` and shown (without installing) with `arc --show-completion`.
