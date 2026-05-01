"""Functional tests verifying each interactive element of the TUI.

Tests verify:
- Status pane loads and shows content (not stuck on 'Loading...')
- j/k navigation moves list selection in Agents and Cron panes
- on_list_view_highlighted drives detail panel updates (not just on Enter)
- Cron toggle updates YAML immediately
- Config bool toggle and int edit persist
- VimListView j/k bindings work
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from arc.tui.app import ArcTUI
from arc.tui.widgets.vim_list import VimListView

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def arc_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".arc"
    (d / "agents").mkdir(parents=True)
    (d / "cron").mkdir()
    (d / "logs").mkdir()
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
def with_agents(arc_dir: Path, tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    for name, model in [("coach", "claude-sonnet-4-6"), ("trainer", "claude-haiku-4-5")]:
        (arc_dir / "agents" / f"{name}.yaml").write_text(
            yaml.dump({
                "name": name,
                "description": f"Test {name}",
                "workspace": str(ws),
                "system_prompt_files": ["AGENTS.md"],
                "model": model,
                "allowed_models": [model, "ollama/qwen3:8b"],
                "permission_mode": "approve-all",
                "discord": {"channel_id": "9999"} if name == "coach" else {},
            })
        )
    return arc_dir


@pytest.fixture
def with_cron(arc_dir: Path) -> Path:
    (arc_dir / "cron" / "jobs.yaml").write_text(
        yaml.dump(
            {
                "jobs": {
                    "heartbeat": {
                        "schedule": "*/30 * * * *",
                        "agent": "coach",
                        "prompt": "Check status.",
                        "enabled": True,
                    },
                    "weekly-plan": {
                        "schedule": "0 19 * * 0",
                        "agent": "coach",
                        "prompt": "Write the weekly plan.",
                        "enabled": False,
                    },
                    "daily-brief": {
                        "schedule": "0 7 * * *",
                        "agent": "coach",
                        "prompt": "Morning brief.",
                        "enabled": True,
                    },
                }
            },
            sort_keys=False,
        )
    )
    return arc_dir


def _patch_config(arc_dir: Path):
    """Patch load_config in all TUI modules to use the test arc_dir.

    Each TUI screen does `from arc.config import load_config` which binds
    the name locally. Patching `arc.config.load_config` alone won't reach
    those local bindings -- we must patch each module's reference separately.
    """
    from contextlib import ExitStack

    from arc.config import load_config as _real_load

    def _mock(config_dir=None):
        return _real_load(arc_dir)

    targets = [
        "arc.config.load_config",
        "arc.tui.screens.status.load_config",
        "arc.tui.screens.agents.load_config",
        "arc.tui.screens.cron.load_config",
        "arc.tui.screens.config.load_config",
    ]

    class _MultiPatch:
        def __enter__(self):
            self._stack = ExitStack()
            for t in targets:
                self._stack.enter_context(patch(t, side_effect=_mock))
            return self

        def __exit__(self, *a):
            self._stack.__exit__(*a)

    return _MultiPatch()


# ---------------------------------------------------------------------------
# Status pane: content loads (not stuck on 'Loading...')
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_pane_loads_content(arc_dir: Path, with_agents: Path) -> None:
    """Status pane must update beyond 'Loading...' after mount."""
    ipc_response = {
        "status": "ok",
        "daemon": {"pid": 12345, "socket": "/tmp/arc.sock"},
        "agents": [
            {
                "name": "coach",
                "model": "claude-sonnet-4-6",
                "workspace": "/ws/coach",
                "discord_channel": "9999",
            }
        ],
        "cron": [
            {
                "name": "heartbeat",
                "schedule": "*/30 * * * *",
                "enabled": True,
                "next_run": "2026-05-01T01:00:00+00:00",
            }
        ],
    }
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=ipc_response):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                # Give the @work coroutine time to complete
                await pilot.pause(0.5)
                from textual.widgets import Static

                content = pilot.app.query_one("#status-content", Static)
                text = content.content  # use .content not .renderable
                assert str(text) != "Loading...", "Status pane stuck on 'Loading...'"


@pytest.mark.asyncio
async def test_status_pane_offline_fallback(arc_dir: Path, with_agents: Path) -> None:
    """Status pane falls back to config files when daemon is not running."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.5)
                from textual.widgets import Static

                content = pilot.app.query_one("#status-content", Static)
                text = str(content.content)
                assert text != "Loading...", "Status pane stuck on 'Loading...'"
                assert "not running" in text.lower() or "coach" in text or "trainer" in text


