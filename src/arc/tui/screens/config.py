"""Config screen: inline editing of common config fields."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Label, ListItem, Static

from arc.config import load_config
from arc.tui.screens.agents import InputScreen
from arc.tui.widgets.vim_list import VimListView

_RESTART_REQUIRED = {"daemon.socket_path", "daemon.pid_file", "daemon.log_level"}
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

    def __init__(
        self, label: str, key: str, kind: str = "str", hint: str = ""
    ) -> None:
        self.label = label
        self.key = key
        self.kind = kind
        self.hint = hint


ROWS: list[ConfigRow] = [
    ConfigRow("DAEMON", "", "section"),
    ConfigRow("  auto_start", "daemon.auto_start", "bool", "space/enter: toggle"),
    ConfigRow("  log_level", "daemon.log_level", "loglevel", "enter: cycle"),
    ConfigRow("  socket_path", "daemon.socket_path", "readonly"),
    ConfigRow("  pid_file", "daemon.pid_file", "readonly"),
    ConfigRow("TIMEOUTS", "", "section"),
    ConfigRow("  acpx_request", "timeouts.acpx_request", "int", "seconds"),
    ConfigRow("  ollama_request", "timeouts.ollama_request", "int", "seconds"),
    ConfigRow("DISCORD", "", "section"),
    ConfigRow("  enabled", "discord.enabled", "bool", "space/enter: toggle"),
    ConfigRow("  guild_id", "discord.guild_id", "str"),
    ConfigRow("GIT", "", "section"),
    ConfigRow("  auto_pull", "git.auto_pull", "bool", "space/enter: toggle"),
]


def _build_lines(data: dict) -> list[tuple[str, ConfigRow | None]]:
    lines = []
    for row in ROWS:
        if row.kind == "section":
            lines.append((f"[bold]{row.label}[/bold]", None))
            continue
        val = _get_nested(data, row.key)
        if val is None:
            val = ""
        hint = f"  [dim]{row.hint}[/dim]" if row.hint else ""
        if row.kind == "bool":
            display = "[green]true [/green]" if val else "[red]false[/red]"
        elif row.kind == "readonly":
            display = f"[dim]{val}[/dim]"
        else:
            display = str(val)
        restart = row.key in _RESTART_REQUIRED and val
        restart_warn = " [yellow]*restart required*[/yellow]" if restart else ""
        lines.append(
            (f"  {row.label:<22}  {display}{hint}{restart_warn}", row)
        )
    return lines


class ConfigPane(Widget):
    """Config tab: inline config editing."""

    BINDINGS = [
        Binding("e", "edit_full", "Edit file"),
        Binding("enter", "edit_field", "Edit"),
        Binding("space", "toggle_field", "Toggle"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    ConfigPane {
        height: 1fr;
        padding: 0;
    }
    #config-header {
        padding: 0 1;
        background: $surface;
        color: $accent;
        text-style: bold;
    }
    #config-list {
        height: 1fr;
    }
    #config-hint {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(
            " CONFIG  j/k: nav  enter/space: edit  e: full file",
            id="config-header",
        )
        yield VimListView(id="config-list")
        yield Static("", id="config-hint")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        data = _load_config_raw()
        self._data = data
        self._lines = _build_lines(data)
        lv = self.query_one("#config-list", VimListView)
        lv.clear()
        for text, _row in self._lines:
            lv.append(ListItem(Static(text)))

    def _selected_row(self) -> ConfigRow | None:
        lv = self.query_one("#config-list", VimListView)
        idx = lv.index
        if idx is None or idx >= len(self._lines):
            return None
        _, row = self._lines[idx]
        return row

    def on_list_view_highlighted(self, event: VimListView.Highlighted) -> None:
        row = self._selected_row()
        if row and row.kind not in ("section", "readonly"):
            hint = f"  key: {row.key}"
            if row.kind == "bool":
                hint += "  |  space/enter: toggle"
            elif row.kind == "loglevel":
                hint += "  |  enter: cycle levels"
            else:
                hint += "  |  enter: edit value"
            self.query_one("#config-hint", Static).update(hint)
        else:
            self.query_one("#config-hint", Static).update("")

    def action_cursor_down(self) -> None:
        self.query_one("#config-list", VimListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#config-list", VimListView).action_cursor_up()

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
            new_str = await self.app.push_screen_wait(
                InputScreen(f"Set {row.key}:", current)
            )
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
                self.notify(
                    f"{row.key} updated. Daemon restart required.", severity="warning"
                )
            else:
                self.notify(f"{row.key} = {new_val}")
            self._refresh()

        import asyncio

        asyncio.create_task(_do())
