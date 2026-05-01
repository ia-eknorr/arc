---
id: cron-schema
title: Cron Schema
sidebar_position: 4
---

# Cron Schema

Cron jobs are defined in `~/.arc/cron/jobs.yaml`. The file contains a single top-level `jobs` key whose value is a map of job names to job objects.

## Full example

```yaml
# ~/.arc/cron/jobs.yaml
jobs:
  weekly-plan:
    description: "Generate weekly training plan every Sunday at 7 PM"
    schedule: "0 19 * * 0"
    agent: coach
    prompt: >
      It's a new week. Pull my Strava data, review what I completed vs planned,
      and generate the new weekly plan file. Save it as weeks/current.md.
    notify: discord
    enabled: true

  heartbeat:
    description: "Background log scanner"
    schedule: "*/30 * * * *"
    agent: coach
    model: haiku
    prompt: >
      Read HEARTBEAT.md and follow the instructions there strictly.
    notify: discord_on_urgent
    enabled: true

  daily-summary:
    description: "Evening training summary"
    schedule: "0 20 * * *"
    agent: coach
    prompt: "Summarize today's training session and update the daily log."
    enabled: false
```

## Top-level structure

The file must have a `jobs` key at the top level. Each key under `jobs` is the job name (a string). Names are used in `arc cron run <name>`, `arc cron enable <name>`, `arc cron disable <name>`, `arc cron history <name>`, and log entries.

```yaml
jobs:
  <job-name>:
    ...
  <job-name>:
    ...
```

## Job fields

### schedule

| Type | Required |
|---|---|
| string | yes |

A standard 5-field cron expression: `minute hour day-of-month month day-of-week`.

```yaml
schedule: "0 19 * * 0"    # Every Sunday at 7 PM
schedule: "*/30 * * * *"  # Every 30 minutes
schedule: "0 8 * * 1-5"   # Weekdays at 8 AM
schedule: "0 0 1 * *"     # First of every month at midnight
```

Parsed by `APScheduler`'s `CronTrigger.from_crontab()`. All standard cron syntax is supported including ranges (`1-5`), lists (`1,3,5`), and step values (`*/15`). There is no seconds field.

---

### agent

| Type | Required |
|---|---|
| string | yes |

The name of the agent that handles this job's prompt. Must match the filename stem of a YAML file in `~/.arc/agents/` (e.g., `agent: coach` references `~/.arc/agents/coach.yaml`).

```yaml
agent: coach
```

---

### prompt

| Type | Required |
|---|---|
| string | yes |

The prompt text sent to the agent at each scheduled run. Supports YAML multi-line strings:

```yaml
# Single line
prompt: "Summarize today's training."

# Block scalar (> folds newlines into spaces)
prompt: >
  It's a new week. Pull my Strava data, review what I completed vs planned,
  and generate the new weekly plan.

# Literal block scalar (| preserves newlines)
prompt: |
  Step 1: Check Strava for recent activities.
  Step 2: Compare against the plan.
  Step 3: Write the updated plan to weeks/current.md.
```

---

### enabled

| Type | Default |
|---|---|
| bool | `true` |

Whether the job is scheduled when the daemon starts. Set to `false` to suspend a job without removing it.

```yaml
enabled: true
enabled: false
```

Change with `arc cron enable <name>` or `arc cron disable <name>`. A daemon restart is required for the change to take effect.

---

### notify

| Type | Default |
|---|---|
| string or null | `null` (no notification) |

Controls whether and when the job's output is posted to Discord after the run completes.

| Value | Behavior |
|---|---|
| `discord` | Always post the full output to the agent's Discord channel |
| `discord_on_urgent` | Post only if the output contains the word "urgent" (case-insensitive) |
| omit or null | Never notify Discord |

For Discord notifications to work, the agent must have `discord.channel_id` set and the Discord bot must be running.

```yaml
notify: discord
notify: discord_on_urgent
```

---

### model

| Type | Default |
|---|---|
| string or null | `null` (use agent's default model) |

Override the agent's default model for this job. Uses the same format as the agent `model` field: acpx aliases for Claude, `ollama/...` for Ollama.

The override is validated against `allowed_models` if the agent has that list configured.

```yaml
model: haiku            # cheaper for frequent runs
model: ollama/qwen3:8b  # local model for privacy-sensitive runs
```

---

### description

| Type | Default |
|---|---|
| string | `""` |

A human-readable description of the job. Shown in `arc cron list`. Has no functional effect.

```yaml
description: "Generate weekly training plan every Sunday at 7 PM"
```

---

## Managing jobs.yaml

The file can be edited directly or via `arc cron` subcommands:

| Command | Effect |
|---|---|
| `arc cron add` | Appends a new job |
| `arc cron remove <name>` | Deletes a job |
| `arc cron enable <name>` | Sets `enabled: true` |
| `arc cron disable <name>` | Sets `enabled: false` |
| `arc cron edit <name>` | Opens the file in `$EDITOR` |

All changes require a daemon restart: `arc daemon restart`
