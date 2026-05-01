"""Tests for Phase 6 CLI commands: agent, log, config, cron add/remove/edit/history, version."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
import pytest
from typer.testing import CliRunner

from arc.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# arc version
# ---------------------------------------------------------------------------


def test_version_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "arc" in result.output


# ---------------------------------------------------------------------------
# arc agent list
# ---------------------------------------------------------------------------


def test_agent_list_shows_agents(config_dir: Path, coach_agent_yaml: dict) -> None:
    result = runner.invoke(app, ["agent", "list", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "coach" in result.output


def test_agent_list_empty(config_dir: Path) -> None:
    result = runner.invoke(app, ["agent", "list", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "no agents" in result.output.lower()


# ---------------------------------------------------------------------------
# arc agent show
# ---------------------------------------------------------------------------


def test_agent_show_coach(config_dir: Path, coach_agent_yaml: dict) -> None:
    result = runner.invoke(app, ["agent", "show", "coach", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "claude-sonnet-4-6" in result.output


def test_agent_show_not_found(config_dir: Path) -> None:
    result = runner.invoke(app, ["agent", "show", "missing", "--config-dir", str(config_dir)])
    assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# arc agent create
# ---------------------------------------------------------------------------


def test_agent_create_writes_yaml(config_dir: Path, workspace: Path) -> None:
    result = runner.invoke(app, [
        "agent", "create",
        "--name", "newbot",
        "--model", "claude-haiku-4-5",
        "--workspace", str(workspace),
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code == 0
    agent_file = config_dir / "agents" / "newbot.yaml"
    assert agent_file.exists()
    data = yaml.safe_load(agent_file.read_text())
    assert data["name"] == "newbot"
    assert data["model"] == "claude-haiku-4-5"


def test_agent_create_already_exists(config_dir: Path, workspace: Path, coach_agent_yaml: dict) -> None:
    result = runner.invoke(app, [
        "agent", "create",
        "--name", "coach",
        "--model", "claude-haiku-4-5",
        "--workspace", str(workspace),
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code != 0 or "exists" in result.output.lower()


# ---------------------------------------------------------------------------
# arc agent delete
# ---------------------------------------------------------------------------


def test_agent_delete_removes_yaml(config_dir: Path, coach_agent_yaml: dict) -> None:
    result = runner.invoke(app, [
        "agent", "delete", "coach",
        "--config-dir", str(config_dir),
    ], input="y\n")
    assert result.exit_code == 0
    assert not (config_dir / "agents" / "coach.yaml").exists()


def test_agent_delete_not_found(config_dir: Path) -> None:
    result = runner.invoke(app, [
        "agent", "delete", "ghost",
        "--config-dir", str(config_dir),
    ], input="y\n")
    assert result.exit_code != 0 or "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# arc agent clone
# ---------------------------------------------------------------------------


def test_agent_clone_creates_new(config_dir: Path, coach_agent_yaml: dict) -> None:
    result = runner.invoke(app, [
        "agent", "clone", "coach", "coach2",
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code == 0
    clone_file = config_dir / "agents" / "coach2.yaml"
    assert clone_file.exists()
    data = yaml.safe_load(clone_file.read_text())
    assert data["name"] == "coach2"
    # channel_id should be cleared
    assert data.get("discord", {}).get("channel_id") is None


def test_agent_clone_target_exists(config_dir: Path, coach_agent_yaml: dict, trainer_agent_yaml: dict) -> None:
    result = runner.invoke(app, [
        "agent", "clone", "coach", "trainer",
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code != 0 or "exists" in result.output.lower()


# ---------------------------------------------------------------------------
# arc log routing
# ---------------------------------------------------------------------------


def test_log_routing_empty(config_dir: Path) -> None:
    result = runner.invoke(app, ["log", "routing", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "no" in result.output.lower() or result.output.strip() == ""


def test_log_routing_shows_entries(config_dir: Path) -> None:
    log_file = config_dir / "logs" / "routing.jsonl"
    entry = {
        "timestamp": "2026-04-30T10:00:00Z",
        "agent": "coach",
        "model": "claude-sonnet-4-6",
        "dispatch_type": "acpx",
        "source": "cli",
        "one_shot": True,
        "prompt_preview": "Write a workout",
    }
    log_file.write_text(json.dumps(entry) + "\n")
    result = runner.invoke(app, ["log", "routing", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "coach" in result.output


# ---------------------------------------------------------------------------
# arc log cron
# ---------------------------------------------------------------------------


def test_log_cron_empty(config_dir: Path) -> None:
    result = runner.invoke(app, ["log", "cron", "--config-dir", str(config_dir)])
    assert result.exit_code == 0


def test_log_cron_filter_by_job(config_dir: Path) -> None:
    log_file = config_dir / "logs" / "cron.jsonl"
    entries = [
        {"timestamp": "2026-04-30T10:00:00Z", "job": "weekly-plan", "status": "ok", "output_preview": "Done"},
        {"timestamp": "2026-04-30T11:00:00Z", "job": "heartbeat", "status": "ok", "output_preview": "Alive"},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = runner.invoke(app, [
        "log", "cron", "--job", "heartbeat", "--config-dir", str(config_dir)
    ])
    assert result.exit_code == 0
    assert "heartbeat" in result.output
    assert "weekly-plan" not in result.output


# ---------------------------------------------------------------------------
# arc config show
# ---------------------------------------------------------------------------


def test_config_show_prints_yaml(config_dir: Path) -> None:
    result = runner.invoke(app, ["config", "show", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "daemon" in result.output


# ---------------------------------------------------------------------------
# arc config set
# ---------------------------------------------------------------------------


def test_config_set_updates_value(config_dir: Path) -> None:
    result = runner.invoke(app, [
        "config", "set", "git.auto_pull", "false",
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code == 0
    data = yaml.safe_load((config_dir / "config.yaml").read_text())
    assert data["git"]["auto_pull"] is False


def test_config_set_integer_value(config_dir: Path) -> None:
    result = runner.invoke(app, [
        "config", "set", "timeouts.acpx_request", "600",
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code == 0
    data = yaml.safe_load((config_dir / "config.yaml").read_text())
    assert data["timeouts"]["acpx_request"] == 600


def test_config_set_nested_creates_key(config_dir: Path) -> None:
    result = runner.invoke(app, [
        "config", "set", "discord.guild_id", "9999",
        "--config-dir", str(config_dir),
    ])
    assert result.exit_code == 0
    data = yaml.safe_load((config_dir / "config.yaml").read_text())
    # digit-only strings are coerced to int by config set
    assert str(data["discord"]["guild_id"]) == "9999"


# ---------------------------------------------------------------------------
# arc cron history
# ---------------------------------------------------------------------------


def test_cron_history_shows_all(config_dir: Path) -> None:
    log_file = config_dir / "logs" / "cron.jsonl"
    entries = [
        {"timestamp": "2026-04-30T10:00:00Z", "job": "weekly-plan", "status": "ok", "output_preview": "Done"},
        {"timestamp": "2026-04-30T11:00:00Z", "job": "heartbeat", "status": "ok", "output_preview": "Alive"},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = runner.invoke(app, ["cron", "history", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "weekly-plan" in result.output
    assert "heartbeat" in result.output


def test_cron_history_filter_by_name(config_dir: Path) -> None:
    log_file = config_dir / "logs" / "cron.jsonl"
    entries = [
        {"timestamp": "2026-04-30T10:00:00Z", "job": "weekly-plan", "status": "ok", "output_preview": "Done"},
        {"timestamp": "2026-04-30T11:00:00Z", "job": "heartbeat", "status": "ok", "output_preview": "Alive"},
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = runner.invoke(app, [
        "cron", "history", "weekly-plan", "--config-dir", str(config_dir)
    ])
    assert result.exit_code == 0
    assert "weekly-plan" in result.output
    assert "heartbeat" not in result.output


def test_cron_history_last_n(config_dir: Path) -> None:
    log_file = config_dir / "logs" / "cron.jsonl"
    entries = [
        {"timestamp": f"2026-04-30T{h:02d}:00:00Z", "job": "job", "status": "ok", "output_preview": "x"}
        for h in range(10)
    ]
    log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = runner.invoke(app, [
        "cron", "history", "--last", "3", "--config-dir", str(config_dir)
    ])
    assert result.exit_code == 0
    # Should only show 3 entries
    assert result.output.count("job") <= 3
