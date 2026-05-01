# CLAUDE.md -- arc project

Read `.design/design.md` for the full design document before starting any work.

## What this is

arc is a Python CLI and daemon for agent dispatch, cron scheduling, and Discord
integration. It replaces OpenClaw with ~800 lines of Python, using acpx for Claude
Code session management and httpx for Ollama.

## Tech

- Python 3.11+, src layout, hatchling build
- typer (CLI), httpx (Ollama), apscheduler (cron), discord.py, pyyaml
- acpx (npm, external CLI) for Claude Code dispatch
- pytest, pytest-asyncio, pytest-httpx, ruff for dev

## Rules

- No em dashes. Not as `--` either. Use a comma, colon, or rewrite.
- No emoji.
- Follow the design doc phases in order. Do not skip ahead.
- Write tests alongside implementation, not after.
- Use async/await throughout (daemon is asyncio-based).
- Type hints on all function signatures.
- Docstrings on all public functions.

## File structure

```
src/arc/
  __init__.py
  __main__.py         # entry point
  cli.py              # typer app
  daemon.py           # ArcDaemon class
  dispatcher.py       # acpx + Ollama dispatch
  agents.py           # agent config loading
  cron.py             # APScheduler wrapper
  discord_bridge.py   # discord.py bot
  ipc.py              # Unix socket protocol
  config.py           # config loading/validation
  setup_wizard.py     # first-run setup
  import_openclaw.py  # migration
  types.py            # dataclasses
  utils.py            # shared helpers
```

## Testing

- pytest with asyncio mode
- Mock acpx with monkeypatched subprocess calls
- Mock Ollama with pytest-httpx
- Mock Discord with unittest.mock
- Config tests use tmp_path fixtures
- Target 80%+ coverage on core modules (dispatcher, agents, config)