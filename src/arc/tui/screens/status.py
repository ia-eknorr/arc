"""Status screen: daemon state, agents, and cron at a glance."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from arc.config import load_config
from arc.utils import is_process_running, read_pid


def _relative_time(iso: str) -> str:
    now = datetime.now(timezone.utc)
    then = datetime.fromisoformat(iso)
    delta = int((then - now).total_seconds())
    if delta < 60:
        return "in <1 min"
    if delta < 3600:
        return f"in {delta // 60} min"
    if delta < 86400:
        h, m = divmod(delta // 60, 60)
        return f"in {h}h {m}m"
    return then.strftime("%a %Y-%m-%d %H:%M")


def _next_fire_offline(schedule: str) -> str | None:
    from apscheduler.triggers.cron import CronTrigger
    try:
        trigger = CronTrigger.from_crontab(schedule)
        nrt = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        return nrt.isoformat() if nrt else None
    except Exception:
        return None


async def _fetch_status(cfg) -> dict:
    """Try daemon IPC first; fall back to config files."""
    from arc import ipc as _ipc
    response = await _ipc.request(cfg, {"op": "status", "source": "tui"})
    if response and response.get("status") == "ok":
        return {"daemon_running": True, **response}

    # Offline fallback
    from arc.agents import list_agents
    from arc.cron import load_jobs

    agents = [
        {
            "name": a.name,
            "model": a.model,
            "workspace": a.workspace,
            "discord_channel": a.discord.get("channel_id"),
        }
        for a in list_agents()
    ]
    cron = [
        {
            "name": j.name,
            "schedule": j.schedule,
            "enabled": j.enabled,
            "next_run": _next_fire_offline(j.schedule) if j.enabled else None,
        }
        for j in load_jobs(cfg)
    ]
    return {
        "daemon_running": False,
        "agents": agents,
        "cron": cron,
    }


class StatusPane(Widget):
    """Full status view: daemon, agents, cron."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("s", "toggle_daemon", "Start/Stop"),
    ]

    _data: reactive[dict] = reactive({})

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="status-content")

    def on_mount(self) -> None:
        self.set_interval(5, self._load)
        self._load()

    def _load(self) -> None:
        asyncio.create_task(self._fetch())

    async def _fetch(self) -> None:
        cfg = load_config()
        data = await _fetch_status(cfg)
        self._data = data
        self._render(data)

    def _render(self, data: dict) -> None:
        lines: list[str] = []

        if data.get("daemon_running"):
            d = data.get("daemon", {})
            pid = d.get("pid", "?")
            sock = d.get("socket", "?")
            lines.append(f"[green]daemon[/green]   running  pid={pid}  socket={sock}")
        else:
            lines.append("[red]daemon[/red]   not running  (press [bold]s[/bold] to start)")

        agents = data.get("agents", [])
        if agents:
            lines.append("")
            lines.append("[bold]AGENTS[/bold]")
            col = max(len(a["name"]) for a in agents)
            for a in agents:
                ch = f"  discord {a['discord_channel']}" if a.get("discord_channel") else ""
                lines.append(f"  {a['name']:<{col}}  {a['model']}  {a['workspace']}{ch}")
        else:
            lines.append("\n[dim]no agents configured[/dim]")

        cron = data.get("cron", [])
        if cron:
            lines.append("")
            lines.append("[bold]CRON[/bold]")
            col = max(len(j["name"]) for j in cron)
            for j in cron:
                if not j["enabled"]:
                    nxt = "--"
                elif j.get("next_run"):
                    nxt = _relative_time(j["next_run"])
                else:
                    nxt = "unknown"
                status = "enabled" if j["enabled"] else "[dim]disabled[/dim]"
                lines.append(f"  {j['name']:<{col}}  next: {nxt:<14}  {status}")

        self.query_one("#status-content", Static).update("\n".join(lines))

    def action_refresh(self) -> None:
        """Manual refresh."""
        self._load()

    def action_toggle_daemon(self) -> None:
        """Start or stop the daemon depending on current state."""
        cfg = load_config()
        pid = read_pid(cfg.daemon.pid_file)
        running = pid is not None and is_process_running(pid)

        import shutil
        import sys
        arc_bin = shutil.which("arc") or sys.argv[0]

        if running:
            subprocess.Popen([arc_bin, "daemon", "stop"])
        else:
            subprocess.Popen(
                [arc_bin, "daemon", "start", "--foreground"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        # Refresh after a short delay to let daemon start/stop
        self.set_timer(1.5, self._load)
