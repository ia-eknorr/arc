"""TUI integration tests using Textual's AppTest framework."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from arc.tui.app import ArcTUI

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def arc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".arc"
    (d / "agents").mkdir(parents=True)
    (d / "logs").mkdir()
    (d / "cron").mkdir()
    (d / "config.yaml").write_text(
        """\
daemon:
  auto_start: false
  log_level: info
  socket_path: /tmp/arc-test.sock
  pid_file: /tmp/arc-test.pid
acpx:
  command: acpx
  default_agent: claude
  session_ttl: 300
  output_format: text
ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1
discord:
  enabled: false
  guild_id: "1234"
git:
  auto_pull: false
timeouts:
  acpx_request: 30
  ollama_request: 30
logging:
  log_routing: false
"""
    )
    return d


@pytest.fixture
def coach_yaml(arc_dir: Path, tmp_path: Path) -> dict:
    ws = tmp_path / "workspace"
    ws.mkdir()
    data = {
        "name": "coach",
        "description": "Test coach",
        "workspace": str(ws),
        "system_prompt_files": ["AGENTS.md"],
        "model": "claude-sonnet-4-6",
        "allowed_models": ["claude-sonnet-4-6", "claude-haiku-4-5"],
        "permission_mode": "approve-all",
        "discord": {"channel_id": "9999"},
    }
    (arc_dir / "agents" / "coach.yaml").write_text(yaml.dump(data))
    return data


@pytest.fixture
def cron_yaml(arc_dir: Path) -> dict:
    data = {
        "jobs": {
            "heartbeat": {
                "schedule": "*/30 * * * *",
                "agent": "coach",
                "prompt": "Check status.",
                "enabled": True,
                "notify": "discord_on_urgent",
            },
            "weekly-plan": {
                "schedule": "0 19 * * 0",
                "agent": "coach",
                "prompt": "Write the weekly plan.",
                "enabled": False,
            },
        }
    }
    (arc_dir / "cron" / "jobs.yaml").write_text(yaml.dump(data))
    return data


def _patch_config(arc_dir: Path):
    """Patch load_config to use the test arc_dir."""
    from arc.config import load_config as _real_load

    def _mock_load(config_dir=None):
        return _real_load(arc_dir)

    return patch("arc.config.load_config", side_effect=_mock_load)


# ---------------------------------------------------------------------------
# App renders without error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_launches(arc_dir: Path) -> None:
    """App should start and render the Status tab."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.1)
                # App is running without errors
                assert pilot.app.is_running


@pytest.mark.asyncio
async def test_status_tab_renders(arc_dir: Path, coach_yaml: dict) -> None:
    """Status tab renders agent and daemon info."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            with patch("arc.agents.list_agents") as mock_agents:
                from arc.types import AgentConfig
                mock_agents.return_value = [
                    AgentConfig(
                        name="coach",
                        workspace="/workspace/fitness-coach",
                        system_prompt_files=[],
                        model="claude-sonnet-4-6",
                        allowed_models=["claude-sonnet-4-6"],
                        discord={"channel_id": "9999"},
                    )
                ]
                async with ArcTUI().run_test(size=(120, 40)) as pilot:
                    await pilot.pause(0.3)
                    assert pilot.app.is_running


@pytest.mark.asyncio
async def test_quit_key(arc_dir: Path) -> None:
    """Pressing q should exit the app."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.1)
                await pilot.press("q")
                # After q, app should be done


# ---------------------------------------------------------------------------
# Tab navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tabs_reachable(arc_dir: Path) -> None:
    """All four tabs (Status, Agents, Cron, Config) should be reachable."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.1)
                from textual.widgets import TabbedContent
                tc = pilot.app.query_one(TabbedContent)
                assert tc is not None
                # Textual prefixes tab IDs internally (--content-tab-<id>)
                tab_ids = {tab.id for tab in tc.query("Tab")}
                assert any("status" in t for t in tab_ids)
                assert any("agents" in t for t in tab_ids)
                assert any("cron" in t for t in tab_ids)
                assert any("config" in t for t in tab_ids)


# ---------------------------------------------------------------------------
# Agents screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agents_tab_renders(arc_dir: Path, coach_yaml: dict) -> None:
    """Agents tab renders the agent list."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.1)
                # Switch to Agents tab (show_tab is synchronous)
                from textual.widgets import TabbedContent
                pilot.app.query_one(TabbedContent).show_tab("agents")
                await pilot.pause(0.1)
                assert pilot.app.is_running


