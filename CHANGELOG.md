# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [v0.1.0] - 2026-05-01

### Added

- **Agent dispatch via acpx** — Claude Code agents are dispatched through `acpx`, which manages named sessions, system prompt loading from workspace files, and permission modes. One-shot mode is used for CLI and cron; persistent named sessions are used for Discord threads.

- **Ollama dispatch via httpx** — Local and remote Ollama-compatible endpoints are called directly over HTTP. Model names prefixed with `ollama/` are routed to the configured endpoint. Named endpoints (`ollama/kyle/qwen3:8b`) allow multi-host setups.

- **Unix socket IPC daemon** — `ArcDaemon` binds a Unix socket at `~/.arc/arc.sock` and accepts JSON requests from the CLI, Discord bot, and cron manager. The 4-byte length-prefixed protocol allows concurrent clients without spawning subprocesses.

- **APScheduler cron** — Jobs defined in `~/.arc/cron/jobs.yaml` are scheduled using `AsyncIOScheduler` with `CronTrigger.from_crontab()`. Each job carries an agent, prompt, optional model override, and a notify mode (`discord`, `discord_on_urgent`, or none).

- **Discord bot** — `ArcDiscordBot` routes messages to agents by channel ID. By default (`require_mention: false`) it responds to all messages in a configured channel. The `/model` in-channel command sets a sticky model override per channel; `/model reset` clears it. Rate limiting uses a sliding window per channel.

- **`arc ask`** — Send a prompt to an agent from the CLI. Tries the daemon first via IPC; falls back to direct dispatch if the daemon is not running. Supports `--agent`, `--model`, `--pretty`, and stdin piping.

- **`arc status`** — Shows daemon state, configured agents with model and Discord channel, and scheduled cron jobs with next-run times. Works offline by reading config from disk when the daemon is not running.

- **`arc daemon`** — Subcommands: `start`, `stop`, `status`, `restart`, `install` (generates a systemd user service unit file).

- **`arc agent`** — Full CRUD for agent YAML files: `list`, `show`, `create`, `edit`, `delete`, `clone`. Clone clears `discord.channel_id` on the copy.

- **`arc cron`** — Job management: `list`, `add`, `remove`, `edit`, `enable`, `disable`, `run`, `next`, `history`. `arc cron run` routes through the daemon so Discord notifications and cron log entries are produced identically to a scheduled run.

- **`arc log`** — `routing` and `cron` subcommands tail the JSONL log files in `~/.arc/logs/`. `arc log tail` follows both files with `tail -f`.

- **`arc config`** — `show`, `edit`, and `set` (dot-notation key, auto-coerces booleans and integers).

- **`arc tokens`** — Wraps the `codeburn` CLI to report Claude Code token usage, scoped to all agent workspaces or a single agent.

- **`arc setup`** — Interactive first-run wizard. Creates `~/.arc/` directory structure, writes default `config.yaml`, creates `.env` with secure permissions, and optionally configures Discord.

- **`arc import-openclaw`** — Migrates agents and cron jobs from an OpenClaw installation. Reads `openclaw.json` and `cron/jobs.json`, converts model names, maps Discord channel bindings, and writes arc-compatible YAML files. Supports `--dry-run`.

- **Shell completions** — Typer generates dynamic completions for zsh, bash, fish, and PowerShell via `arc --install-completion`.

- **Docusaurus documentation site** — Full docs at `https://ia-eknorr.github.io/arc/` covering architecture, all CLI commands, agent/config/cron schema references, guides, and troubleshooting.

[v0.1.0]: https://github.com/ia-eknorr/arc/releases/tag/v0.1.0
