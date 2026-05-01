---
id: agents
title: Agent Configuration
sidebar_position: 1
---

# Agent Configuration

An agent is a YAML file in `~/.arc/agents/`. The filename (without `.yaml`) is the agent name used in `arc ask --agent <name>` and in cron job definitions.

## Creating an agent

### Interactive

```bash
arc agent create
# Agent name: coach
# Workspace path: /workspace/fitness-coach
# Model [claude-sonnet-4-6]: claude-sonnet-4-6
# Created agent 'coach' at /Users/you/.arc/agents/coach.yaml
```

### With flags

```bash
arc agent create \
  --name coach \
  --workspace /workspace/fitness-coach \
  --model claude-sonnet-4-6
```

### From an existing YAML file

```bash
arc agent create --from ./my-agent.yaml
# Created agent 'my-agent'.
```

The `--name` flag overrides the `name` field in the YAML if you want to rename it on import.

## Agent YAML structure

```yaml
name: coach
description: "Coach Kai - personal fitness coach"
workspace: /workspace/fitness-coach

system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md

model: claude-sonnet-4-6
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5

permission_mode: approve-all

discord:
  channel_id: "1234567890123456789"
  require_mention: false
```

## System prompt files

`system_prompt_files` is a list of filenames relative to `workspace`. arc reads each file that exists and concatenates them with `---` separators to form the system prompt.

```
# AGENTS.md

<contents>

---

# IDENTITY.md

<contents>

---
```

The conventional files and their purposes:

| File | Purpose |
|---|---|
| `AGENTS.md` | Claude Code instructions: tool use, coding conventions, agent behaviors |
| `IDENTITY.md` | Who the agent is: role, name, mission |
| `SOUL.md` | Tone, values, communication style |
| `USER.md` | User profile: preferences, history, context the agent should remember |
| `TOOLS.md` | Available tools and how the agent should use them |

These are conventions inherited from the OpenClaw ecosystem. You can use any filenames you like. Files that do not exist are skipped with a warning in the daemon log.

## Local context files (Ollama agents)

Ollama models cannot read the filesystem. The `local_context_files` field injects the content of workspace files directly into the request as a system message.

```yaml
name: trainer
workspace: /workspace/fitness-coach
model: ollama/qwen3:8b
local_context_files:
  - programs/current.md
  - weeks/current.md
```

Each file is read from `workspace/<filename>` and included verbatim under `--- <filename> ---` headers. Files that do not exist are skipped.

This is Ollama-specific: for Claude agents, the agent can read the filesystem directly via Claude Code's file tools.

## Model configuration

`model` is the default model for the agent. `allowed_models` is an optional list of models that callers are permitted to request. If `allowed_models` is empty, any model with the correct prefix (`claude-*` or `ollama/*`) is accepted.

```yaml
model: claude-sonnet-4-6
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5
  - ollama/qwen3:8b
```

A request for a model not in `allowed_models` is rejected with an error before dispatch.

## Permission mode

`permission_mode` controls how `acpx` handles tool use permissions. This only applies to Claude dispatch.

| Value | acpx flag | Behavior |
|---|---|---|
| `approve-all` | `--approve-all` | Auto-approve all tool use (file reads, writes, bash) |
| `approve-reads` | `--approve-reads` | Auto-approve reads; prompt for writes and bash |
| `deny-all` | `--deny-all` | Deny all tool use |
| `bypassPermissions` | `--approve-all` | Legacy Claude Code value, mapped to approve-all |
| `auto` | `--approve-all` | Legacy Claude Code value, mapped to approve-all |
| `acceptEdits` | `--approve-reads` | Legacy Claude Code value, mapped to approve-reads |

For fully automated headless operation (daemon, cron, Discord), use `approve-all`. For agents that should not modify files, use `approve-reads` or `deny-all`.

## Discord binding

Bind an agent to a Discord channel by setting `discord.channel_id` to the channel's ID (a string):

```yaml
discord:
  channel_id: "1234567890123456789"
  require_mention: false
```

`require_mention: true` means the bot only responds when @mentioned in the channel. The default is `false` (respond to every message).

Multiple agents can be bound to different channels in the same server. Each channel can only have one agent bound to it.

To get a channel ID in Discord: enable Developer Mode in settings, then right-click the channel and choose "Copy Channel ID".

## Managing agents

### List all agents

```bash
arc agent list
# coach            claude-sonnet-4-6            /workspace/fitness-coach  channel=1234567890123456789
# trainer          ollama/qwen3:8b              /workspace/fitness-coach
```

### Show agent config

```bash
arc agent show coach
```

Prints the raw YAML for the agent.

### Edit an agent

```bash
arc agent edit coach
```

Opens the agent YAML in `$EDITOR`. Changes take effect on the next request (the daemon re-reads agent files on each dispatch).

### Clone an agent

```bash
arc agent clone coach coach-dev
```

Creates a copy of `coach` as `coach-dev`. The clone's `discord.channel_id` is cleared so it does not accidentally steal messages from the original agent's channel.

### Delete an agent

```bash
arc agent delete coach
# Delete agent 'coach'? [y/N]: y
# Deleted agent 'coach'.
```

Use `--yes` to skip the confirmation prompt:

```bash
arc agent delete coach --yes
```

## Full example: fitness coach

```yaml
# ~/.arc/agents/coach.yaml
name: coach
description: "Coach Kai - AI-powered personal fitness coach"
workspace: /workspace/fitness-coach

system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md

model: claude-sonnet-4-6
allowed_models:
  - claude-sonnet-4-6
  - claude-haiku-4-5

permission_mode: approve-all

discord:
  channel_id: "1234567890123456789"
  require_mention: false
```

```yaml
# ~/.arc/agents/coach-quick.yaml
name: coach-quick
description: "Coach Kai on Haiku for fast, cheap responses"
workspace: /workspace/fitness-coach

system_prompt_files:
  - IDENTITY.md
  - SOUL.md

model: claude-haiku-4-5
allowed_models:
  - claude-haiku-4-5

permission_mode: approve-reads

discord: {}
```
