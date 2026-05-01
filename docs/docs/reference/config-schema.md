---
id: config-schema
title: Config Schema
sidebar_position: 3
---

# Config Schema

The main config file is `~/.arc/config.yaml`. It is created with defaults by `arc setup` or automatically on first run.

## Full default config

```yaml
daemon:
  auto_start: true
  socket_path: ~/.arc/arc.sock
  log_level: info
  pid_file: ~/.arc/daemon.pid

acpx:
  command: acpx
  default_agent: claude
  session_ttl: 300
  output_format: text

ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1

discord:
  enabled: false
  token_env: DISCORD_BOT_TOKEN
  guild_id: ""
  thread_mode: false
  rate_limit:
    messages_per_minute: 5

git:
  auto_pull: true
  auto_commit: true
  auto_push: false

timeouts:
  acpx_request: 300
  ollama_request: 120
  ipc_connect: 5

output:
  default_format: raw
  color: true

logging:
  log_routing: true
```

## daemon

Controls the background daemon process.

### daemon.auto_start

| Type | Default |
|---|---|
| bool | `true` |

When `true`, running `arc ask` automatically starts the daemon as a background process if it is not running. The CLI retries the IPC connection once after spawning the daemon.

```yaml
daemon:
  auto_start: true
```

Set to `false` if you prefer explicit daemon management.

---

### daemon.socket_path

| Type | Default |
|---|---|
| string (path) | `~/.arc/arc.sock` |

Path to the Unix domain socket used for CLI-to-daemon communication. The `~` is expanded at runtime. The socket file is created when the daemon starts and deleted on shutdown.

```yaml
daemon:
  socket_path: ~/.arc/arc.sock
```

---

### daemon.log_level

| Type | Default |
|---|---|
| string | `info` |

Python logging level for the daemon and CLI. Valid values: `debug`, `info`, `warning`, `error`, `critical`.

```yaml
daemon:
  log_level: info
```

Set to `debug` to see verbose dispatch and IPC traces.

---

### daemon.pid_file

| Type | Default |
|---|---|
| string (path) | `~/.arc/daemon.pid` |

Path to the file where the daemon writes its PID. Used by `arc daemon stop` and `arc daemon status` to find and signal the process.

```yaml
daemon:
  pid_file: ~/.arc/daemon.pid
```

The parent directory of `pid_file` is used as the arc config directory for locating `agents/`, `cron/`, and `logs/`.

---

## acpx

Controls the `acpx` Claude Code session manager.

### acpx.command

| Type | Default |
|---|---|
| string | `acpx` |

The executable name or path for `acpx`. Change this if `acpx` is installed in a non-standard location or you want to use a specific version.

```yaml
acpx:
  command: /usr/local/bin/acpx
```

---

### acpx.default_agent

| Type | Default |
|---|---|
| string | `claude` |

The `acpx` agent name (the Claude Code agent configuration within `acpx`). This is the argument passed to `acpx` after the global flags: `acpx ... <default_agent> exec ...`

```yaml
acpx:
  default_agent: claude
```

---

### acpx.session_ttl

| Type | Default |
|---|---|
| int (seconds) | `300` |

How long `acpx` keeps named sessions alive after the last activity. Used by Discord thread mode: sessions older than this value may be recreated on the next message, losing conversation context.

```yaml
acpx:
  session_ttl: 300
```

This value is informational in arc; the TTL is enforced by `acpx` itself.

---

### acpx.output_format

| Type | Default |
|---|---|
| string | `text` |

The output format requested from `acpx`. arc currently always passes `--format quiet` to suppress progress output; this config value is reserved for future use.

---

## ollama

Named Ollama endpoints for model routing.

### ollama.endpoints

| Type | Default |
|---|---|
| map[string, object] | `{local: {url: http://localhost:11434/v1}}` |

A map of endpoint names to URL objects. The `local` endpoint is the default for `ollama/<model>` model strings (without an explicit endpoint). Named endpoints are accessed with `ollama/<endpoint>/<model>`.

