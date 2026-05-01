---
id: discord
title: Discord Integration
sidebar_position: 3
---

# Discord Integration

arc includes a `discord.py` bot that binds agents to Discord channels. Messages in a bound channel are dispatched to the agent and the response is posted back. Slash commands let you manage models, trigger cron jobs, and inspect system state without leaving Discord.

## Creating the bot

Before configuring arc, you need a Discord application and bot token.

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to "Bot" in the left sidebar
4. Under "Token", click "Reset Token" and copy the token
5. Enable the "Message Content Intent" under Privileged Gateway Intents
6. Go to "OAuth2" > "URL Generator"
7. Select scopes: `bot` and `applications.commands`
8. Select bot permissions: `Send Messages`, `Read Message History`, `Create Public Threads`
9. Copy the generated URL and open it to invite the bot to your server

> **Important:** The `applications.commands` scope is required for slash commands to appear in Discord. If you invited the bot without it, re-invite using a new URL with that scope added.

To get your server's guild ID: enable Developer Mode in Discord (Settings > Advanced), then right-click your server name and choose "Copy Server ID".

## Configuration

Store the bot token in `~/.arc/.env` (never in `config.yaml`):

```bash
echo "DISCORD_BOT_TOKEN=your-token-here" > ~/.arc/.env
chmod 600 ~/.arc/.env
```

Enable Discord in `~/.arc/config.yaml`:

```yaml
discord:
  enabled: true
  token_env: DISCORD_BOT_TOKEN   # environment variable name (not the token itself)
  guild_id: "1234567890123456789"  # your server's ID
  thread_mode: false
  rate_limit:
    messages_per_minute: 5
```

Run `arc setup` to be prompted for these values interactively, or set them manually as shown above.

## Binding an agent to a channel

Add a `discord.channel_id` to the agent YAML:

```yaml
name: coach
workspace: /workspace/fitness-coach
model: sonnet
discord:
  channel_id: "9876543210987654321"
  require_mention: false
```

To get a channel ID: right-click the channel in Discord and choose "Copy Channel ID" (Developer Mode must be enabled).

Restart the daemon for the change to take effect:

```bash
arc daemon restart
```

## How routing works

When a message arrives in any channel:

1. The bot checks if the message is from itself (ignored) and if the guild matches `guild_id`
2. It looks up which agent has `discord.channel_id` matching the channel ID
3. If the message is in a thread, it also checks the thread's parent channel
4. If no agent is bound, the message is ignored
5. If `require_mention` is true and the bot is not @mentioned, the message is ignored
6. The rate limiter is checked; if over the limit, the message is silently dropped
7. The prompt is dispatched to `ArcDaemon.handle_request` with `source=discord`

## require_mention

By default (`require_mention: false`), the bot responds to every message in the bound channel. Set `require_mention: true` to only respond when the bot is @mentioned:

```yaml
discord:
  channel_id: "9876543210987654321"
  require_mention: true
```

This is useful for channels where humans also chat and you only want the bot to respond when explicitly addressed.

## Thread mode

When `thread_mode: true` is set in config, the bot creates a new thread for each incoming message (if the message is not already in a thread):

```yaml
discord:
  enabled: true
  guild_id: "1234567890123456789"
  thread_mode: true
```

Threads use persistent named `acpx` sessions (`<agent>-<thread_id>`), so the agent maintains conversation context across multiple messages in the same thread. This is the primary way to have multi-turn conversations with a Claude agent.

Without thread mode, each message is dispatched as a one-shot request with no context from previous messages.

## Rate limiting

The `rate_limit.messages_per_minute` setting controls how many messages per channel the bot will respond to in a 60-second sliding window. If the limit is exceeded, the message is silently dropped (no response, no error).

```yaml
discord:
  rate_limit:
    messages_per_minute: 5
```

The rate limit is per channel, not per user. The default is 5 messages per minute.

---

## Slash commands

arc registers slash commands with Discord on startup. All commands appear in Discord's command picker when you type `/`. Commands are synced to your guild immediately if `guild_id` is configured; otherwise they propagate globally within an hour.

### /model

Switch or view the active model for the current channel.

```
/model [model]
```

| Usage | Effect |
|---|---|
| `/model` | Show the current model (visible only to you) |
| `/model haiku` | Switch to haiku for this channel |
| `/model ollama/kyle/gemma4-27b` | Switch to a local Ollama model |
| `/model reset` | Restore the agent's default model |

