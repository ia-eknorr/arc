---
id: installation
title: Installation
sidebar_position: 2
---

# Installation

## Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Required |
| Node.js | 22.12.0+ | Required for `acpx` |
| acpx | latest | `npm install -g acpx@latest` |
| Claude Code CLI | latest | `curl -fsSL https://claude.ai/install.sh \| bash` |
| Ollama | any | Optional, only needed for `ollama/*` models |

arc itself has no binary dependencies beyond what Python provides. The heavy lifting is done by external tools (`acpx`, `ollama`) that arc calls as subprocesses or over HTTP.

## Install via pipx (recommended)

`pipx` installs arc in an isolated virtual environment and adds the `arc` command to your PATH. This avoids conflicts with other Python packages.

```bash
# Install pipx if you do not have it
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Install arc
pipx install arc-cli
```

To upgrade:

```bash
pipx upgrade arc-cli
```

## Install via pip

If you prefer a plain pip install into the active environment:

```bash
pip install arc-cli
```

For development (editable install with test dependencies):

```bash
git clone git@github.com:ia-eknorr/arc.git
cd arc
pip install -e ".[dev]"
```

## Server install via install script

For headless server installs (LXC, VM, cloud instance), a shell script handles Python environment setup, directory creation, and optional systemd service registration:

```bash
git clone git@github.com:ia-eknorr/arc.git
cd arc
bash scripts/install.sh
```

The script:
1. Creates a Python venv at `/opt/arc/venv`
2. Installs arc-cli into the venv
3. Writes a systemd user service unit to `~/.config/systemd/user/arc-daemon.service`
4. Enables and starts the service

You can also generate the systemd unit yourself:

```bash
arc daemon install
# Wrote /home/user/.config/systemd/user/arc-daemon.service
# To enable: systemctl --user enable --now arc-daemon
```

Then enable it:

```bash
systemctl --user enable --now arc-daemon
```

## Shell completion

Typer generates completion scripts for bash, zsh, fish, and PowerShell.

Install for your current shell (one-time setup):

```bash
arc --install-completion
```

Print the script without installing (useful for system-wide setup or to inspect it):

```bash
arc --show-completion
```

For bash, you can also add the completion manually:

```bash
arc --show-completion bash >> ~/.bashrc
source ~/.bashrc
```

## Verify installation

```bash
arc version
# arc 0.1.0

arc setup
# Checks for acpx and claude, creates ~/.arc/ if it doesn't exist

arc daemon start
arc daemon status
# Daemon running (pid=12345, socket=/Users/you/.arc/arc.sock)
```

## Uninstall

```bash
# With pipx
pipx uninstall arc-cli

# Remove config and data (optional)
rm -rf ~/.arc
```
