---
id: changelog
title: Changelog
sidebar_position: 1
---

Full release notes are in [CHANGELOG.md](https://github.com/ia-eknorr/arc/blob/main/CHANGELOG.md) on GitHub.

---

## [v0.1.0] — 2026-05-01

**Initial release.**

### Added

- Agent dispatch to Claude via `acpx` and local/remote Ollama models via `httpx`
- Unix socket IPC daemon (`arc daemon start/stop/restart/status/install`)
- APScheduler cron with Discord notify modes (`discord`, `discord_on_urgent`)
- Discord bot with per-channel agent routing, rate limiting, and `/model` switching
- Full CLI: `arc ask`, `arc agent`, `arc cron`, `arc log`, `arc config`, `arc tokens`, `arc setup`
- OpenClaw migration (`arc import-openclaw`)
- Shell completions for zsh, bash, fish, and PowerShell
- Docusaurus documentation site

[v0.1.0]: https://github.com/ia-eknorr/arc/releases/tag/v0.1.0