The autocomplete dropdown shows all models in the agent's `allowed_models` list plus `reset`. Use acpx aliases (`sonnet`, `haiku`) not full Anthropic model IDs.

Model overrides are sticky per channel and stored in daemon memory. They are lost on daemon restart.

```
Model set to `haiku`.
```

---

### /status

Show daemon state, configured agents, and next cron run times. Response is visible only to you.

```
/status
```

Example output:

```
daemon pid=12345 `/Users/you/.arc/arc.sock`

agents
  `coach` — sonnet | #fitness-coach
  `trainer` — haiku | #training
  `chat` — haiku | #general

cron
  `weekly-plan` — in 3h 14m
  `heartbeat` — in 12m
  `daily-summary` — disabled
```

---

### /agents

List all configured agents, their models, workspaces, and bound channels. Response is visible only to you.

```
/agents
```

Example output:

```
coach — `sonnet` | #fitness-coach
  `/workspace/fitness-coach`
trainer — `haiku` | #training
  `/workspace/fitness-coach`
```

---

### /history

Show recent routing log entries. Response is visible only to you.

```
/history [last]
```

| Option | Default | Description |
|---|---|---|
| `last` | 5 | Number of entries to show |

Example output:

```
2026-05-01 21:00 coach via `sonnet` — What's my workout today?
2026-05-01 20:30 coach via `haiku` — Quick question about tomorrow
2026-05-01 20:00 chat via `haiku` — What's the weather in Denver?
```

---

### /ask

Send a prompt to a specific agent from any channel, regardless of which channel the agent is normally bound to. The response is posted publicly. Defers automatically since responses can take time.

```
/ask <agent> <prompt>
```

| Option | Description |
|---|---|
| `agent` | Agent name (autocomplete shows all configured agents) |
| `prompt` | Prompt text to send |

Example:

```
/ask coach What's my workout today?
```

Useful for querying agents without switching channels, or for one-off queries from any channel.

---

### /cron run

Run a named cron job immediately. The job's output is posted publicly. Defers automatically since jobs dispatch to acpx.

```
/cron run <job>
```

| Option | Description |
|---|---|
| `job` | Job name (autocomplete shows all configured jobs) |

If the agent's `notify` is set to `discord` or `discord_on_urgent`, the output is also sent to the agent's bound channel as usual.

```
/cron run heartbeat
```

---

### /cron next

Show when each enabled job is scheduled to run next. Response is visible only to you.

```
/cron next
```

Example output:

```
`weekly-plan` — in 3h 14m
`heartbeat` — in 12m
`daily-summary` — disabled
```

---

## Cron notifications to Discord

Cron jobs can post their output to a channel by setting `notify: discord` or `notify: discord_on_urgent` in the job definition. The output is sent to the channel bound to the job's agent.

```yaml
jobs:
  weekly-plan:
    schedule: "0 19 * * 0"
    agent: coach
    prompt: "Write the weekly training plan."
    notify: discord
```

For this to work:
- The Discord bot must be running (`discord.enabled: true`)
- The agent must have `discord.channel_id` set
- The bot must have permission to send messages in that channel

## Multiple agents in one server

You can run multiple agents in the same Discord server, each bound to a different channel:

```yaml
# ~/.arc/agents/coach.yaml
name: coach
discord:
  channel_id: "111111111111111111"

# ~/.arc/agents/trainer.yaml
name: trainer
discord:
  channel_id: "222222222222222222"

# ~/.arc/agents/chat.yaml
name: chat
discord:
  channel_id: "333333333333333333"
```

Each channel operates independently. The `/model` override is per-channel, so switching models in the coach channel does not affect the trainer channel.

Slash commands like `/status`, `/agents`, and `/cron next` work from any channel — they show information about the entire arc installation, not just the current channel's agent.

## Security considerations

- Store the bot token in `~/.arc/.env` with mode 600, not in `config.yaml`
- Set `guild_id` to restrict the bot to your server; without it, the bot responds in any server it is invited to
- Use `require_mention: true` in public or semi-public channels to prevent the bot from responding to every message
- Use `rate_limit.messages_per_minute` to protect against accidental spam loops
- Slash commands like `/cron run` and `/ask` can trigger agent dispatches — consider who has access to the channels where arc is active
