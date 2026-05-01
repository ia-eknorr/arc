---
id: migration
title: Migrating from OpenClaw
sidebar_position: 5
---

# Migrating from OpenClaw

arc includes a migration tool that reads an existing OpenClaw installation and converts agents and cron jobs to arc format.

## Why migrate?

OpenClaw is a capable agent router, but it requires a TypeScript runtime, a separate process manager, and a JSON-heavy configuration format. arc replaces the same functionality with plain Python and YAML files that you can read and edit without tooling.

What you gain:
- Simpler config: YAML instead of JSON, flat file per agent
- Standard cron expressions instead of a custom scheduler API
- A single Python package with no build step
- `arc ask` from the CLI without starting a separate server

## What gets converted

The importer reads `~/.openclaw/openclaw.json` and `~/.openclaw/cron/jobs.json`.

| OpenClaw | arc |
|---|---|
| Agent definitions (id, workspace, model, description) | `~/.arc/agents/<name>.yaml` |
| Discord channel bindings (type: route) | `discord.channel_id` in agent YAML |
| Cron jobs (cron kind) | `~/.arc/cron/jobs.yaml` |
| Cron jobs (every kind, everyMs) | Converted to `*/N * * * *` expression |

Model name mapping:

| OpenClaw model | arc model |
|---|---|
| `anthropic/claude-sonnet-4-6` | `claude-sonnet-4-6` |
| `anthropic/claude-haiku-4-5` | `claude-haiku-4-5` |
| `anthropic/claude-opus-4-7` | `claude-opus-4-7` |
| Other `anthropic/X` | `X` (prefix stripped) |

## Running arc import-openclaw

### Dry run first

Always do a dry run before writing files:

```bash
arc import-openclaw --dry-run
```

Output:

```
Dry run -- reading from /Users/you/.openclaw, would write to /Users/you/.arc

  [dry-run] would import agent: coach
  [dry-run] would import agent: trainer
  [dry-run] would import cron job: weekly-plan
  [dry-run] would import cron job: heartbeat
  Skipped: agent:main (already exists)
```

The dry run reads and parses all OpenClaw files but does not write anything.

### Import

```bash
arc import-openclaw
```

Output:

```
Importing from /Users/you/.openclaw into /Users/you/.arc

  Imported agent: coach
  Imported agent: trainer
  Imported cron job: weekly-plan
  Imported cron job: heartbeat

Done. Review ~/.arc/agents/ and restart the daemon.
```

### Custom OpenClaw directory

```bash
arc import-openclaw --from /opt/openclaw
```

### Summary of flags

| Flag | Default | Description |
|---|---|---|
| `--from` | `~/.openclaw` | Path to the OpenClaw config directory |
| `--dry-run` | false | Preview without writing |

## OpenClaw to arc format mapping

### Agent

OpenClaw `openclaw.json` (agents section):

```json
{
  "agents": {
    "list": [
      {
        "id": "coach",
        "description": "Coach Kai",
        "workspace": "/workspace/fitness-coach",
        "model": {
          "primary": "anthropic/claude-sonnet-4-6"
        }
      }
    ]
  },
  "bindings": [
    {
      "type": "route",
      "agentId": "coach",
      "match": {
        "channel": "discord",
        "peer": {
          "kind": "channel",
          "id": 1234567890123456789
        }
      }
    }
  ]
}
```

Resulting arc `~/.arc/agents/coach.yaml`:

```yaml
name: coach
description: Coach Kai
workspace: /workspace/fitness-coach
system_prompt_files:
  - AGENTS.md
  - IDENTITY.md
  - SOUL.md
  - USER.md
  - TOOLS.md
model: claude-sonnet-4-6
allowed_models: []
permission_mode: approve-all
discord:
  channel_id: '1234567890123456789'
```

`system_prompt_files` is populated by scanning the agent's workspace for the standard identity files that exist.

### Cron job

OpenClaw `cron/jobs.json`:

```json
{
  "jobs": [
    {
      "name": "weekly-plan",
      "description": "Weekly training plan",
      "agentId": "coach",
      "schedule": {
        "kind": "cron",
        "expr": "0 19 * * 0"
      },
      "payload": {
        "message": "Write the weekly training plan."
      },
      "enabled": true
    },
    {
      "name": "heartbeat",
      "agentId": "coach",
      "schedule": {
        "kind": "every",
        "everyMs": 1800000
      },
      "payload": {
        "message": "Read HEARTBEAT.md and follow it."
      },
      "enabled": true
    }
  ]
}
```

Resulting arc `~/.arc/cron/jobs.yaml`:

```yaml
jobs:
  weekly-plan:
    description: Weekly training plan
    schedule: '0 19 * * 0'
    agent: coach
    prompt: Write the weekly training plan.
    notify: discord
    enabled: true
  heartbeat:
    description: ''
    schedule: '*/30 * * * *'
    agent: coach
    prompt: Read HEARTBEAT.md and follow it.
    notify: discord
    enabled: true
```

Note: `everyMs: 1800000` (30 minutes) becomes `*/30 * * * *`. All imported cron jobs get `notify: discord` by default.

## What does not migrate

| OpenClaw feature | Status |
|---|---|
| Non-Discord bindings (webhooks, etc.) | Not migrated, requires manual setup |
| Custom schedule kinds (other than `cron` and `every`) | Falls back to `0 * * * *` (hourly) |
| Agent-level permission config | All agents get `approve-all` |
| `allowed_models` | Not set; add manually if needed |
| Cron job model overrides | Not set; add manually if needed |
| Notify per job (discord vs discord_on_urgent) | All get `discord`; edit manually |

## Post-migration checklist

After running `arc import-openclaw`:

1. Review each agent YAML in `~/.arc/agents/` and verify workspace paths exist
2. Check that `discord.channel_id` values are correct (they are converted to strings)
3. Review `~/.arc/cron/jobs.yaml` and adjust `notify` values where `discord_on_urgent` is more appropriate than `discord`
4. Add `allowed_models` lists to agents where you want to restrict model access
5. Set `model` overrides on cron jobs that should use a cheaper model
6. Verify `system_prompt_files` lists the files that actually exist in each workspace
7. Run `arc setup` if you have not already done so (creates config and directories)
8. Start the daemon: `arc daemon start`
9. Test each agent: `arc ask --agent <name> "Hello"`
10. Check `arc status` to confirm all agents and cron jobs are loaded
