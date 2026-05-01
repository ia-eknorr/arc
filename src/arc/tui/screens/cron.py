"""Cron screen: job list with enable/disable, run-now, and detail panel."""
from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from arc.config import load_config
from arc.cron import load_jobs
from arc.tui.screens.agents import ConfirmScreen, InputScreen
from arc.types import CronJob


def _jobs_file() -> Path:
    cfg = load_config()
    return Path(cfg.daemon.pid_file).expanduser().parent / "cron" / "jobs.yaml"


def _load_jobs_raw() -> dict:
    jf = _jobs_file()
    if not jf.exists():
        return {"jobs": {}}
    return yaml.safe_load(jf.read_text()) or {"jobs": {}}


def _save_jobs_raw(data: dict) -> None:
    jf = _jobs_file()
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _next_fire_str(schedule: str) -> str:
    from apscheduler.triggers.cron import CronTrigger
    try:
        trigger = CronTrigger.from_crontab(schedule)
        nrt = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        if not nrt:
            return "unknown"
        delta = int((nrt - datetime.now(timezone.utc)).total_seconds())
        if delta < 60:
            return "in <1 min"
        if delta < 3600:
            return f"in {delta // 60} min"
        h, m = divmod(delta // 60, 60)
        return f"in {h}h {m}m"
    except Exception:
        return "invalid schedule"


class CronDetail(Static):
    """Detail view for a single cron job."""

    def show(self, job: CronJob) -> None:
        next_str = _next_fire_str(job.schedule) if job.enabled else "--"
        lines = [f"[bold]{job.name}[/bold]", ""]
        if job.description:
            lines.append(f"  {job.description}")
            lines.append("")
        lines.append(f"  schedule:  {job.schedule}")
        lines.append(f"  agent:     {job.agent}")
        if job.model:
            lines.append(f"  model:     {job.model}")
        else:
            lines.append("  model:     (agent default)")
        if job.notify:
            lines.append(f"  notify:    {job.notify}")
        lines.append(f"  next run:  {next_str}")
        lines.append("")
        lines.append("  prompt:")
        for line in job.prompt.splitlines():
            lines.append(f"    {line}")
        lines.append("")
        lines.append("[dim]space: toggle  r: run now  e: open in editor  d: delete[/dim]")
        self.update("\n".join(lines))


class CronPane(Widget):
    """Cron tab: job list + detail panel."""

    BINDINGS = [
        Binding("space", "toggle_job", "Toggle"),
        Binding("r", "run_job", "Run now"),
        Binding("e", "edit_in_editor", "Editor"),
        Binding("n", "new_job", "New"),
        Binding("d", "delete_job", "Delete"),
    ]

    DEFAULT_CSS = """
    CronPane {
        height: 1fr;
    }
    #cron-list-pane {
        width: 40;
        border-right: solid $accent;
    }
    #cron-detail-pane {
        width: 1fr;
        padding: 1 2;
    }
    #cron-list {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="cron-list-pane"):
                yield Label("[bold]CRON JOBS[/bold]", classes="section-title")
                yield ListView(id="cron-list")
            with ScrollableContainer(id="cron-detail-pane"):
                yield CronDetail(id="cron-detail")

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        cfg = load_config()
        self._jobs = load_jobs(cfg)
        lv = self.query_one("#cron-list", ListView)
        lv.clear()
        for job in self._jobs:
            status = "on" if job.enabled else "[dim]off[/dim]"
            lv.append(ListItem(Label(f"{job.name}  [{status}]")))
        if self._jobs:
            self._show_detail(self._jobs[0])

    def _selected_job(self) -> CronJob | None:
        lv = self.query_one("#cron-list", ListView)
        idx = lv.index
        if idx is None or not self._jobs or idx >= len(self._jobs):
            return None
        return self._jobs[idx]

    def _show_detail(self, job: CronJob) -> None:
        self.query_one("#cron-detail", CronDetail).show(job)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        job = self._selected_job()
        if job:
            self._show_detail(job)

    def action_toggle_job(self) -> None:
        job = self._selected_job()
        if not job:
            return
        raw = _load_jobs_raw()
        jobs = raw.get("jobs") or {}
        if job.name in jobs:
            jobs[job.name]["enabled"] = not job.enabled
            _save_jobs_raw(raw)
            state = "enabled" if not job.enabled else "disabled"
            self.notify(f"'{job.name}' {state}. Restart daemon to apply.")
        self._refresh_list()

    def action_run_job(self) -> None:
        job = self._selected_job()
        if not job:
            return

        async def _do() -> None:
            from arc import ipc as _ipc
            cfg = load_config()
            self.notify(f"Running '{job.name}'...")
            response = await _ipc.request(cfg, {"op": "cron_run", "job": job.name})
            if response is None:
                self.notify("Daemon not running. Cannot run job.", severity="warning")
            elif response.get("status") == "error":
                self.notify(f"Error: {response['error']}", severity="error")
            else:
                self.notify(f"'{job.name}' completed.")

        asyncio.create_task(_do())

    def action_edit_in_editor(self) -> None:
        jf = _jobs_file()
        if not jf.exists():
            self.notify("No jobs file found.", severity="warning")
            return
        editor = os.environ.get("EDITOR", "vi")
        with self.app.suspend():
            subprocess.run([editor, str(jf)])
        self._refresh_list()

    def action_new_job(self) -> None:
        async def _do() -> None:
            name = await self.app.push_screen_wait(InputScreen("Job name:", ""))
            if not name:
                return
            schedule = await self.app.push_screen_wait(InputScreen("Schedule (cron):", "0 9 * * *"))
            if not schedule:
                return
            agent = await self.app.push_screen_wait(InputScreen("Agent:", ""))
            if not agent:
                return
            prompt = await self.app.push_screen_wait(InputScreen("Prompt:", ""))
            if not prompt:
                return

            raw = _load_jobs_raw()
            raw.setdefault("jobs", {})
            if name in raw["jobs"]:
                self.notify(f"Job '{name}' already exists.", severity="error")
                return

            raw["jobs"][name] = {
                "schedule": schedule,
                "agent": agent,
                "prompt": prompt,
                "enabled": True,
            }
            _save_jobs_raw(raw)
            self._refresh_list()
            self.notify(f"Job '{name}' added. Restart daemon to schedule it.")

        asyncio.create_task(_do())

    def action_delete_job(self) -> None:
        job = self._selected_job()
        if not job:
            return

        async def _do() -> None:
            confirmed = await self.app.push_screen_wait(
                ConfirmScreen(f"Delete job '{job.name}'?")
            )
            if confirmed:
                raw = _load_jobs_raw()
                raw.get("jobs", {}).pop(job.name, None)
                _save_jobs_raw(raw)
                self._refresh_list()
                self.notify(f"Deleted '{job.name}'.")

        asyncio.create_task(_do())