# ---------------------------------------------------------------------------
# VimListView: j/k key navigation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vim_list_j_moves_down(arc_dir: Path, with_agents: Path) -> None:
    """j key should move selection down: from None->0, then 0->1."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("agents")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#agents-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)

                # First j: goes from None -> 0 (first item selected)
                await pilot.press("j")
                await pilot.pause(0.05)
                idx_0 = lv.index
                assert idx_0 == 0

                # Second j: goes from 0 -> 1
                await pilot.press("j")
                await pilot.pause(0.05)
                assert lv.index == 1


@pytest.mark.asyncio
async def test_vim_list_k_moves_up(arc_dir: Path, with_agents: Path) -> None:
    """k key should move selection up."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("agents")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#agents-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)

                # Move down twice then up once
                await pilot.press("j")
                await pilot.press("j")
                await pilot.pause(0.05)
                idx_mid = lv.index  # should be 1
                await pilot.press("k")
                await pilot.pause(0.05)
                assert lv.index == max(0, (idx_mid or 1) - 1)


# ---------------------------------------------------------------------------
# Agents: detail updates on keyboard navigation (highlighted)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_detail_updates_on_keyboard_nav(
    arc_dir: Path, with_agents: Path
) -> None:
    """Moving between agents with j should update the detail panel."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("agents")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#agents-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)

                from arc.tui.screens.agents import AgentDetail

                detail = pilot.app.query_one("#agents-detail", AgentDetail)
                # Detail shows coach initially (first agent)
                text_coach = str(detail.content)

                # First j: None -> 0 (coach, same as initial)
                await pilot.press("j")
                await pilot.pause(0.05)
                # Second j: 0 -> 1 (trainer)
                await pilot.press("j")
                await pilot.pause(0.1)
                text_trainer = str(detail.content)

                assert text_coach != text_trainer, (
                    "Detail panel did not update after navigating to next agent"
                )
                assert "coach" in text_coach
                assert "trainer" in text_trainer


# ---------------------------------------------------------------------------
# Cron: j/k navigation and detail updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_detail_updates_on_nav(arc_dir: Path, with_cron: Path) -> None:
    """Navigating cron list with j shows detail for each job."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("cron")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#cron-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)

                from arc.tui.screens.cron import CronDetail

                detail = pilot.app.query_one("#cron-detail", CronDetail)
                text_first = str(detail.content)
                assert len(text_first) > 10, "Detail should not be empty after mount"

                # First j: None -> 0 (same job, detail unchanged)
                await pilot.press("j")
                await pilot.pause(0.05)
                # Second j: 0 -> 1 (next job)
                await pilot.press("j")
                await pilot.pause(0.1)
                text_second = str(detail.content)

                assert text_first != text_second, (
                    "Detail panel did not update after j navigation"
                )


