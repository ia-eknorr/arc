"""Tokens screen: codeburn usage per agent with bar charts."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from arc.agents import list_agents
from arc.config import load_config


def _cb_bin() -> list[str] | None:
    """Return codeburn command prefix, preferring global install over npx."""
    cb = shutil.which("codeburn")
    if cb:
        return [cb]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", "codeburn"]
    return None


async def _run_cb(cb: list[str], extra: list[str]) -> dict:
    """Run codeburn status --format json and return parsed result."""
    cmd = cb + ["status", "--format", "json", "--provider", "claude"] + extra
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return json.loads(stdout.decode())
    except Exception:
        return {"today": {"cost": 0.0, "calls": 0}, "month": {"cost": 0.0, "calls": 0}}


def _bar(value: float, max_val: float, width: int = 28) -> str:
    if max_val <= 0:
        return "░" * width
    filled = round((value / max_val) * width)
    return "█" * filled + "░" * (width - filled)


class TokensPane(Widget):
    """Tokens tab: codeburn usage as bar charts per agent."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    DEFAULT_CSS = """
    TokensPane {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    #tokens-body {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="tokens-body")

    def on_mount(self) -> None:
        self._load()

    def action_refresh(self) -> None:
        self._load()

    @work(exclusive=True)
    async def _load(self) -> None:
        cb = _cb_bin()
        if not cb:
            self.query_one("#tokens-body", Static).update(
                "[yellow]codeburn not found[/yellow]\n\n"
                "Install: [bold]npm install -g codeburn[/bold]"
            )
            return

        self.query_one("#tokens-body", Static).update("[dim]Loading...[/dim]")

        cfg = load_config()
        config_dir = Path(cfg.daemon.pid_file).expanduser().parent
        agents = list_agents(config_dir)

        coros = [_run_cb(cb, [])]
        for a in agents:
            coros.append(_run_cb(cb, ["--project", Path(a.workspace).name]))

        results = await asyncio.gather(*coros)
        self._render(results[0], list(zip(agents, results[1:])))

    def _render(self, g: dict, per_agent: list) -> None:
        cur = g.get("currency", "USD")
        today_cost = g.get("today", {}).get("cost", 0.0)
        today_calls = g.get("today", {}).get("calls", 0)
        month_cost = g.get("month", {}).get("cost", 0.0)

        lines: list[str] = [
            "[bold]TOKEN USAGE[/bold]  [dim]r: refresh[/dim]",
            "",
            f"  [bold cyan]TODAY[/bold cyan]   [green]${today_cost:>8.2f} {cur}[/green]"
            f"  [dim]{today_calls} calls[/dim]",
            f"  [bold cyan]MONTH[/bold cyan]   [cyan]${month_cost:>8.2f} {cur}[/cyan]",
            "",
        ]

        if not per_agent:
            lines.append("[dim]No agents configured.[/dim]")
            self.query_one("#tokens-body", Static).update("\n".join(lines))
            return

        name_w = max(len(a.name) for a, _ in per_agent)
        max_today = max((d.get("today", {}).get("cost", 0.0) for _, d in per_agent), default=0.0) or 0.01
        max_month = max((d.get("month", {}).get("cost", 0.0) for _, d in per_agent), default=0.0) or 0.01

        lines += ["  [bold]BY AGENT  (today)[/bold]", ""]
        for agent, d in per_agent:
            cost = d.get("today", {}).get("cost", 0.0)
            calls = d.get("today", {}).get("calls", 0)
            bar = _bar(cost, max_today)
            pct = cost / today_cost * 100 if today_cost > 0 else 0
            lines.append(
                f"  [cyan]{agent.name:<{name_w}}[/cyan]  "
                f"[green]{bar}[/green]  "
                f"[green]${cost:.2f}[/green]"
                f"  [dim]{pct:.0f}%  {calls} calls[/dim]"
            )

        lines += ["", "  [bold]BY AGENT  (month)[/bold]", ""]
        for agent, d in per_agent:
            cost = d.get("month", {}).get("cost", 0.0)
            calls = d.get("month", {}).get("calls", 0)
            bar = _bar(cost, max_month)
            pct = cost / month_cost * 100 if month_cost > 0 else 0
            lines.append(
                f"  [cyan]{agent.name:<{name_w}}[/cyan]  "
                f"[cyan]{bar}[/cyan]  "
                f"[cyan]${cost:.2f}[/cyan]"
                f"  [dim]{pct:.0f}%  {calls} calls[/dim]"
            )

        self.query_one("#tokens-body", Static).update("\n".join(lines))