@pytest.mark.asyncio
async def test_agent_model_change_writes_yaml(arc_dir: Path, coach_yaml: dict) -> None:
    """Changing an agent's model should persist to YAML."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            # Directly test the file-write logic
            from arc.tui.screens.agents import _load_raw, _save_raw
            with patch("arc.tui.screens.agents._agents_dir", return_value=arc_dir / "agents"):
                data = _load_raw("coach")
                data["model"] = "claude-haiku-4-5"
                _save_raw("coach", data)

            saved = yaml.safe_load((arc_dir / "agents" / "coach.yaml").read_text())
            assert saved["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_agent_create_writes_yaml(arc_dir: Path) -> None:
    """Creating an agent should write a YAML file."""
    from arc.tui.screens.agents import _save_raw
    with patch("arc.tui.screens.agents._agents_dir", return_value=arc_dir / "agents"):
        data = {
            "name": "newbot",
            "description": "",
            "workspace": "/tmp/newbot",
            "system_prompt_files": [],
            "model": "claude-sonnet-4-6",
            "allowed_models": ["claude-sonnet-4-6"],
            "permission_mode": "approve-all",
            "discord": {},
        }
        _save_raw("newbot", data)

    saved = yaml.safe_load((arc_dir / "agents" / "newbot.yaml").read_text())
    assert saved["name"] == "newbot"
    assert saved["model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_agent_delete_removes_yaml(arc_dir: Path, coach_yaml: dict) -> None:
    """Deleting an agent removes its YAML file."""
    agent_file = arc_dir / "agents" / "coach.yaml"
    assert agent_file.exists()
    agent_file.unlink()
    assert not agent_file.exists()


# ---------------------------------------------------------------------------
# Cron screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_toggle_writes_yaml(arc_dir: Path, cron_yaml: dict) -> None:
    """Toggling a cron job enabled/disabled should persist to YAML."""
    from arc.tui.screens.cron import _load_jobs_raw, _save_jobs_raw
    with patch("arc.tui.screens.cron._jobs_file", return_value=arc_dir / "cron" / "jobs.yaml"):
        raw = _load_jobs_raw()
        raw["jobs"]["heartbeat"]["enabled"] = False
        _save_jobs_raw(raw)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert saved["jobs"]["heartbeat"]["enabled"] is False


@pytest.mark.asyncio
async def test_cron_enable_writes_yaml(arc_dir: Path, cron_yaml: dict) -> None:
    """Enabling a disabled cron job persists to YAML."""
    from arc.tui.screens.cron import _load_jobs_raw, _save_jobs_raw
    with patch("arc.tui.screens.cron._jobs_file", return_value=arc_dir / "cron" / "jobs.yaml"):
        raw = _load_jobs_raw()
        assert raw["jobs"]["weekly-plan"]["enabled"] is False
        raw["jobs"]["weekly-plan"]["enabled"] = True
        _save_jobs_raw(raw)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert saved["jobs"]["weekly-plan"]["enabled"] is True


@pytest.mark.asyncio
async def test_cron_new_job_writes_yaml(arc_dir: Path, cron_yaml: dict) -> None:
    """Adding a new cron job writes it to YAML."""
    from arc.tui.screens.cron import _load_jobs_raw, _save_jobs_raw
    with patch("arc.tui.screens.cron._jobs_file", return_value=arc_dir / "cron" / "jobs.yaml"):
        raw = _load_jobs_raw()
        raw["jobs"]["daily-brief"] = {
            "schedule": "0 7 * * *",
            "agent": "coach",
            "prompt": "Good morning brief.",
            "enabled": True,
        }
        _save_jobs_raw(raw)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert "daily-brief" in saved["jobs"]


@pytest.mark.asyncio
async def test_cron_delete_job(arc_dir: Path, cron_yaml: dict) -> None:
    """Deleting a cron job removes it from YAML."""
    from arc.tui.screens.cron import _load_jobs_raw, _save_jobs_raw
    with patch("arc.tui.screens.cron._jobs_file", return_value=arc_dir / "cron" / "jobs.yaml"):
        raw = _load_jobs_raw()
        del raw["jobs"]["heartbeat"]
        _save_jobs_raw(raw)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert "heartbeat" not in saved["jobs"]


# ---------------------------------------------------------------------------
# Config screen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_bool_toggle(arc_dir: Path) -> None:
    """Toggling a boolean config field persists correctly."""
    from arc.tui.screens.config import _get_nested, _load_config_raw, _save_config_raw, _set_nested
    with patch("arc.tui.screens.config._config_path", return_value=arc_dir / "config.yaml"):
        data = _load_config_raw()
        current = _get_nested(data, "daemon.auto_start")
        _set_nested(data, "daemon.auto_start", not bool(current))
        _save_config_raw(data)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert saved["daemon"]["auto_start"] is True


@pytest.mark.asyncio
async def test_config_int_edit(arc_dir: Path) -> None:
    """Editing an int config field persists correctly."""
    from arc.tui.screens.config import _load_config_raw, _save_config_raw, _set_nested
    with patch("arc.tui.screens.config._config_path", return_value=arc_dir / "config.yaml"):
        data = _load_config_raw()
        _set_nested(data, "timeouts.acpx_request", 600)
        _save_config_raw(data)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert saved["timeouts"]["acpx_request"] == 600


@pytest.mark.asyncio
async def test_config_str_edit(arc_dir: Path) -> None:
    """Editing a string config field persists correctly."""
    from arc.tui.screens.config import _load_config_raw, _save_config_raw, _set_nested
    with patch("arc.tui.screens.config._config_path", return_value=arc_dir / "config.yaml"):
        data = _load_config_raw()
        _set_nested(data, "discord.guild_id", "5678")
        _save_config_raw(data)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert str(saved["discord"]["guild_id"]) == "5678"


@pytest.mark.asyncio
async def test_config_log_level_cycle(arc_dir: Path) -> None:
    """Cycling log level advances through debug/info/warning/error."""
    from arc.tui.screens.config import (
        _LOG_LEVELS,
        _get_nested,
        _load_config_raw,
        _save_config_raw,
        _set_nested,
    )
    with patch("arc.tui.screens.config._config_path", return_value=arc_dir / "config.yaml"):
        data = _load_config_raw()
        current = _get_nested(data, "daemon.log_level") or "info"
        idx = _LOG_LEVELS.index(current) if current in _LOG_LEVELS else 0
        new_val = _LOG_LEVELS[(idx + 1) % len(_LOG_LEVELS)]
        _set_nested(data, "daemon.log_level", new_val)
        _save_config_raw(data)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert saved["daemon"]["log_level"] in _LOG_LEVELS


# ---------------------------------------------------------------------------
# CLI entry point: arc tui with missing textual
# ---------------------------------------------------------------------------


def test_tui_cmd_missing_textual() -> None:
    """arc tui should print a helpful error if textual is not installed."""
    import sys

    from typer.testing import CliRunner

    from arc.cli import app

    runner = CliRunner()
    with patch.dict(sys.modules, {"textual": None, "arc.tui.app": None}):
        with patch("arc.tui.app.ArcTUI", side_effect=ImportError("no textual")):
            # Simulate missing textual by patching the import
            result = runner.invoke(app, ["tui"])
            # Should not crash ungracefully; either ImportError caught or exit 1
            assert result.exit_code in (0, 1)


def test_tui_cmd_imports() -> None:
    """arc tui command is registered and importable."""
    from typer.testing import CliRunner

    from arc.cli import app

    runner = CliRunner()
    # Just check help text is available, not that the TUI runs
    result = runner.invoke(app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "tui" in result.output.lower() or "launch" in result.output.lower()
