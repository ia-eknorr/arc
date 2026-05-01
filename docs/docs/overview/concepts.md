---
id: concepts
title: Core Concepts
sidebar_position: 3
---

# Core Concepts

## Agents

An agent is a named YAML file in `~/.arc/agents/`. Each agent defines a persona, a workspace directory, which model it uses by default, and optionally which Discord channel it listens to.

```yaml
name: coach
description: "Coach Kai - personal fitness coach"
workspace: /workspace/fitness-coach
system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
model: claude-sonnet-4-6
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5
discord:
  channel_id: "1234567890123456789"
```

The agent name is used in every `arc ask --agent <name>` call and in cron job definitions.

## System prompt construction

When a prompt is dispatched, arc reads each file listed in `system_prompt_files` from the agent's `workspace` directory and concatenates them with `---` separators:

```
# AGENTS.md

<contents of workspace/AGENTS.md>

---

# IDENTITY.md

<contents of workspace/IDENTITY.md>

---
...
```

The combined string is passed to `acpx` as `--system-prompt` or to Ollama as a system message. Files that do not exist are skipped with a warning.

The conventional filenames are:

| File | Purpose |
|---|---|
| `AGENTS.md` | Claude Code agent instructions (tool use, behavior) |
| `IDENTITY.md` | Agent persona and role definition |
| `SOUL.md` | Tone, values, and personality |
| `USER.md` | User profile and preferences the agent should know |
| `TOOLS.md` | Available tools and how to use them |

These are conventions, not requirements. You can use any filenames.

## Dispatch

Dispatch is the act of sending a prompt to a backend and returning the text response. arc has two dispatch paths, selected automatically by model prefix:

- `claude-*` models: dispatched via `acpx`, the Claude Code session manager
- `ollama/*` models: dispatched via `httpx` to an Ollama-compatible REST API

The dispatcher validates the requested model against `allowed_models` before calling the backend. If `allowed_models` is empty, any model with the correct prefix is accepted.

## Sessions

arc supports two session modes:

**One-shot (default):** Each request is independent. `acpx exec` is called with the prompt and returns the response. No session state is preserved between calls. Used for CLI and cron dispatch.

**Named sessions:** Discord threads use persistent `acpx` sessions. When a message arrives in a Discord thread, arc constructs a session name from the agent name and the thread ID (`coach-1234567890`). The session is created on the first message and reused for subsequent messages in the same thread, preserving conversation context.

Sessions are managed entirely by `acpx`. The `session_ttl` config value (default 300 seconds) controls how long `acpx` keeps idle sessions alive.

## Model routing

The model for a request is resolved in priority order:

1. `--model` flag on `arc ask` (or the `model` field in the IPC request)
2. `/model` Discord command (sticky per channel, stored in daemon memory)
3. Agent config `model` field (the default)

Model strings follow one of two patterns:

- `claude-<variant>`: routed to `acpx`. Examples: `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-opus-4-7`
- `ollama/<model>`: routed to the `local` Ollama endpoint. Example: `ollama/qwen3:8b`
- `ollama/<endpoint>/<model>`: routed to a named Ollama endpoint. Example: `ollama/remote/qwen3:32b`

Anything else raises a `DispatchError`.

## Cron jobs

Cron jobs live in `~/.arc/cron/jobs.yaml`. Each job has a name, a 5-field cron schedule, an agent name, and a prompt to send:

```yaml
jobs:
  weekly-plan:
    schedule: "0 19 * * 0"
    agent: coach
    prompt: "Write the weekly training plan."
    notify: discord
    enabled: true
```

The CronManager uses APScheduler's `CronTrigger.from_crontab()` to parse schedules, so any standard 5-field cron expression works. Jobs are loaded when the daemon starts; changes to `jobs.yaml` require a daemon restart.

The `notify` field controls Discord notifications:
- `discord`: always send the output to the agent's channel
- `discord_on_urgent`: send only if the output contains the word "urgent"
- omit: never notify

## IPC protocol

The CLI communicates with the daemon over a Unix domain socket at `~/.arc/arc.sock`. The protocol is minimal:

- Each message is a 4-byte big-endian unsigned integer (the payload length) followed by that many bytes of UTF-8-encoded JSON
- Requests are JSON objects with at least a `prompt` field and optionally `agent`, `model`, `source`, `thread_id`, `channel_id`, and `op`
- Responses are JSON objects with a `status` field (`"ok"` or `"error"`) and either `result` or `error`

The `op` field is used for non-dispatch operations: `op: "status"` returns daemon state, agents, and cron schedules; `op: "cron_run"` runs a named job immediately.

If the socket is not reachable, `ipc.request()` returns `None` and the CLI falls back to direct dispatch.
