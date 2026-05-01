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
        Binding("l", "next_tab", "Next tab", show=False),
        Binding("h", "prev_tab", "Prev tab", show=False),
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

    _TAB_ORDER = ["status", "agents", "cron", "config"]

    def action_next_tab(self) -> None:
        tc = self.query_one(TabbedContent)
        idx = self._TAB_ORDER.index(tc.active) if tc.active in self._TAB_ORDER else 0
        tc.active = self._TAB_ORDER[(idx + 1) % len(self._TAB_ORDER)]

    def action_prev_tab(self) -> None:
        tc = self.query_one(TabbedContent)
        idx = self._TAB_ORDER.index(tc.active) if tc.active in self._TAB_ORDER else 0
        tc.active = self._TAB_ORDER[(idx - 1) % len(self._TAB_ORDER)]

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Focus the list widget whenever a tab becomes active."""
        focus_map = {
            "--content-tab-agents": "#agents-list",
            "--content-tab-cron": "#cron-list",
            "--content-tab-config": "#config-list",
        }
        selector = focus_map.get(event.tab.id)
        if selector:
            try:
                self.query_one(selector).focus()
            except Exception:
                pass
