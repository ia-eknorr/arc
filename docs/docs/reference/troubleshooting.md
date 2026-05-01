---
id: troubleshooting
title: Troubleshooting
sidebar_position: 5
---

# Troubleshooting

## Log file locations

| File | Contents |
|---|---|
| `~/.arc/logs/routing.jsonl` | One record per dispatched prompt |
| `~/.arc/logs/cron.jsonl` | One record per cron job run |
| `~/.arc/daemon.pid` | Daemon PID (only exists while daemon runs) |
| `~/.arc/arc.sock` | Unix socket (only exists while daemon runs) |

View logs with:

```bash
arc log routing --last 20
arc log cron --last 10
arc log tail        # tail -f both files
```

Enable debug logging for verbose output:

```bash
arc config set daemon.log_level debug
arc daemon restart
```

---

## Daemon not starting

**Symptom:** `arc daemon start` prints "Daemon started." but `arc daemon status` says "Daemon not running."

**Checks:**

1. Check if the PID file was created:

   ```bash
   cat ~/.arc/daemon.pid
   ```

2. Check if `acpx` and Python can be found:

   ```bash
   which acpx
   which arc
   ```

3. Start in foreground to see errors:

   ```bash
   arc daemon start --foreground
   ```

   This runs the daemon in the current terminal and prints any startup errors directly.

4. Check for a stale socket file:

   ```bash
   ls -la ~/.arc/arc.sock
   # If it exists but the daemon isn't running, remove it:
   rm ~/.arc/arc.sock
   arc daemon start
   ```

5. Verify the config file is valid YAML:

   ```bash
   python3 -c "import yaml; yaml.safe_load(open('$HOME/.arc/config.yaml'))"
   ```

---

## IPC connection refused

**Symptom:** `arc ask` falls back to direct dispatch instead of using the daemon, or prints IPC errors.

**Checks:**

1. Confirm the daemon is running:

   ```bash
   arc daemon status
   ```

2. Check the socket path matches in config:

   ```bash
   arc config show | grep socket_path
   ls ~/.arc/arc.sock
   ```

3. Check the IPC timeout. If the daemon is overloaded, it may not respond within `timeouts.ipc_connect` (default 5 seconds):

   ```bash
   arc config set timeouts.ipc_connect 15
   arc daemon restart
   ```

4. Direct dispatch still works without the daemon. If `arc ask` gives an answer even without the daemon, the dispatch path is fine; only IPC is affected.

---

## acpx not found

**Symptom:** `arc ask` or the daemon logs print `acpx: command not found` or `DispatchError: acpx exited 1`.

**Checks:**

1. Confirm `acpx` is installed:

   ```bash
   which acpx
   acpx --version
   ```

2. If not found, install it:

   ```bash
   npm install -g acpx@latest
   ```

3. If installed in a path that the daemon cannot see (e.g., nvm-managed Node.js), set the full path in config:

   ```bash
   arc config set acpx.command /home/user/.nvm/versions/node/v22.12.0/bin/acpx
   arc daemon restart
   ```

4. Confirm Claude Code is also installed (required by `acpx`):

   ```bash
   which claude
   curl -fsSL https://claude.ai/install.sh | bash
   ```

5. Check that `acpx` works manually:

   ```bash
   acpx --format quiet --cwd /tmp --model haiku --approve-all claude exec --file /dev/stdin <<< "Say hello"
   ```

---

## Discord bot not responding

**Symptom:** Messages in the bound channel produce no response from the bot.

**Checks:**

1. Confirm Discord is enabled in config:

   ```bash
   arc config show | grep -A5 discord
   ```

   `enabled` must be `true`.

2. Check that the bot token is in `~/.arc/.env`:

   ```bash
   cat ~/.arc/.env
   # Should contain: DISCORD_BOT_TOKEN=your-token-here
   ```

3. Check that the bot is online in your Discord server (should show as online in the member list).

