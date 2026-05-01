---
id: architecture
title: Architecture
sidebar_position: 2
---

# Architecture

arc has six major components that work together to accept prompts from multiple sources and route them to the correct backend.

## Components

### arc CLI (`arc.cli`)

The `arc` command is a Typer application that exposes all user-facing subcommands. For most operations that involve dispatching a prompt, the CLI first attempts to contact the daemon via Unix socket IPC. If the daemon is not reachable and `daemon.auto_start` is true, the CLI spawns the daemon as a detached background process and retries. If still unreachable, it falls back to direct dispatch in the calling process.

This means `arc ask` works correctly regardless of whether the daemon is running.

### ArcDaemon (`arc.daemon`)

The daemon is an asyncio event loop that:

1. Binds a Unix domain socket at `~/.arc/arc.sock` (configurable)
2. Writes its PID to `~/.arc/daemon.pid`
3. Registers SIGTERM and SIGINT handlers for graceful shutdown
4. Starts the Discord bot as a background task if Discord is enabled
5. Starts the CronManager and registers all enabled jobs
6. Serves IPC connections indefinitely

The daemon holds two pieces of in-memory state: the Discord bot reference and a `model_overrides` dict mapping Discord channel IDs to user-selected models (set with the `/model` command).

All prompt handling flows through `ArcDaemon.handle_request`, which is called by IPC clients, the Discord bot, and the cron runner.

### Dispatcher (`arc.dispatcher`)

The dispatcher is the routing layer. Given a prompt, an agent config, and an optional model override, it:

1. Resolves the effective model (override or agent default)
2. Validates the model against `allowed_models` if the list is non-empty
3. Routes to `dispatch_acpx` for `claude-*` models or `dispatch_ollama` for `ollama/*` models
4. Returns a `DispatchResult` with the output text, the model that was used, and the dispatch type

**acpx path:** Builds a system prompt by reading and concatenating `system_prompt_files` from the agent workspace. Writes the prompt to a temporary file (to avoid shell escaping issues with multi-line prompts). Calls `acpx --format quiet --cwd <workspace> --model <model> <perm_flag> claude exec --file <tmpfile>` for one-shot dispatch, or manages a named session for Discord threads.

**Ollama path:** Builds the same system prompt and appends any `local_context_files` as an additional system message. Posts to the Ollama-compatible `/v1/chat/completions` endpoint via `httpx`.

### CronManager (`arc.cron`)

Wraps APScheduler's `AsyncIOScheduler`. On daemon start, it reads `~/.arc/cron/jobs.yaml`, adds each enabled job as a `CronTrigger.from_crontab(schedule)` job, and starts the scheduler. When a job fires, it calls `ArcDaemon.run_cron_job`, which routes the job prompt through the standard `handle_request` path (including Discord notification and log appending).

### Discord bot (`arc.discord_bridge`)

A `discord.py` Client subclass. On each message:

1. Ignores messages from itself and from guilds that do not match `guild_id`
2. Looks up which agent is bound to the channel (or the thread's parent channel)
3. Checks `require_mention` and the per-channel rate limiter
4. If `thread_mode` is enabled and the message is not already in a thread, creates a thread and uses it as the reply target
5. Calls `ArcDaemon.handle_request` with `source=discord` and the thread ID, which enables named `acpx` sessions for multi-turn conversation
6. Splits long responses into 2000-character chunks and sends them

The `/model` command is intercepted before dispatch: it reads or sets the daemon's in-memory `model_overrides` dict for the channel.

### IPC (`arc.ipc`)

A minimal framing protocol over Unix domain sockets. Every message is a 4-byte big-endian unsigned integer length prefix followed by a UTF-8 JSON payload. The `request` function handles the full connect-send-receive-close cycle and returns `None` if the daemon socket is not reachable.

## File layout

```
~/.arc/
  config.yaml          Main configuration
  .env                 Secrets (DISCORD_BOT_TOKEN, etc.) -- mode 600
  daemon.pid           PID file written by the daemon
  arc.sock             Unix domain socket (exists only while daemon runs)
  agents/
    <name>.yaml        One file per agent
  cron/
    jobs.yaml          All scheduled jobs
  logs/
    routing.jsonl      One JSON record per dispatched prompt
    cron.jsonl         One JSON record per cron job run
```

## Request lifecycle

1. User runs `arc ask --agent coach "What's my workout today?"`
2. CLI calls `ipc.request(cfg, {prompt, agent, model, source: "cli"})`
3. Daemon receives the request, loads the agent config, resolves model and session
4. If `git.auto_pull` is true, `git pull` runs in the agent workspace
5. Dispatcher builds the system prompt, calls `acpx` or Ollama, returns `DispatchResult`
6. Daemon logs the routing record to `routing.jsonl`
7. Daemon sends `{status: "ok", result: <output>}` back over the socket
8. CLI prints the output
