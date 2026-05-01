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
        Binding("h", "app.prev_tab", "Prev tab", show=False),
        Binding("l", "app.next_tab", "Next tab", show=False),
    ]
