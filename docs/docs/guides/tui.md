---
id: tui
title: Terminal UI (arc tui)
sidebar_position: 5
---

# Terminal UI

`arc tui` opens a k9s-style terminal management interface for day-to-day arc operations -- changing an agent's model, toggling a cron job, checking daemon status -- without hand-editing YAML.

```bash
arc tui
```

Requires the `tui` extra:

```bash
pip install -e ".[tui]"
```

## Panes

The interface has four panes. Switch between them with `h`/`l` or by clicking the tab headers.

### Status

The default pane. Shows daemon state, a list of configured agents with their models, and upcoming cron jobs with next-fire times. Auto-refreshes every 5 seconds.

- `r` - manual refresh
- `s` - start or stop the daemon

### Agents

Browse all agents. The left panel lists agent names; the right panel shows the selected agent's full configuration.

- `j` / `k` - move cursor
- `c` - change model (picks from `allowed_models` list)
- `e` - open agent YAML in `$EDITOR`
- `n` - create a new agent (interactive form: name, workspace, model)
- `d` - delete selected agent (confirmation required)

### Cron

Browse scheduled jobs with enable/disable status and next fire time.

- `space` - toggle selected job on or off
- `r` - run selected job immediately (daemon must be running)
- `e` - open jobs YAML in `$EDITOR`
- `n` - add a new job (interactive form: name, schedule, agent, prompt)
- `d` - delete selected job (confirmation required)

### Config

Inline editor for common config fields in `~/.arc/config.yaml`.

- `j` / `k` - move cursor
- `enter` - edit selected field (toggles booleans, cycles log level, opens input for others)
- `space` - toggle boolean fields
- `e` - open full `config.yaml` in `$EDITOR`

Fields that require a daemon restart show a warning after editing.

## Keybindings

| Key | Action |
|-----|--------|
| `h` | Previous tab |
| `l` | Next tab |
| `j` | Move cursor down |
| `k` | Move cursor up |
| `g` | Jump to top of list |
| `G` | Jump to bottom of list |
| `q` | Quit |

`h` and `l` work from anywhere in the interface -- even when the list has focus -- so you can navigate without reaching for the mouse.

## When the daemon is not running

The TUI works without a running daemon:

- Status pane shows "daemon not running" and reads agent/cron data from config files
- Agents and Config panes work fully (file reads/writes bypass the daemon)
- Cron "run now" is disabled and shows a warning
