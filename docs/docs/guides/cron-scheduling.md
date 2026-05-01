---
id: cron-scheduling
title: Cron Scheduling
sidebar_position: 2
---

# Cron Scheduling

arc uses APScheduler's `AsyncIOScheduler` with `CronTrigger.from_crontab()` to schedule agent prompts. Jobs are defined in `~/.arc/cron/jobs.yaml` and managed with the `arc cron` subcommands.

## How it works

When the daemon starts, `CronManager` reads `jobs.yaml` and registers each enabled job with the scheduler. At each scheduled time, the job calls `ArcDaemon.run_cron_job`, which:

1. Sends the job's prompt to the job's agent via the standard `handle_request` path
2. Checks the `notify` setting and sends output to Discord if applicable
3. Appends a record to `~/.arc/logs/cron.jsonl`

Cron jobs always use one-shot dispatch (no persistent sessions). If the daemon is not running, cron jobs do not fire.

## jobs.yaml format

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
    description: "Background log scanner every 30 minutes"
    schedule: "*/30 * * * *"
    agent: coach
    model: haiku
    prompt: >
      Read HEARTBEAT.md and follow it strictly.
    notify: discord_on_urgent
    enabled: true

  daily-summary:
    description: "Daily workout summary at 8 PM"
    schedule: "0 20 * * *"
    agent: coach
    prompt: "Summarize today's training and update the daily log."
    enabled: true
```

Each key under `jobs:` is the job name. The name is used in `arc cron run <name>`, `arc cron enable <name>`, and log entries.

## Schedule expressions

arc uses standard 5-field cron syntax: `minute hour day-of-month month day-of-week`.

| Expression | Meaning |
|---|---|
| `0 19 * * 0` | Every Sunday at 7:00 PM |
| `0 8 * * 1-5` | Weekdays at 8:00 AM |
| `0 20 * * *` | Every day at 8:00 PM |
| `*/30 * * * *` | Every 30 minutes |
| `0 */2 * * *` | Every 2 hours |
| `0 0 1 * *` | First of every month at midnight |
| `15 14 1 * *` | First of every month at 2:15 PM |

The `from_crontab()` function accepts all standard expressions supported by APScheduler, including ranges (`1-5`), lists (`1,3,5`), and step values (`*/15`).

## Notify modes

The `notify` field controls whether and when the job's output is posted to Discord.

| Value | Behavior |
|---|---|
| `discord` | Always post the full output to the agent's Discord channel |
| `discord_on_urgent` | Post only if the output contains the word "urgent" (case-insensitive) |
| omit | Never notify Discord |

Discord notifications require the agent to have a `discord.channel_id` configured and the Discord bot to be running.

## Model override

A cron job can override the agent's default model for that job only:

```yaml
heartbeat:
  schedule: "*/30 * * * *"
  agent: coach
  model: claude-haiku-4-5   # use a cheaper model for frequent runs
  prompt: "Read HEARTBEAT.md and follow it."
  notify: discord_on_urgent
```

The model override follows the same validation rules as `--model` on `arc ask`: if `allowed_models` is non-empty, the override must be in the list.

## Managing jobs

### List all jobs

```bash
arc cron list
```

Output:

```
weekly-plan          [enabled]   0 19 * * 0
  Generate weekly training plan every Sunday at 7 PM
heartbeat            [enabled]   */30 * * * *  model=claude-haiku-4-5  notify=discord_on_urgent
  Background log scanner every 30 minutes
daily-summary        [disabled]  0 20 * * *
```

### Add a job

```bash
arc cron add \
  --name daily-summary \
  --schedule "0 20 * * *" \
  --agent coach \
  --prompt "Summarize today's training."
# Added job 'daily-summary'. Restart daemon to schedule it.
```

Add interactively (without flags):

```bash
arc cron add
# Job name: daily-summary
# Schedule (cron expression): 0 20 * * *
# Agent name: coach
# Prompt: Summarize today's training.
```

With notify and model override:

```bash
arc cron add \
  --name heartbeat \
  --schedule "*/30 * * * *" \
  --agent coach \
  --prompt "Read HEARTBEAT.md and follow it." \
  --notify discord_on_urgent \
  --model claude-haiku-4-5
```

### Remove a job

```bash
arc cron remove heartbeat
# Removed job 'heartbeat'. Restart daemon to apply.
```

### Enable and disable

```bash
arc cron enable daily-summary
# Enabled daily-summary. Restart the daemon to apply.

arc cron disable heartbeat
# Disabled heartbeat. Restart the daemon to apply.
```

Changes to `enabled` take effect after a daemon restart.

### Run a job immediately

```bash
arc cron run weekly-plan
```

If the daemon is running, the request is routed through IPC so Discord notifications and logging fire. If the daemon is not running, the job is dispatched directly without Discord notification.

### Show next scheduled times

```bash
arc cron next
```

Output:

```
weekly-plan          2026-05-03 19:00 MDT
heartbeat            2026-04-30 22:30 MDT
daily-summary        [disabled]
```

### View run history

```bash
arc cron history
# 2026-04-30 21:00  weekly-plan          [ok]   The new weekly plan has been created...
# 2026-04-30 20:30  heartbeat            [ok]   No urgent items found.
```

Filter by job name:

```bash
arc cron history heartbeat --last 5
```

### Edit the jobs file directly

```bash
arc cron edit heartbeat
```

This opens `~/.arc/cron/jobs.yaml` in `$EDITOR`. The `name` argument is accepted but currently unused; the command always opens the full jobs file.

## Cron log

Each job run appends a record to `~/.arc/logs/cron.jsonl`:

```json
{
  "timestamp": "2026-04-30T21:00:05.123456+00:00",
  "job": "weekly-plan",
  "status": "ok",
  "output_preview": "The new weekly plan has been created for the week of May 3..."
}
```

View with `arc log cron` or `arc log tail`.

## Daemon restart after changes

Changes to `jobs.yaml` (add, remove, enable, disable, schedule edits) require a daemon restart to take effect. The `arc cron add`, `arc cron remove`, `arc cron enable`, and `arc cron disable` commands all print a reminder:

```
Restart daemon to apply.
```

Restart with:

```bash
arc daemon restart
```
