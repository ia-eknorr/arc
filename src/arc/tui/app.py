"""ArcTUI -- k9s-style management interface for arc."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, TabbedContent, TabPane

from arc.tui.screens.agents import AgentsPane
from arc.tui.screens.config import ConfigPane
from arc.tui.screens.cron import CronPane
from arc.tui.screens.status import StatusPane


class ArcTUI(App[None]):
    """arc management TUI."""

    TITLE = "arc"
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
    ]

    DEFAULT_CSS = """
    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    .section-title {
        color: $accent;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }

    .dim {
        color: $text-muted;
    }

    .ok {
        color: $success;
    }

    .error {
        color: $error;
    }

    .warning {
        color: $warning;
    }
    """

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="status"):
            with TabPane("Status", id="status"):
                yield StatusPane(id="status-pane")
            with TabPane("Agents", id="agents"):
                yield AgentsPane(id="agents-pane")
            with TabPane("Cron", id="cron"):
                yield CronPane(id="cron-pane")
            with TabPane("Config", id="config"):
                yield ConfigPane(id="config-pane")
        yield Footer()
