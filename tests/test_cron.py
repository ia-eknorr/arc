from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from arc.config import ArcConfig, DaemonConfig, GitConfig, LoggingConfig
from arc.cron import CronManager, load_jobs, set_job_enabled


@pytest.fixture
def cron_config(tmp_path: Path) -> ArcConfig:
    cfg = ArcConfig()
    cfg.daemon = DaemonConfig(
        pid_file=str(tmp_path / "daemon.pid"),
        socket_path=str(tmp_path / "arc.sock"),
        log_level="warning",
    )
    cfg.git = GitConfig(auto_pull=False)
    cfg.logging = LoggingConfig(log_routing=False)
    return cfg


@pytest.fixture
def jobs_file(cron_config: ArcConfig) -> Path:
    cron_dir = Path(cron_config.daemon.pid_file).parent / "cron"
    cron_dir.mkdir(parents=True)
    jobs_path = cron_dir / "jobs.yaml"
    jobs_path.write_text(yaml.dump({
        "jobs": {
            "daily-workout": {
                "description": "Morning briefing",
                "schedule": "0 7 * * *",
                "agent": "coach",
                "prompt": "Deliver today's workout.",
                "notify": "discord",
                "enabled": True,
            },
            "heartbeat": {
                "schedule": "*/30 * * * *",
                "agent": "coach",
                "model": "haiku",
                "prompt": "Read HEARTBEAT.md.",
                "notify": "discord_on_urgent",
                "enabled": True,
            },
            "weekly-plan": {
                "schedule": "0 19 * * 0",
                "agent": "coach",
                "prompt": "Generate weekly plan.",
                "notify": "discord",
                "enabled": False,
            },
        }
    }))
    return jobs_path


# --- load_jobs ---


def test_load_jobs_empty_when_no_file(cron_config: ArcConfig) -> None:
    assert load_jobs(cron_config) == []


def test_load_jobs_parses_all(cron_config: ArcConfig, jobs_file: Path) -> None:
    jobs = load_jobs(cron_config)
    assert len(jobs) == 3
    names = {j.name for j in jobs}
    assert names == {"daily-workout", "heartbeat", "weekly-plan"}


def test_load_jobs_fields(cron_config: ArcConfig, jobs_file: Path) -> None:
    jobs = {j.name: j for j in load_jobs(cron_config)}
    hb = jobs["heartbeat"]
    assert hb.model == "haiku"
    assert hb.notify == "discord_on_urgent"
    assert hb.enabled is True

    wp = jobs["weekly-plan"]
    assert wp.enabled is False
    assert wp.model is None


def test_load_jobs_description_optional(cron_config: ArcConfig, jobs_file: Path) -> None:
    jobs = {j.name: j for j in load_jobs(cron_config)}
    assert jobs["heartbeat"].description == ""
    assert jobs["daily-workout"].description == "Morning briefing"


# --- set_job_enabled ---


def test_set_job_enabled_disables(cron_config: ArcConfig, jobs_file: Path) -> None:
    assert set_job_enabled(cron_config, "daily-workout", False) is True
    jobs = {j.name: j for j in load_jobs(cron_config)}
    assert jobs["daily-workout"].enabled is False


def test_set_job_enabled_enables(cron_config: ArcConfig, jobs_file: Path) -> None:
    assert set_job_enabled(cron_config, "weekly-plan", True) is True
    jobs = {j.name: j for j in load_jobs(cron_config)}
    assert jobs["weekly-plan"].enabled is True


def test_set_job_enabled_missing_job(cron_config: ArcConfig, jobs_file: Path) -> None:
    assert set_job_enabled(cron_config, "ghost-job", True) is False


def test_set_job_enabled_no_file(cron_config: ArcConfig) -> None:
    assert set_job_enabled(cron_config, "anything", True) is False


# --- CronManager ---


def test_cron_manager_schedules_enabled_jobs(cron_config: ArcConfig, jobs_file: Path) -> None:
    manager = CronManager(cron_config)
    mock_scheduler = MagicMock()
    manager._scheduler = mock_scheduler

    run_fn = AsyncMock()
    manager.start(run_fn)

    # daily-workout and heartbeat are enabled; weekly-plan is disabled
    assert mock_scheduler.add_job.call_count == 2
    scheduled_ids = {
        call.kwargs.get("id") or call.args[2] for call in mock_scheduler.add_job.call_args_list
    }
    assert "daily-workout" in scheduled_ids
    assert "heartbeat" in scheduled_ids
    assert "weekly-plan" not in scheduled_ids
    mock_scheduler.start.assert_called_once()


def test_cron_manager_get_jobs(cron_config: ArcConfig, jobs_file: Path) -> None:
    manager = CronManager(cron_config)
    manager._scheduler = MagicMock()
    manager.start(AsyncMock())
    assert len(manager.get_jobs()) == 3


def test_cron_manager_stop_shuts_down(cron_config: ArcConfig) -> None:
    manager = CronManager(cron_config)
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    manager._scheduler = mock_scheduler
    manager.stop()
    mock_scheduler.shutdown.assert_called_once_with(wait=False)


def test_cron_manager_stop_noop_when_not_running(cron_config: ArcConfig) -> None:
    manager = CronManager(cron_config)
    mock_scheduler = MagicMock()
    mock_scheduler.running = False
    manager._scheduler = mock_scheduler
    manager.stop()
    mock_scheduler.shutdown.assert_not_called()


def test_cron_manager_empty_jobs_file(cron_config: ArcConfig) -> None:
    manager = CronManager(cron_config)
    mock_scheduler = MagicMock()
    manager._scheduler = mock_scheduler
    manager.start(AsyncMock())
    mock_scheduler.add_job.assert_not_called()
