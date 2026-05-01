"""Agents screen: list + detail panel with inline editing."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, ListItem, Select, Static

from arc.agents import list_agents
from arc.config import load_config
from arc.tui.widgets.vim_list import VimListView


def _agents_dir() -> Path:
    cfg = load_config()
    return Path(cfg.daemon.pid_file).expanduser().parent / "agents"


def _load_raw(name: str) -> dict:
    path = _agents_dir() / f"{name}.yaml"
    return yaml.safe_load(path.read_text()) or {}


def _save_raw(name: str, data: dict) -> None:
    path = _agents_dir() / f"{name}.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


class ConfirmScreen(ModalScreen[bool]):
    """Generic yes/no confirmation modal."""

    BINDINGS = [("escape", "dismiss_no", "Cancel")]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-box {
        width: 50;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    #confirm-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self._message)
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", id="yes", variant="error")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_dismiss_no(self) -> None:
        self.dismiss(False)


class InputScreen(ModalScreen[str | None]):
    """Single-field text input modal."""

    BINDINGS = [("escape", "dismiss_none", "Cancel")]

    DEFAULT_CSS = """
    InputScreen {
        align: center middle;
    }
    #input-box {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    Input {
        margin-top: 1;
    }
    #input-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, prompt: str, default: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Label(self._prompt)
            yield Input(value=self._default, id="input-field")
            with Horizontal(id="input-buttons"):
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#input-field", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            val = self.query_one("#input-field", Input).value.strip()
            self.dismiss(val if val else None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class ModelPickScreen(ModalScreen[str | None]):
    """Pick a model from allowed_models list."""

    BINDINGS = [("escape", "dismiss_none", "Cancel")]

    DEFAULT_CSS = """
    ModelPickScreen {
        align: center middle;
    }
    #model-box {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    Select {
        margin-top: 1;
    }
    #model-buttons {
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, allowed: list[str], current: str) -> None:
        super().__init__()
        self._allowed = allowed
        self._current = current

    def compose(self) -> ComposeResult:
        options = [(m, m) for m in self._allowed]
        with Vertical(id="model-box"):
            yield Label("Select model:")
            yield Select(options, value=self._current, id="model-select")
            with Horizontal(id="model-buttons"):
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            sel = self.query_one("#model-select", Select)
            self.dismiss(str(sel.value) if sel.value is not Select.BLANK else None)
        else:
            self.dismiss(None)

    def action_dismiss_none(self) -> None:
        self.dismiss(None)


class AgentDetail(Static):
    """Read-only detail view for a single agent."""

    def show(self, name: str) -> None:
        try:
            data = _load_raw(name)
        except Exception as e:
            self.update(f"[red]Error loading {name}: {e}[/red]")
            return

        lines = [f"[bold cyan]{name}[/bold cyan]", ""]
        lines.append(f"  [dim]description:[/dim]      {data.get('description', '')}")
        lines.append(f"  [dim]workspace:[/dim]         {data.get('workspace', '')}")
        lines.append(f"  [dim]model:[/dim]             {data.get('model', '')}")

        allowed = data.get("allowed_models", [])
        if allowed:
            lines.append("  [dim]allowed_models:[/dim]")
            for m in allowed:
                lines.append(f"    {m}")

        lines.append(f"  [dim]permission_mode:[/dim]   {data.get('permission_mode', '')}")

        spf = data.get("system_prompt_files", [])
        if spf:
            lines.append("  [dim]system_prompt_files:[/dim]")
            for f in spf:
                lines.append(f"    {f}")

        ch = data.get("discord", {}).get("channel_id", "")
        if ch:
            lines.append(f"  [dim]discord channel:[/dim]   {ch}")

        lines.append("")
        lines.append(
            "[dim]c: change model  e: open in editor  "
            "d: delete  h: back to list[/dim]"
        )
        self.update("\n".join(lines))


class AgentsPane(Widget):
    """Agents tab: list on left, detail on right."""

    BINDINGS = [
        Binding("n", "new_agent", "New"),
        Binding("d", "delete_agent", "Delete"),
        Binding("e", "edit_in_editor", "Editor"),
        Binding("c", "change_model", "Change model"),
        Binding("l", "focus_detail", "Detail", show=False),
        Binding("h", "focus_list", "List", show=False),
        Binding("enter", "focus_detail", "Detail", show=False),
    ]

    DEFAULT_CSS = """
    AgentsPane {
        height: 1fr;
    }
    #agents-split {
        height: 1fr;
    }
    #agents-list-pane {
        width: 28;
        border-right: solid $accent;
    }
    #agents-list-label {
        padding: 0 1;
        background: $surface;
        color: $accent;
        text-style: bold;
    }
    #agents-detail-pane {
        width: 1fr;
        padding: 1 2;
    }
    VimListView {
        height: 1fr;
    }
    ListItem {
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="agents-split"):
            with Vertical(id="agents-list-pane"):
                yield Label(" AGENTS  j/k: nav  l: detail", id="agents-list-label")
                yield VimListView(id="agents-list")
            with ScrollableContainer(id="agents-detail-pane"):
                yield AgentDetail(id="agents-detail")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        cfg = load_config()
        config_dir = Path(cfg.daemon.pid_file).expanduser().parent
        lv = self.query_one("#agents-list", VimListView)
        lv.clear()
        self._agents = list_agents(config_dir)
        for a in self._agents:
            lv.append(ListItem(Label(a.name)))
        if self._agents:
            self._show_detail(self._agents[0].name)
        else:
            self.query_one("#agents-detail", AgentDetail).update(
                "[dim]No agents configured.\n\nn: create your first agent[/dim]"
            )

    def _selected_name(self) -> str | None:
        lv = self.query_one("#agents-list", VimListView)
        idx = lv.index
        if idx is None or not self._agents or idx >= len(self._agents):
            return None
        return self._agents[idx].name

    def _show_detail(self, name: str) -> None:
        self.query_one("#agents-detail", AgentDetail).show(name)

    def on_list_view_highlighted(self, event: VimListView.Highlighted) -> None:
        lv = self.query_one("#agents-list", VimListView)
        idx = lv.index
        if idx is not None and self._agents and idx < len(self._agents):
            self._show_detail(self._agents[idx].name)

    def action_focus_detail(self) -> None:
        self.query_one("#agents-detail-pane").focus()

    def action_focus_list(self) -> None:
        self.query_one("#agents-list", VimListView).focus()

    def action_new_agent(self) -> None:
        async def _do() -> None:
            name = await self.app.push_screen_wait(InputScreen("Agent name:", ""))
            if not name:
                return
            workspace = await self.app.push_screen_wait(InputScreen("Workspace path:", ""))
            if not workspace:
                return
            model = await self.app.push_screen_wait(
                InputScreen("Model:", "claude-sonnet-4-6")
            )
            if not model:
                return

            dest = _agents_dir() / f"{name}.yaml"
            if dest.exists():
                self.notify(f"Agent '{name}' already exists.", severity="error")
                return

            data: dict = {
                "name": name,
                "description": "",
                "workspace": workspace,
                "system_prompt_files": ["AGENTS.md", "IDENTITY.md", "SOUL.md", "USER.md"],
                "model": model,
                "allowed_models": [model],
                "permission_mode": "approve-all",
                "discord": {},
            }
            _save_raw(name, data)
            self._refresh_list()
            self.notify(f"Agent '{name}' created.")

        import asyncio

        asyncio.create_task(_do())

    def action_delete_agent(self) -> None:
        name = self._selected_name()
        if not name:
            return

        async def _do() -> None:
            confirmed = await self.app.push_screen_wait(
                ConfirmScreen(f"Delete agent '{name}'?")
            )
            if confirmed:
                path = _agents_dir() / f"{name}.yaml"
                path.unlink(missing_ok=True)
                self._refresh_list()
                self.notify(f"Deleted '{name}'.")

        import asyncio

        asyncio.create_task(_do())

    def action_edit_in_editor(self) -> None:
        name = self._selected_name()
        if not name:
            return
        path = _agents_dir() / f"{name}.yaml"
        editor = os.environ.get("EDITOR", "vi")
        with self.app.suspend():
            subprocess.run([editor, str(path)])
        self._refresh_list()

    def action_change_model(self) -> None:
        name = self._selected_name()
        if not name:
            return
        data = _load_raw(name)
        allowed = data.get("allowed_models", [data.get("model", "")])
        current = data.get("model", "")

        async def _do() -> None:
            model = await self.app.push_screen_wait(ModelPickScreen(allowed, current))
            if model and model != current:
                data["model"] = model
                _save_raw(name, data)
                self._show_detail(name)
                self.notify(f"Model updated to {model}.")

        import asyncio

        asyncio.create_task(_do())
