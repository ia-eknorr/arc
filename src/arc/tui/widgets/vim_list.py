"""ListView subclass with vim/k9s-style keybindings (j/k/g/G)."""
from __future__ import annotations

from textual.binding import Binding
from textual.widgets import ListView


class VimListView(ListView):
    """ListView with j/k/g/G navigation."""

    BINDINGS = [
        *ListView.BINDINGS,
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    def action_cursor_down(self) -> None:
        if not self._nodes:
            return
        if self.index is None:
            self.index = 0
        else:
            self.index = min(self.index + 1, len(self._nodes) - 1)

    def action_cursor_up(self) -> None:
        if self.index is None:
            return
        self.index = max(0, self.index - 1)
