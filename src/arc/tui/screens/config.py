"""Config screen: inline editing of common config fields."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from arc.config import load_config
from arc.tui.screens.agents import InputScreen

# Fields that affect the daemon process and require a restart on change.
_RESTART_REQUIRED = {"daemon.socket_path", "daemon.pid_file", "daemon.log_level"}

# Fields that are boolean toggles.
_BOOL_FIELDS = {"daemon.auto_start", "discord.enabled"}

# Log level choices for cycling.
_LOG_LEVELS = ["debug", "info", "warning", "error"]


def _config_path() -> Path:
    cfg = load_config()
    return Path(cfg.daemon.pid_file).expanduser().parent / "config.yaml"


def _load_config_raw() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _save_config_raw(data: dict) -> None:
    _config_path().write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _get_nested(data: dict, key: str):
    parts = key.split(".")
    node = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_nested(data: dict, key: str, value) -> None:
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


class ConfigRow:
    """Represents one editable config row."""

    def __init__(self, label: str, key: str, kind: str = "str", hint: str = "") -> None:
        self.label = label
        self.key = key
        self.kind = kind  # "bool", "int", "str", "loglevel", "readonly"
        self.hint = hint


# Ordered list of displayed config rows.
ROWS: list[ConfigRow] = [
    ConfigRow("DAEMON", "", "section"),
    ConfigRow("  auto_start", "daemon.auto_start", "bool", "toggle with space/enter"),
    ConfigRow("  log_level", "daemon.log_level", "loglevel", "debug/info/warning/error"),
    ConfigRow("  socket_path", "daemon.socket_path", "readonly"),
    ConfigRow("  pid_file", "daemon.pid_file", "readonly"),
    ConfigRow("TIMEOUTS", "", "section"),
    ConfigRow("  acpx_request", "timeouts.acpx_request", "int", "seconds"),
    ConfigRow("  ollama_request", "timeouts.ollama_request", "int", "seconds"),
    ConfigRow("DISCORD", "", "section"),
    ConfigRow("  enabled", "discord.enabled", "bool", "toggle with space/enter"),
    ConfigRow("  guild_id", "discord.guild_id", "str"),
    ConfigRow("GIT", "", "section"),
    ConfigRow("  auto_pull", "git.auto_pull", "bool", "toggle with space/enter"),
]


def _build_lines(data: dict) -> list[tuple[str, ConfigRow | None]]:
    """Build display lines paired with their config row (or None for section headers)."""
    lines = []
    for row in ROWS:
        if row.kind == "section":
            lines.append((f"\n[bold]{row.label}[/bold]", None))
            continue
        val = _get_nested(data, row.key)
        if val is None:
            val = ""
        hint = f"  [dim]{row.hint}[/dim]" if row.hint else ""
        if row.kind == "bool":
            display = "[green]true[/green]" if val else "[red]false[/red]"
        elif row.kind == "readonly":
            display = f"[dim]{val}[/dim]"
        else:
            display = str(val)
        restart = row.key in _RESTART_REQUIRED and val
        needs_restart = " [yellow]*restart required*[/yellow]" if restart else ""
        lines.append((f"  {row.label:<22}  {display}{hint}{needs_restart}", row))
    return lines


class ConfigPane(Widget):
    """Config tab: inline config editing."""

    BINDINGS = [
        Binding("e", "edit_full", "Edit file"),
        Binding("enter", "edit_field", "Edit"),
        Binding("space", "toggle_field", "Toggle"),
    ]

    DEFAULT_CSS = """
    ConfigPane {
        height: 1fr;
    }
    #config-list {
        height: 1fr;
    }
    #config-hint {
        height: 3;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]CONFIG[/bold]  [dim](e: edit full file  enter/space: edit field)[/dim]",
                    classes="section-title")
        yield ListView(id="config-list")
        yield Static("", id="config-hint")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        data = _load_config_raw()
        self._data = data
        self._lines = _build_lines(data)
        lv = self.query_one("#config-list", ListView)
        lv.clear()
        for text, row in self._lines:
            lv.append(ListItem(Static(text)))

    def _selected_row(self) -> ConfigRow | None:
        lv = self.query_one("#config-list", ListView)
        idx = lv.index
        if idx is None or idx >= len(self._lines):
            return None
        _, row = self._lines[idx]
        return row

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        row = self._selected_row()
        if row and row.kind not in ("section", "readonly"):
            self.query_one("#config-hint", Static).update(
                f"  key: {row.key}  |  enter: edit  space: toggle (bool)"
            )
        else:
            self.query_one("#config-hint", Static).update("")

    def action_edit_full(self) -> None:
        path = _config_path()
        editor = os.environ.get("EDITOR", "vi")
        with self.app.suspend():
            subprocess.run([editor, str(path)])
        self._refresh()

    def action_toggle_field(self) -> None:
        row = self._selected_row()
        if not row or row.kind != "bool":
            return
        data = _load_config_raw()
        current = _get_nested(data, row.key)
        _set_nested(data, row.key, not bool(current))
        _save_config_raw(data)
        if row.key in _RESTART_REQUIRED:
            self.notify(f"{row.key} updated. Daemon restart required.", severity="warning")
        else:
            self.notify(f"{row.key} = {not bool(current)}")
        self._refresh()

    def action_edit_field(self) -> None:
        row = self._selected_row()
        if not row or row.kind in ("section", "readonly"):
            return
        if row.kind == "bool":
            self.action_toggle_field()
            return

        data = _load_config_raw()
        current = str(_get_nested(data, row.key) or "")

        if row.kind == "loglevel":
            # Cycle through log levels
            try:
                idx = _LOG_LEVELS.index(current)
                new_val = _LOG_LEVELS[(idx + 1) % len(_LOG_LEVELS)]
            except ValueError:
                new_val = "info"
            _set_nested(data, row.key, new_val)
            _save_config_raw(data)
            self.notify(f"{row.key} = {new_val}")
            self._refresh()
            return

        async def _do() -> None:
            new_str = await self.app.push_screen_wait(InputScreen(f"Set {row.key}:", current))
            if new_str is None:
                return
            if row.kind == "int":
                try:
                    new_val = int(new_str)
                except ValueError:
                    self.notify(f"'{new_str}' is not a valid integer.", severity="error")
                    return
            else:
                new_val = new_str
            _set_nested(data, row.key, new_val)
            _save_config_raw(data)
            if row.key in _RESTART_REQUIRED:
                self.notify(f"{row.key} updated. Daemon restart required.", severity="warning")
            else:
                self.notify(f"{row.key} = {new_val}")
            self._refresh()

        import asyncio
        asyncio.create_task(_do())
