"""Logs screen: routing and cron JSONL viewer."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, Static

from arc.config import load_config
from arc.tui.widgets.vim_list import VimListView


def _fmt_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _load_jsonl(path: Path, last: int = 60) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
        entries = []
        for line in lines[-last:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return list(reversed(entries))
    except Exception:
        return []


class LogDetail(Static):
    """Detail panel for a single log entry."""

    def show_routing(self, e: dict) -> None:
        ts = _fmt_ts(e.get("timestamp", ""))
        lines = [
            f"[bold cyan]routing[/bold cyan]  [dim]{ts}[/dim]",
            "",
            f"  [dim]agent:[/dim]          {e.get('agent', '')}",
            f"  [dim]model:[/dim]          {e.get('model', '')}",
            f"  [dim]dispatch_type:[/dim]  {e.get('dispatch_type', '')}",
            f"  [dim]source:[/dim]         {e.get('source', '')}",
            f"  [dim]one_shot:[/dim]       {e.get('one_shot', '')}",
            "",
            "  [dim]prompt:[/dim]",
        ]
        for chunk in (e.get("prompt_preview") or "").splitlines():
            lines.append(f"    {chunk}")
        self.update("\n".join(lines))

    def show_cron(self, e: dict) -> None:
        ts = _fmt_ts(e.get("timestamp", ""))
        status = e.get("status", "")
        color = "green" if status == "ok" else "red"
        lines = [
            f"[bold cyan]cron[/bold cyan]  [dim]{ts}[/dim]",
            "",
            f"  [dim]job:[/dim]     {e.get('job', '')}",
            f"  [dim]status:[/dim]  [{color}]{status}[/{color}]",
            "",
            "  [dim]output:[/dim]",
        ]
        for chunk in (e.get("output_preview") or "").splitlines():
            lines.append(f"    {chunk}")
        self.update("\n".join(lines))

    def empty(self) -> None:
        self.update("[dim]Select an entry to view details.[/dim]")


class LogsPane(Widget):
    """Logs tab: routing and cron JSONL viewer with list/detail split."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_routing", "Routing"),
        Binding("2", "show_cron", "Cron"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    DEFAULT_CSS = """
    LogsPane {
        height: 1fr;
    }
    #logs-split {
        height: 1fr;
    }
    #logs-list-pane {
        width: 36;
        border-right: solid $accent;
    }
    #logs-list-label {
        padding: 0 1;
        background: $surface;
        color: $accent;
        text-style: bold;
    }
    #logs-detail-pane {
        width: 1fr;
        padding: 1 2;
    }
    VimListView {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode: str = "routing"
        self._entries: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="logs-split"):
            with Vertical(id="logs-list-pane"):
                yield Label("", id="logs-list-label")
                yield VimListView(id="logs-list")
            with ScrollableContainer(id="logs-detail-pane"):
                yield LogDetail(id="logs-detail")

    def on_mount(self) -> None:
        self._refresh()

    def action_cursor_down(self) -> None:
        self.query_one("#logs-list", VimListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#logs-list", VimListView).action_cursor_up()

    def action_scroll_home(self) -> None:
        self.query_one("#logs-list", VimListView).action_scroll_home()

    def action_scroll_end(self) -> None:
        self.query_one("#logs-list", VimListView).action_scroll_end()

    def action_refresh(self) -> None:
        self._refresh()

    def action_show_routing(self) -> None:
        self._mode = "routing"
        self._refresh()

    def action_show_cron(self) -> None:
        self._mode = "cron"
        self._refresh()

    def _log_path(self) -> Path:
        cfg = load_config()
        log_dir = Path(cfg.daemon.pid_file).expanduser().parent / "logs"
        return log_dir / f"{self._mode}.jsonl"

    def _refresh(self) -> None:
        self._entries = _load_jsonl(self._log_path())
        lv = self.query_one("#logs-list", VimListView)
        lv.clear()

        mode_label = "ROUTING" if self._mode == "routing" else "CRON"
        self.query_one("#logs-list-label", Label).update(
            f" {mode_label}  1: routing  2: cron  r: refresh"
        )

        if not self._entries:
            self.query_one("#logs-detail", LogDetail).empty()
            return

        for e in self._entries:
            ts = _fmt_ts(e.get("timestamp", ""))
            if self._mode == "routing":
                agent = e.get("agent", "?")
                src = e.get("source", "")
                lv.append(ListItem(Label(f"[dim]{ts}[/dim]  [cyan]{agent}[/cyan]  [dim]{src}[/dim]")))
            else:
                job = e.get("job", "?")
                status = e.get("status", "")
                color = "green" if status == "ok" else "red"
                lv.append(ListItem(Label(f"[dim]{ts}[/dim]  [cyan]{job}[/cyan]  [{color}]{status}[/{color}]")))

        # Show first entry detail immediately; on_list_view_highlighted handles subsequent navigation
        detail = self.query_one("#logs-detail", LogDetail)
        e = self._entries[0]
        if self._mode == "routing":
            detail.show_routing(e)
        else:
            detail.show_cron(e)

    def _show_detail(self) -> None:
        lv = self.query_one("#logs-list", VimListView)
        idx = lv.index
        detail = self.query_one("#logs-detail", LogDetail)
        if idx is None or not self._entries or idx >= len(self._entries):
            detail.empty()
            return
        e = self._entries[idx]
        if self._mode == "routing":
            detail.show_routing(e)
        else:
            detail.show_cron(e)

    def on_list_view_highlighted(self, _event: VimListView.Highlighted) -> None:
        self._show_detail()
