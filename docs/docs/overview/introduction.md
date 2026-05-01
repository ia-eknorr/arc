---
id: introduction
title: Introduction
sidebar_position: 1
slug: /
---

# Introduction

arc is a lightweight Python CLI and daemon for agent dispatch, cron scheduling, and Discord integration. It replaces the OpenClaw agent router with roughly 800 lines of Python, using `acpx` for Claude Code session management and `httpx` for Ollama models.

## Why arc?

OpenClaw was a capable agent orchestration layer, but it carried significant operational complexity: a TypeScript runtime, a process manager, JSON-heavy config files, and tight coupling between components. arc trades breadth for simplicity.

The goals:

- A single `arc` binary that works from the CLI, as a background daemon, and as a Discord bot
- Two dispatch paths: Claude (via `acpx`) and Ollama (via HTTP), selected automatically by model prefix
- Standard cron expressions backed by APScheduler, not a custom scheduler
- Agent config as plain YAML files you can read and edit without tooling
- Zero external services required: everything runs from `~/.arc/`

## Features

| Feature | Description |
|---|---|
| `arc ask` | Send a prompt to any agent from the command line |
| Agent dispatch | Route to Claude or Ollama based on model prefix |
| Unix socket IPC | Daemon accepts requests from CLI, Discord, and cron without spawning new processes |
| APScheduler cron | Standard 5-field cron expressions, enable/disable per job |
| Discord bot | Bind agents to channels; per-channel model switching with `/model` |
| Discord threads | Optional thread-per-conversation with persistent `acpx` sessions |
| Rate limiting | Sliding-window per-channel rate limit |
| Git integration | Auto-pull workspace repos before each dispatch |
| OpenClaw migration | `arc import-openclaw` converts agents and cron jobs |
| Token tracking | `arc tokens` wraps `codeburn` for Claude usage reporting |

## Quick example

```bash
# Install
pip install arc-cli

# First-run setup
arc setup

# Create an agent
arc agent create --name coach \
  --workspace /workspace/fitness-coach \
  --model sonnet

# Start the daemon
arc daemon start

# Send a prompt
arc ask --agent coach "What's my workout today?"
```

The daemon routes the request through IPC, dispatches to Claude via `acpx`, and prints the response. If the daemon is not running, `arc ask` falls back to direct dispatch automatically.

## Architecture at a glance

```
CLI / Discord / Cron
        |
    Unix socket (IPC)
        |
    ArcDaemon
        |
   Dispatcher
   /         \
acpx        httpx
(Claude)   (Ollama)
```

Continue to [Architecture](./architecture.md) for a detailed breakdown, or jump to [Quickstart](../getting-started/quickstart.md) to get running in five minutes.