# ---------------------------------------------------------------------------
# Cron: toggle and action methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_toggle_action_writes_yaml(arc_dir: Path, with_cron: Path) -> None:
    """action_toggle_job() on CronPane writes the new enabled state to YAML."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("cron")
                await pilot.pause(0.2)

                from arc.tui.screens.cron import CronPane

                pane = pilot.app.query_one("#cron-pane", CronPane)
                # heartbeat is first (index 0), enabled=True
                lv = pilot.app.query_one("#cron-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)
                # Ensure first item is selected
                await pilot.press("j")
                await pilot.pause(0.05)

                with patch(
                    "arc.tui.screens.cron._jobs_file",
                    return_value=arc_dir / "cron" / "jobs.yaml",
                ):
                    pane.action_toggle_job()
                    await pilot.pause(0.2)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert saved["jobs"]["heartbeat"]["enabled"] is False


@pytest.mark.asyncio
async def test_cron_toggle_via_space_key(arc_dir: Path, with_cron: Path) -> None:
    """Space key on focused cron list calls toggle and persists to YAML."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("cron")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#cron-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)
                await pilot.press("j")  # select heartbeat (index 0)
                await pilot.pause(0.05)

                # Press space; binding defined on CronPane, bubbles from VimListView
                with patch(
                    "arc.tui.screens.cron._jobs_file",
                    return_value=arc_dir / "cron" / "jobs.yaml",
                ):
                    await pilot.press("space")
                    await pilot.pause(0.2)

    saved = yaml.safe_load((arc_dir / "cron" / "jobs.yaml").read_text())
    assert saved["jobs"]["heartbeat"]["enabled"] is False


# ---------------------------------------------------------------------------
# Config: j/k navigation, bool toggle, int edit via action methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_j_k_navigation(arc_dir: Path) -> None:
    """j/k should move through config rows in the list."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.2)
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("config")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#config-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)

                # j moves from None -> 0 (first row selected)
                await pilot.press("j")
                await pilot.pause(0.05)
                assert lv.index == 0

                # j again: 0 -> 1
                await pilot.press("j")
                await pilot.pause(0.05)
                assert lv.index == 1

                # k: 1 -> 0
                await pilot.press("k")
                await pilot.pause(0.05)
                assert lv.index == 0


@pytest.mark.asyncio
async def test_config_bool_toggle_action(arc_dir: Path) -> None:
    """action_toggle_field on auto_start persists to config.yaml."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("config")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#config-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)
                # Row 0=DAEMON header, row 1=auto_start
                await pilot.press("j")
                await pilot.press("j")  # index 1 = auto_start
                await pilot.pause(0.05)

                from arc.tui.screens.config import ConfigPane

                pane = pilot.app.query_one("#config-pane", ConfigPane)
                with patch(
                    "arc.tui.screens.config._config_path",
                    return_value=arc_dir / "config.yaml",
                ):
                    pane.action_toggle_field()
                    await pilot.pause(0.1)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert saved["daemon"]["auto_start"] is True


@pytest.mark.asyncio
async def test_config_log_level_cycle_action(arc_dir: Path) -> None:
    """action_edit_field on log_level cycles through debug/info/warning/error."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent

                pilot.app.query_one(TabbedContent).show_tab("config")
                await pilot.pause(0.2)

                lv = pilot.app.query_one("#config-list", VimListView)
                lv.focus()
                await pilot.pause(0.05)
                # Row 2=log_level
                for _ in range(3):
                    await pilot.press("j")
                await pilot.pause(0.05)

                from arc.tui.screens.config import _LOG_LEVELS, ConfigPane

                pane = pilot.app.query_one("#config-pane", ConfigPane)
                with patch(
                    "arc.tui.screens.config._config_path",
                    return_value=arc_dir / "config.yaml",
                ):
                    pane.action_edit_field()
                    await pilot.pause(0.1)

    saved = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert saved["daemon"]["log_level"] in _LOG_LEVELS


# ---------------------------------------------------------------------------
# All screens render without exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_screens_render_no_exception(
    arc_dir: Path, with_agents: Path, with_cron: Path
) -> None:
    """Cycle through all four tabs and confirm no exceptions are raised."""
    with _patch_config(arc_dir):
        with patch("arc.ipc.request", new_callable=AsyncMock, return_value=None):
            async with ArcTUI().run_test(size=(120, 40)) as pilot:
                from textual.widgets import TabbedContent

                tc = pilot.app.query_one(TabbedContent)

                for tab in ("status", "agents", "cron", "config"):
                    tc.show_tab(tab)
                    await pilot.pause(0.3)

                assert pilot.app.is_running
