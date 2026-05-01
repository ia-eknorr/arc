---
id: quickstart
title: Quickstart
sidebar_position: 1
---

# Quickstart

This guide gets you from zero to a working agent in about five minutes.

## Prerequisites

- Python 3.11 or newer
- Node.js 22.12.0 or newer
- `acpx` CLI installed: `npm install -g acpx@latest`
- Claude Code CLI installed: `curl -fsSL https://claude.ai/install.sh | bash`

Ollama is optional. If you only want to use Claude models, you do not need it.

## 1. Install arc

The recommended method is `pipx`, which installs arc in an isolated environment and makes the `arc` command available globally:

```bash
pipx install arc-cli
```

Or with plain pip into the active environment:

```bash
pip install arc-cli
```

Verify the install:

```bash
arc version
# arc 0.2.0
```

## 2. Run arc setup

The setup wizard creates `~/.arc/` with a default config, the required subdirectories, and an `.env` file for secrets.

```bash
arc setup
```

Example output:

```
arc setup -- configuring /Users/you/.arc

  [ok] acpx: /usr/local/bin/acpx
  [ok] claude: /usr/local/bin/claude

Created /Users/you/.arc/config.yaml
Created /Users/you/.arc/.env (chmod 600)

Set up Discord bot? [y/N]: N

Setup complete. Run: arc daemon start
```

If `acpx` or `claude` shows `MISSING`, follow the install links in the output before continuing.

## 3. Create your first agent

Create an agent called `main` that uses your current directory as its workspace:

```bash
arc agent create \
  --name main \
  --workspace "$PWD" \
  --model sonnet
```

Or interactively (without flags, arc prompts for each value):

```bash
arc agent create
# Agent name: main
# Workspace path: /workspace/my-project
# Model [sonnet]:
```

Verify it was created:

```bash
arc agent list
# main             sonnet            /workspace/my-project
```

## 4. Start the daemon

```bash
arc daemon start
# Daemon started.
```

Check that it is running:

```bash
arc daemon status
# Daemon running (pid=12345, socket=/Users/you/.arc/arc.sock)
```

The daemon runs in the background. It manages IPC connections, cron jobs, and the Discord bot.

## 5. Send a prompt

```bash
arc ask --agent main "Explain what this project does."
```

arc routes the request to the daemon over IPC, which dispatches to Claude via `acpx`, and prints the response.

You can pipe stdin as part of the prompt:

```bash
cat README.md | arc ask --agent main "Summarize this in three sentences."
```

Override the model for a single request:

```bash
arc ask --agent main --model haiku "Quick question: what does this function do?"
```

Show dispatch metadata with `--pretty`:

```bash
arc ask --agent main --pretty "Hello"
# [acpx / claude-sonnet-4-6]
#
# Hello! How can I help you today?
```

## 6. Check status

```bash
arc status
```

Example output:

```
daemon    running (pid=12345, socket=/Users/you/.arc/arc.sock)

agents
  main             sonnet            /workspace/my-project

cron
  (no jobs configured)
```

## Next steps

- [Installation](./installation.md): full install options including pipx, scripts, and shell completions
- [Agent Configuration](../guides/agents.md): system prompt files, Discord binding, model allow-lists
- [Cron Scheduling](../guides/cron-scheduling.md): schedule recurring prompts
- [Discord Integration](../guides/discord.md): connect the bot to your server
