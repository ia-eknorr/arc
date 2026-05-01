from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from arc.cli import _next_fire_offline, _relative_time, app

runner = CliRunner()


# ---------------------------------------------------------------------------
# _relative_time
# ---------------------------------------------------------------------------


def test_relative_time_minutes() -> None:
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(minutes=14)).isoformat()
    assert "min" in _relative_time(future)


def test_relative_time_hours() -> None:
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)).isoformat()
    result = _relative_time(future)
    assert "h" in result and "m" in result


def test_relative_time_days_shows_date() -> None:
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    result = _relative_time(future)
    assert "-" in result  # date format: YYYY-MM-DD


def test_relative_time_under_one_minute() -> None:
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert _relative_time(future) == "in <1 min"


# ---------------------------------------------------------------------------
# _next_fire_offline
# ---------------------------------------------------------------------------


def test_next_fire_offline_valid_schedule() -> None:
    result = _next_fire_offline("0 7 * * *")
    assert result is not None
    assert "T" in result  # ISO format


def test_next_fire_offline_invalid_schedule() -> None:
    result = _next_fire_offline("not a cron expression")
    assert result is None


# ---------------------------------------------------------------------------
# arc status - daemon running
# ---------------------------------------------------------------------------

_DAEMON_RESPONSE = {
    "status": "ok",
    "daemon": {"pid": 12345, "socket": "~/.arc/arc.sock"},
    "agents": [
        {
            "name": "coach",
            "model": "claude-sonnet-4-6",
            "workspace": "/workspace/fitness-coach",
            "discord_channel": "9999",
        }
    ],
    "cron": [
        {
            "name": "weekly-plan",
            "schedule": "0 19 * * 0",
            "enabled": True,
            "next_run": None,
        }
    ],
}


def test_status_daemon_running_shows_pid(config_dir: Path) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=_DAEMON_RESPONSE):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "12345" in result.output
    assert "running" in result.output


def test_status_daemon_running_shows_agent(config_dir: Path) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=_DAEMON_RESPONSE):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "coach" in result.output
    assert "claude-sonnet-4-6" in result.output


def test_status_daemon_running_shows_cron(config_dir: Path) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=_DAEMON_RESPONSE):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "weekly-plan" in result.output


def test_status_shows_discord_channel(config_dir: Path) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=_DAEMON_RESPONSE):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "9999" in result.output


# ---------------------------------------------------------------------------
# arc status - daemon not running (offline fallback)
# ---------------------------------------------------------------------------


def test_status_offline_shows_not_running(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "not running" in result.output


def test_status_offline_shows_agents_from_config(
    config_dir: Path, workspace: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "coach" in result.output
    assert "claude-sonnet-4-6" in result.output


def test_status_offline_no_agents(config_dir: Path) -> None:
    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "none configured" in result.output


def test_status_offline_cron_computes_next_run(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    import yaml

    cron_dir = config_dir / "cron"
    cron_dir.mkdir(exist_ok=True)
    (cron_dir / "jobs.yaml").write_text(yaml.dump({
        "jobs": {
            "weekly-plan": {
                "schedule": "0 19 * * 0",
                "agent": "coach",
                "prompt": "plan",
                "enabled": True,
            }
        }
    }))

    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "weekly-plan" in result.output
    assert "next:" in result.output


def test_status_offline_disabled_cron_shows_disabled(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    import yaml

    cron_dir = config_dir / "cron"
    cron_dir.mkdir(exist_ok=True)
    (cron_dir / "jobs.yaml").write_text(yaml.dump({
        "jobs": {
            "heartbeat": {
                "schedule": "*/30 * * * *",
                "agent": "coach",
                "prompt": "check",
                "enabled": False,
            }
        }
    }))

    with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
        result = runner.invoke(app, ["status", "--config-dir", str(config_dir)])
    assert "disabled" in result.output
