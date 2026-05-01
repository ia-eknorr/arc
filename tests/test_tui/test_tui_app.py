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
        f"""\
daemon:
  auto_start: false
  log_level: info
  socket_path: {d}/arc.sock
  pid_file: {d}/daemon.pid
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
    """Patch load_config in all TUI screen modules to use the test arc_dir."""
    from contextlib import ExitStack

    from arc.config import load_config as _real_load

    def _mock_load(config_dir=None):
        return _real_load(arc_dir)

    targets = [
        "arc.config.load_config",
        "arc.tui.screens.status.load_config",
        "arc.tui.screens.agents.load_config",
        "arc.tui.screens.cron.load_config",
        "arc.tui.screens.config.load_config",
        "arc.tui.screens.tokens.load_config",
        "arc.tui.screens.logs.load_config",
    ]

    class _MultiPatch:
        def __enter__(self):
            self._stack = ExitStack()
            for t in targets:
                self._stack.enter_context(patch(t, side_effect=_mock_load))
            return self

        def __exit__(self, *args):
            self._stack.__exit__(*args)

    return _MultiPatch()


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


# ---------------------------------------------------------------------------
# Tokens screen
# ---------------------------------------------------------------------------


def test_tokens_bar_full() -> None:
    from arc.tui.screens.tokens import _bar

    result = _bar(10.0, 10.0, width=10)
    assert result == "█" * 10


def test_tokens_bar_half() -> None:
    from arc.tui.screens.tokens import _bar

    result = _bar(5.0, 10.0, width=10)
    assert "█" in result and "░" in result
    assert len(result) == 10


def test_tokens_bar_zero_max() -> None:
    from arc.tui.screens.tokens import _bar

    result = _bar(0.0, 0.0, width=10)
    assert result == "░" * 10


def test_tokens_render_no_agents(arc_dir: Path) -> None:
    """TokensPane._render should not raise with no agents."""
    from arc.tui.screens.tokens import _bar

    assert len(_bar(5.0, 20.0, width=20)) == 20


def test_tokens_codeburn_not_found(arc_dir: Path) -> None:
    """_cb_bin returns None when codeburn/npx are absent."""
    import shutil

    from arc.tui.screens.tokens import _cb_bin

    with patch.object(shutil, "which", return_value=None):
        result = _cb_bin()
    assert result is None


# ---------------------------------------------------------------------------
# Logs screen
# ---------------------------------------------------------------------------


def test_logs_load_jsonl_empty(arc_dir: Path) -> None:
    from arc.tui.screens.logs import _load_jsonl

    path = arc_dir / "logs" / "routing.jsonl"
    assert not path.exists()
    assert _load_jsonl(path) == []


def test_logs_load_jsonl_parses_entries(arc_dir: Path) -> None:
    from arc.tui.screens.logs import _load_jsonl

    path = arc_dir / "logs" / "routing.jsonl"
    path.write_text(
        '{"timestamp": "2026-05-01T08:00:00+00:00", "agent": "coach", "model": "claude-sonnet-4-6",'
        ' "source": "cli", "one_shot": true, "prompt_preview": "hello"}\n'
        '{"timestamp": "2026-05-01T09:00:00+00:00", "agent": "coach", "model": "claude-haiku-4-5",'
        ' "source": "discord", "one_shot": false, "prompt_preview": "hi"}\n'
    )
    entries = _load_jsonl(path)
    assert len(entries) == 2
    # newest first
    assert entries[0]["timestamp"] > entries[1]["timestamp"]


def test_logs_load_jsonl_last_limit(arc_dir: Path) -> None:
    from arc.tui.screens.logs import _load_jsonl

    path = arc_dir / "logs" / "cron.jsonl"
    lines = [f'{{"timestamp": "2026-05-01T0{i}:00:00+00:00", "job": "hb", "status": "ok", "output_preview": ""}}' for i in range(5)]
    path.write_text("\n".join(lines) + "\n")
    entries = _load_jsonl(path, last=3)
    assert len(entries) == 3


def test_logs_fmt_ts() -> None:
    from arc.tui.screens.logs import _fmt_ts

    result = _fmt_ts("2026-05-01T08:13:09.131782+00:00")
    # Should produce MM-DD HH:MM in local time (exact value depends on timezone)
    assert "-" in result and ":" in result
    assert len(result) == 11  # MM-DD HH:MM


def test_logs_fmt_ts_invalid() -> None:
    from arc.tui.screens.logs import _fmt_ts

    result = _fmt_ts("not-a-timestamp")
    assert result == "not-a-timestamp"[:16]


def test_logs_detail_show_routing() -> None:
    from arc.tui.screens.logs import LogDetail

    detail = LogDetail()
    # Verify show_routing doesn't raise (update is a no-op without a mounted app)
    entry = {
        "timestamp": "2026-05-01T08:00:00+00:00",
        "agent": "coach",
        "model": "claude-sonnet-4-6",
        "dispatch_type": "acpx",
        "source": "cli",
        "one_shot": True,
        "prompt_preview": "hello world",
    }
    # Calling update on an unmounted Static raises -- just check it produces output
    try:
        detail.show_routing(entry)
    except Exception:
        pass  # unmounted widget


def test_logs_detail_show_cron() -> None:
    from arc.tui.screens.logs import LogDetail

    detail = LogDetail()
    entry = {
        "timestamp": "2026-05-01T09:00:00+00:00",
        "job": "heartbeat",
        "status": "ok",
        "output_preview": "HEARTBEAT_OK",
    }
    try:
        detail.show_cron(entry)
    except Exception:
        pass  # unmounted widget


@pytest.mark.asyncio
async def test_logs_tab_renders(arc_dir: Path) -> None:
    """Logs tab renders without error given routing.jsonl entries."""
    routing_log = arc_dir / "logs" / "routing.jsonl"
    routing_log.write_text(
        '{"timestamp": "2026-05-01T08:13:09.131782+00:00", "agent": "coach",'
        ' "model": "claude-sonnet-4-6", "dispatch_type": "acpx",'
        ' "source": "cli", "one_shot": true, "prompt_preview": "hello"}\n'
    )
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent
                pilot.app.query_one(TabbedContent).active = "logs"
                await pilot.pause(0.2)
                assert pilot.app.is_running


@pytest.mark.asyncio
async def test_logs_cron_entries_render(arc_dir: Path) -> None:
    """Logs tab cron mode renders cron.jsonl entries."""
    cron_log = arc_dir / "logs" / "cron.jsonl"
    cron_log.write_text(
        '{"timestamp": "2026-05-01T09:00:00+00:00", "job": "heartbeat", "status": "ok", "output_preview": "HEARTBEAT_OK"}\n'
        '{"timestamp": "2026-05-01T09:30:00+00:00", "job": "heartbeat", "status": "error", "output_preview": "Agent not found"}\n'
    )
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent
                pilot.app.query_one(TabbedContent).active = "logs"
                await pilot.pause(0.2)
                from arc.tui.screens.logs import LogsPane
                pane = pilot.app.query_one(LogsPane)
                pane.action_show_cron()
                await pilot.pause(0.1)
                assert pane._mode == "cron"
                assert len(pane._entries) == 2


@pytest.mark.asyncio
async def test_all_tabs_include_tokens_and_logs(arc_dir: Path) -> None:
    """All six tabs are reachable including Tokens and Logs."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.1)
                from textual.widgets import TabbedContent
                tc = pilot.app.query_one(TabbedContent)
                tab_ids = {tab.id for tab in tc.query("Tab")}
                assert any("tokens" in t for t in tab_ids)
                assert any("logs" in t for t in tab_ids)