4. Check the daemon logs for Discord errors:

   ```bash
   arc config set daemon.log_level debug
   arc daemon restart
   arc daemon start --foreground
   ```

   Look for lines like `Discord bot ready: BotName#1234` or error messages from `discord.py`.

5. Confirm the `channel_id` in the agent YAML matches the actual channel:

   ```bash
   arc agent show coach | grep channel_id
   ```

   Right-click the channel in Discord (Developer Mode enabled) and compare.

6. Check `guild_id` in config matches your server:

   ```bash
   arc config show | grep guild_id
   ```

   If `guild_id` is set to the wrong server, the bot ignores all messages.

7. Check `require_mention`. If `require_mention: true`, the bot only responds when @mentioned.

8. Check the rate limit. If you sent many messages quickly, the sliding window may have been hit:

   ```bash
   arc config set discord.rate_limit.messages_per_minute 20
   arc daemon restart
   ```

---

## Cron jobs not firing

**Symptom:** Jobs are listed in `arc cron list` but never run.

**Checks:**

1. Confirm the daemon is running:

   ```bash
   arc daemon status
   ```

   Cron only works when the daemon is running.

2. Check that the job is enabled:

   ```bash
   arc cron list
   # Look for [enabled] vs [disabled]
   ```

3. Verify the schedule expression is valid:

   ```bash
   arc cron next
   ```

   If a job shows "unknown" next run time, the schedule expression may be invalid. Try a simpler expression first.

4. Run the job manually to test:

   ```bash
   arc cron run weekly-plan
   ```

   If this fails, check the error output. Common issues: agent not found, model not in `allowed_models`, workspace path doesn't exist.

5. Check the cron log after a manual run:

   ```bash
   arc log cron --last 5
   ```

6. Check that changes to `jobs.yaml` were applied. Changes require a daemon restart:

   ```bash
   arc daemon restart
   arc cron list
   ```

---

## Model not in allowed_models error

**Symptom:** `Error: Model 'X' is not allowed for agent 'Y'. Allowed: ...`

**Resolution:**

Option 1: Add the model to `allowed_models` in the agent YAML:

```bash
arc agent edit coach
# Add the model to the allowed_models list
```

Option 2: Use a model that is already in the list:

```bash
arc ask --agent coach --model haiku "Hello"
```

Option 3: Clear `allowed_models` to allow any model with the correct prefix:

```bash
arc agent edit coach
# Set: allowed_models: []
```

---

## Ollama errors

**Symptom:** `Error: Cannot connect to Ollama at http://localhost:11434/v1. Is Ollama running?`

**Checks:**

1. Start Ollama:

   ```bash
   ollama serve
   ```

2. Verify the endpoint URL in config:

   ```bash
   arc config show | grep -A5 ollama
   ```

3. Test the endpoint directly:

   ```bash
   curl http://localhost:11434/v1/models
   ```

4. For named endpoints, verify the name matches exactly:

   ```bash
   # Model string: ollama/remote/qwen3:8b
   # Config must have:
   # ollama:
   #   endpoints:
   #     remote:
   #       url: http://...
   ```

**Symptom:** `Error: Ollama timed out after 120s`

Increase the timeout for large models:

```bash
arc config set timeouts.ollama_request 300
arc daemon restart
```

---

## Checking daemon status and health

```bash
# Basic status
arc daemon status

# Full status with agents and cron
arc status

# Live log tail
arc log tail

# Debug mode
arc config set daemon.log_level debug
arc daemon restart
arc daemon start --foreground  # see all output in terminal

# Check socket permissions
ls -la ~/.arc/arc.sock

# Check PID file
cat ~/.arc/daemon.pid

# Verify process is actually running
kill -0 $(cat ~/.arc/daemon.pid) 2>&1
```

---

## Enabling debug logging

Temporarily enable debug logging for a session:

```bash
arc config set daemon.log_level debug
arc daemon restart
arc daemon start --foreground
```

This prints every IPC request, dispatch call, Discord message event, and cron job execution to stdout.

Reset to normal:

```bash
arc config set daemon.log_level info
arc daemon restart
```