```yaml
ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1
    remote:
      url: http://192.168.1.100:11434/v1
    kyle:
      url: http://kyle-nuc.tailnet:11434/v1
```

Each endpoint object has a single field:

#### url

| Type | Required |
|---|---|
| string (URL) | yes |

The base URL of the Ollama-compatible API. arc appends `/chat/completions` to form the full request URL.

---

## discord

Discord bot configuration.

### discord.enabled

| Type | Default |
|---|---|
| bool | `false` |

Whether to start the Discord bot when the daemon starts. Set to `true` after configuring `token_env` and `guild_id`.

---

### discord.token_env

| Type | Default |
|---|---|
| string | `DISCORD_BOT_TOKEN` |

The name of the environment variable that holds the Discord bot token. The token itself should be stored in `~/.arc/.env`, not in `config.yaml`.

```yaml
discord:
  token_env: DISCORD_BOT_TOKEN
```

The daemon loads `~/.arc/.env` at startup using a minimal dotenv parser.

---

### discord.guild_id

| Type | Default |
|---|---|
| string | `""` |

Your Discord server's (guild) ID. When set, the bot ignores messages from other servers. Leave empty to allow the bot to operate in any server it is invited to (not recommended for production).

```yaml
discord:
  guild_id: "1234567890123456789"
```

---

### discord.thread_mode

| Type | Default |
|---|---|
| bool | `false` |

When `true`, the bot creates a new thread for each message that arrives outside a thread. Threads use persistent named `acpx` sessions so conversation context is preserved across messages in the same thread.

When `false`, the bot replies inline in the channel and each message is a one-shot dispatch with no conversation memory.

---

### discord.rate_limit.messages_per_minute

| Type | Default |
|---|---|
| int | `5` |

Maximum number of messages the bot will respond to per channel per 60-second sliding window. Messages that arrive after the limit is reached are silently dropped.

```yaml
discord:
  rate_limit:
    messages_per_minute: 5
```

---

## git

Automatic git operations in agent workspaces.

### git.auto_pull

| Type | Default |
|---|---|
| bool | `true` |

When `true`, the daemon runs `git pull` in the agent workspace before each dispatch. This keeps the agent's context files (system prompts, programs, etc.) up to date.

### git.auto_commit

| Type | Default |
|---|---|
| bool | `true` |

Reserved for future use. Not currently implemented.

### git.auto_push

| Type | Default |
|---|---|
| bool | `false` |

Reserved for future use. Not currently implemented.

---

## timeouts

Request timeout values in seconds.

### timeouts.acpx_request

| Type | Default |
|---|---|
| int (seconds) | `300` |

Maximum time to wait for `acpx` to return a response. If the timeout is exceeded, the subprocess is killed and a `DispatchError` is raised. Increase this for agents that run complex or long-running Claude Code tasks.

### timeouts.ollama_request

| Type | Default |
|---|---|
| int (seconds) | `120` |

Maximum time to wait for an Ollama API response. Increase for large models on slow hardware.

### timeouts.ipc_connect

| Type | Default |
|---|---|
| int (seconds) | `5` |

Maximum time to wait when connecting to the daemon socket. If the daemon does not respond within this time, the CLI treats it as not running and falls back.

---

## output

### output.default_format

| Type | Default |
|---|---|
| string | `raw` |

Default output format. Currently `raw` is the only supported value.

### output.color

| Type | Default |
|---|---|
| bool | `true` |

Reserved for future use.

---

## logging

### logging.log_routing

| Type | Default |
|---|---|
| bool | `true` |

When `true`, the daemon appends a JSON record to `~/.arc/logs/routing.jsonl` for each dispatched prompt. Records include timestamp, agent name, model, dispatch type, source, and a 100-character prompt preview.

Set to `false` to disable routing logs (e.g., for high-volume deployments where disk I/O is a concern).
