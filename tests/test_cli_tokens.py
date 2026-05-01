from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from arc.cli import _codeburn_bin, app

runner = CliRunner()


# ---------------------------------------------------------------------------
# _codeburn_bin
# ---------------------------------------------------------------------------


def test_codeburn_bin_prefers_global():
    with patch("arc.cli.shutil.which", side_effect=lambda x: "/usr/bin/codeburn" if x == "codeburn" else None):
        assert _codeburn_bin() == ["/usr/bin/codeburn"]


def test_codeburn_bin_npx_fallback():
    def which_side(name: str) -> str | None:
        return "/usr/local/bin/npx" if name == "npx" else None

    with patch("arc.cli.shutil.which", side_effect=which_side):
        result = _codeburn_bin()
    assert result == ["/usr/local/bin/npx", "--yes", "codeburn"]


def test_codeburn_bin_returns_empty_when_missing():
    with patch("arc.cli.shutil.which", return_value=None):
        assert _codeburn_bin() == []


# ---------------------------------------------------------------------------
# arc tokens - error cases
# ---------------------------------------------------------------------------


def test_tokens_exits_when_codeburn_missing(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value=None):
        result = runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    assert result.exit_code == 1
    assert "codeburn not found" in result.output


def test_tokens_unknown_agent_exits_nonzero(config_dir: Path) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        result = runner.invoke(app, ["tokens", "--agent", "nobody", "--config-dir", str(config_dir)])
    assert result.exit_code != 0
    assert "nobody" in result.output


# ---------------------------------------------------------------------------
# arc tokens - no agent (global view)
# ---------------------------------------------------------------------------


def test_tokens_no_agent_lists_agents(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    assert "coach" in result.output


def test_tokens_no_agent_scopes_to_all_arc_agents(
    config_dir: Path, workspace: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    cmd = mock_run.call_args[0][0]
    assert "--project" in cmd
    assert workspace.name in cmd


def test_tokens_no_agents_configured_omits_project_filter(config_dir: Path) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    cmd = mock_run.call_args[0][0]
    assert "--project" not in cmd


def test_tokens_no_agents_configured(config_dir: Path) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# arc tokens --agent
# ---------------------------------------------------------------------------


def test_tokens_agent_adds_project_filter(
    config_dir: Path, workspace: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            result = runner.invoke(
                app, ["tokens", "--agent", "coach", "--config-dir", str(config_dir)]
            )
    assert result.exit_code == 0
    cmd = mock_run.call_args[0][0]
    assert "--project" in cmd
    project_idx = cmd.index("--project")
    assert cmd[project_idx + 1] == workspace.name


def test_tokens_agent_shows_workspace_header(
    config_dir: Path, workspace: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)):
            result = runner.invoke(
                app, ["tokens", "--agent", "coach", "--config-dir", str(config_dir)]
            )
    assert "coach" in result.output
    assert str(workspace) in result.output


# ---------------------------------------------------------------------------
# arc tokens - flags forwarded to codeburn
# ---------------------------------------------------------------------------


def test_tokens_provider_claude_always_set(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    cmd = mock_run.call_args[0][0]
    assert "--provider" in cmd
    assert cmd[cmd.index("--provider") + 1] == "claude"


def test_tokens_period_forwarded(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(
                app, ["tokens", "--period", "week", "--config-dir", str(config_dir)]
            )
    cmd = mock_run.call_args[0][0]
    assert "--period" in cmd
    assert cmd[cmd.index("--period") + 1] == "week"


def test_tokens_default_subcommand_is_status(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    cmd = mock_run.call_args[0][0]
    assert "status" in cmd


def test_tokens_report_subcommand(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(
                app, ["tokens", "--cmd", "report", "--config-dir", str(config_dir)]
            )
    cmd = mock_run.call_args[0][0]
    assert "report" in cmd
    # --period is only forwarded for `status`
    assert "--period" not in cmd


def test_tokens_propagates_codeburn_exit_code(config_dir: Path, coach_agent_yaml: dict) -> None:
    with patch("arc.cli.shutil.which", return_value="/usr/bin/codeburn"):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=2)):
            result = runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    assert result.exit_code == 2


def test_tokens_npx_fallback_invoked(config_dir: Path, coach_agent_yaml: dict) -> None:
    def which_side(name: str) -> str | None:
        return "/usr/local/bin/npx" if name == "npx" else None

    with patch("arc.cli.shutil.which", side_effect=which_side):
        with patch("arc.cli.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            runner.invoke(app, ["tokens", "--config-dir", str(config_dir)])
    cmd = mock_run.call_args[0][0]
    assert "npx" in cmd[0]
    assert "codeburn" in cmd
