"""Cron job scheduling for arc daemon."""
import logging
from pathlib import Path
from typing import Awaitable, Callable

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from arc.config import ArcConfig
from arc.types import CronJob

log = logging.getLogger("arc.cron")


def _jobs_file(config: ArcConfig) -> Path:
    config_dir = Path(config.daemon.pid_file).expanduser().parent
    return config_dir / "cron" / "jobs.yaml"


def load_jobs(config: ArcConfig) -> list[CronJob]:
    """Load cron jobs from the cron/jobs.yaml config file."""
    path = _jobs_file(config)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    jobs = []
    for name, d in (data.get("jobs") or {}).items():
        jobs.append(CronJob(
            name=name,
            description=d.get("description", ""),
            schedule=d["schedule"],
            agent=d.get("agent"),
            prompt=d.get("prompt"),
            command=d.get("command"),
            model=d.get("model"),
            notify=d.get("notify"),
            enabled=d.get("enabled", True),
            pre_check=d.get("pre_check"),
        ))
    return jobs


def set_job_enabled(config: ArcConfig, job_name: str, enabled: bool) -> bool:
    """Toggle a job's enabled flag in jobs.yaml. Returns False if job not found."""
    path = _jobs_file(config)
    if not path.exists():
        return False
    data = yaml.safe_load(path.read_text()) or {}
    jobs = data.get("jobs") or {}
    if job_name not in jobs:
        return False
    jobs[job_name]["enabled"] = enabled
    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    return True


class CronManager:
    def __init__(self, config: ArcConfig) -> None:
        self.config = config
        self._scheduler = AsyncIOScheduler()
        self._jobs: list[CronJob] = []

    def start(self, run_job_fn: Callable[[CronJob], Awaitable[None]]) -> None:
        """Load jobs from config and start the scheduler."""
        self._jobs = load_jobs(self.config)
        enabled = 0
        for job in self._jobs:
            if job.enabled:
                self._scheduler.add_job(
                    run_job_fn,
                    CronTrigger.from_crontab(job.schedule),
                    args=[job],
                    id=job.name,
                    name=job.name,
                )
                enabled += 1
                log.info(f"cron: scheduled {job.name!r} ({job.schedule})")
        self._scheduler.start()
        log.info(f"cron: scheduler started ({enabled} active jobs)")

    def stop(self) -> None:
        """Shut down the scheduler without waiting for running jobs."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def get_jobs(self) -> list[CronJob]:
        """Return all loaded jobs (enabled and disabled)."""
        return list(self._jobs)

    def next_run_times(self) -> dict[str, str | None]:
        """Return ISO next-run timestamp for each enabled job, None if not scheduled."""
        result: dict[str, str | None] = {}
        for job in self._jobs:
            if not job.enabled:
                result[job.name] = None
                continue
            apj = self._scheduler.get_job(job.name)
            if apj and apj.next_run_time:
                result[job.name] = apj.next_run_time.isoformat()
            else:
                result[job.name] = None
        return result
