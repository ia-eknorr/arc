---
id: discord
title: Discord Integration
sidebar_position: 3
---

# Discord Integration

arc includes a `discord.py` bot that binds agents to Discord channels. Messages in a bound channel are dispatched to the agent and the response is posted back.

## Creating the bot

Before configuring arc, you need a Discord application and bot token.

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to "Bot" in the left sidebar
4. Under "Token", click "Reset Token" and copy the token
5. Enable the "Message Content Intent" under Privileged Gateway Intents
6. Go to "OAuth2" > "URL Generator"
7. Select scopes: `bot`
8. Select bot permissions: `Send Messages`, `Read Message History`, `Create Public Threads`
9. Copy the generated URL and open it to invite the bot to your server

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
  thread_mode: true
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

## The /model command

Discord users can switch the model for a channel using the `/model` command in the channel:

```
/model haiku
```

The bot responds: `Model set to haiku.`

Use acpx aliases (`sonnet`, `haiku`, `default`) not full Anthropic model IDs. The alias must also be in the agent's `allowed_models` list.

The switch is sticky: subsequent messages in that channel use the new model until reset.

Check the current model:

```
/model
```

Response: `Current model: claude-sonnet-4-6`

Reset to the agent's default:

```
/model reset
```

The `/model` command only accepts models listed in the agent's `allowed_models`. If the list is empty, no model switching is permitted. Example response for an unauthorized model:

```
Model 'gpt-4' not allowed. Options: claude-sonnet-4-6, claude-haiku-4-5
```

Model overrides are stored in daemon memory and are lost on daemon restart.

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

# ~/.arc/agents/main.yaml
name: main
discord:
  channel_id: "333333333333333333"
```

Each channel operates independently. The `/model` override is per-channel, so switching models in the coach channel does not affect the trainer channel.

## Security considerations

- Store the bot token in `~/.arc/.env` with mode 600, not in `config.yaml`
- Set `guild_id` to restrict the bot to your server; without it, the bot responds in any server it is invited to
- Use `require_mention: true` in public or semi-public channels to prevent the bot from responding to every message
- Use `rate_limit.messages_per_minute` to protect against accidental spam loops
