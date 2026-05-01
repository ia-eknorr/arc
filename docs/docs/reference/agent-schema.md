---
id: agent-schema
title: Agent YAML Schema
sidebar_position: 2
---

# Agent YAML Schema

Each agent is a YAML file in `~/.arc/agents/<name>.yaml`. The filename (without `.yaml`) is the agent name used in all `arc` commands.

## Full example

```yaml
name: coach
description: "Coach Kai - AI-powered personal fitness coach"
workspace: /workspace/fitness-coach

system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md

local_context_files: []

model: sonnet
allowed_models:
  - sonnet
  - haiku

permission_mode: approve-all

discord:
  channel_id: "1234567890123456789"
  require_mention: false
```

## Field reference

### name

| Attribute | Value |
|---|---|
| Type | string |
| Required | yes |

The agent's identifier. Must match the filename (e.g., `name: coach` in `coach.yaml`). Used in `arc ask --agent <name>`, cron job `agent` fields, and log entries.

```yaml
name: coach
```

---

### description

| Attribute | Value |
|---|---|
| Type | string |
| Required | no |
| Default | `""` |

A human-readable description of the agent. Shown in `arc agent list` (in future versions). Has no functional effect.

```yaml
description: "Coach Kai - personal fitness coach with Strava integration"
```

---

### workspace

| Attribute | Value |
|---|---|
| Type | string (path) |
| Required | yes |

Absolute path to the agent's working directory. The dispatcher sets `--cwd <workspace>` when calling `acpx`, so Claude Code's file operations are relative to this directory. `system_prompt_files` and `local_context_files` are also resolved relative to this path.

```yaml
workspace: /workspace/fitness-coach
```

---

### system_prompt_files

| Attribute | Value |
|---|---|
| Type | list[string] |
| Required | no |
| Default | `[]` |

List of filenames (relative to `workspace`) to read and concatenate as the system prompt. Each file is prefixed with `# <filename>` and separated by `---`.

Files that do not exist are silently skipped with a warning in the daemon log. If the list is empty or no files exist, no system prompt is sent (the backend's default applies).

```yaml
system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md
```

The conventional filenames and their purposes:

| File | Purpose |
|---|---|
| `AGENTS.md` | Claude Code tool use and behavior instructions |
| `IDENTITY.md` | Agent persona and role |
| `SOUL.md` | Tone, values, personality |
| `USER.md` | User profile and preferences |
| `TOOLS.md` | Available tools and usage instructions |

---

### local_context_files

| Attribute | Value |
|---|---|
| Type | list[string] |
| Required | no |
| Default | `[]` |

List of filenames (relative to `workspace`) whose contents are injected into the Ollama request as a system message. Useful for giving Ollama agents access to workspace data without filesystem tool access.

Ignored for Claude (acpx) agents, which can read the filesystem directly.

```yaml
local_context_files:
  - programs/current.md
  - weeks/current.md
  - athlete-profile.md
```

---

### model

| Attribute | Value |
|---|---|
| Type | string |
| Required | yes |

The default model for this agent. The value determines which backend is used:

- **acpx alias** (`sonnet`, `haiku`, `default`, `sonnet[1m]`): dispatched via `acpx` to Claude Code
- **`ollama/<model>`** or **`ollama/<endpoint>/<model>`**: dispatched via `httpx` to Ollama

For Claude models, use the short alias that `acpx` advertises — not the full Anthropic model ID. Using `claude-sonnet-4-6` instead of `sonnet` will cause acpx to reject the request with `Cannot apply --model "claude-sonnet-4-6": the ACP agent did not advertise that model`.

To see which aliases your acpx version supports: `acpx --help | grep -A5 model`

```yaml
model: sonnet
```

```yaml
model: haiku
```

```yaml
model: ollama/qwen3:8b
```

```yaml
model: ollama/remote/llama3.2:latest
```

---

### allowed_models

| Attribute | Value |
|---|---|
| Type | list[string] |
| Required | no |
| Default | `[]` (any model allowed) |

A list of models that callers may request via `--model`, `/model` Discord command, or cron job `model` field. If empty, any model is accepted. Use the same format as the `model` field: acpx aliases for Claude, `ollama/...` for Ollama.

```yaml
allowed_models:
  - sonnet
  - haiku
  - ollama/qwen3:8b
```

Requests for models not in this list are rejected with: `Model 'X' is not allowed for agent 'Y'. Allowed: ...`

---

### permission_mode

| Attribute | Value |
|---|---|
| Type | string |
| Required | no |
| Default | `approve-all` |

Controls how `acpx` handles tool use permissions. Only applies to Claude (acpx) dispatch; ignored for Ollama.

| Value | acpx flag | Behavior |
|---|---|---|
| `approve-all` | `--approve-all` | Auto-approve all tool use |
| `approve-reads` | `--approve-reads` | Auto-approve reads; prompt for writes |
| `deny-all` | `--deny-all` | Deny all tool use |
| `bypassPermissions` | `--approve-all` | Legacy alias for approve-all |
| `auto` | `--approve-all` | Legacy alias for approve-all |
| `acceptEdits` | `--approve-reads` | Legacy alias for approve-reads |
| `default` | `--approve-reads` | Legacy alias for approve-reads |

For headless daemon operation, use `approve-all`. For read-only agents, use `approve-reads` or `deny-all`.

```yaml
permission_mode: approve-all
```

---

### discord

| Attribute | Value |
|---|---|
| Type | object |
| Required | no |
| Default | `{}` |

Discord integration settings for this agent.

```yaml
discord:
  channel_id: "1234567890123456789"
  require_mention: false
```

#### discord.channel_id

| Attribute | Value |
|---|---|
| Type | string |
| Required | no |
| Default | `""` |

The Discord channel ID that this agent listens to. When a message arrives in this channel, it is routed to this agent. Must be a string (quote numeric IDs in YAML).

Only one agent can be bound to a given channel. If multiple agents have the same `channel_id`, the first one found wins (alphabetical by filename).

```yaml
discord:
  channel_id: "1234567890123456789"
```

#### discord.require_mention

| Attribute | Value |
|---|---|
| Type | bool |
| Required | no |
| Default | `false` |

When `true`, the bot only responds in this channel if the bot is @mentioned in the message. When `false` (default), every message in the channel triggers a response.

```yaml
discord:
  channel_id: "1234567890123456789"
  require_mention: true
```
