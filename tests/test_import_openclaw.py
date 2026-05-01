import json
from pathlib import Path

import yaml

from arc.import_openclaw import (
    _build_channel_map,
    _find_identity_files,
    _map_model,
    convert_agents,
    convert_cron_jobs,
    import_from_path,
)

# --- helpers ---


def _make_oc_dir(tmp_path: Path, workspace: Path) -> Path:
    oc_dir = tmp_path / ".openclaw"
    oc_dir.mkdir()
    (oc_dir / "cron").mkdir()

    config = {
        "agents": {
            "list": [
                {
                    "id": "coach",
                    "name": "coach",
                    "workspace": str(workspace),
                    "agentDir": "/root/.openclaw/agents/coach/agent",
                    "model": "anthropic/claude-sonnet-4-6",
                },
                {
                    "id": "trainer",
                    "name": "trainer",
                    "workspace": str(workspace),
                    "agentDir": "/root/.openclaw/agents/trainer/agent",
                    "model": {"primary": "anthropic/claude-haiku-4-5"},
                },
            ]
        },
        "bindings": [
            {
                "type": "route",
                "agentId": "coach",
                "match": {"channel": "discord", "peer": {"kind": "channel", "id": "9999"}},
            }
        ],
    }
    (oc_dir / "openclaw.json").write_text(json.dumps(config))

    cron = {
        "jobs": [
            {
                "id": "abc",
                "agentId": "coach",
                "name": "weekly-plan",
                "description": "Weekly plan",
                "enabled": True,
                "schedule": {"kind": "cron", "expr": "0 20 * * 0"},
                "payload": {"kind": "agentTurn", "message": "Write weekly plan."},
            },
            {
                "id": "def",
                "agentId": "trainer",
                "name": "heartbeat",
                "enabled": True,
                "schedule": {"kind": "every", "everyMs": 7200000},
                "payload": {"kind": "agentTurn", "message": "Run heartbeat scan."},
            },
        ]
    }
    (oc_dir / "cron" / "jobs.json").write_text(json.dumps(cron))
    return oc_dir


# --- _map_model ---


def test_map_model_string() -> None:
    assert _map_model("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_map_model_dict() -> None:
    assert _map_model({"primary": "anthropic/claude-haiku-4-5"}) == "claude-haiku-4-5"


def test_map_model_unknown() -> None:
    assert _map_model("anthropic/custom-model") == "custom-model"


# --- _build_channel_map ---


def test_build_channel_map() -> None:
    bindings = [
        {
            "type": "route",
            "agentId": "coach",
            "match": {"channel": "discord", "peer": {"kind": "channel", "id": "1234"}},
        },
        {
            "type": "route",
            "agentId": "main",
            "match": {"channel": "discord"},
        },
    ]
    mapping = _build_channel_map(bindings)
    assert mapping["coach"] == "1234"
    assert "main" not in mapping


# --- _find_identity_files ---


def test_find_identity_files(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents")
    (tmp_path / "SOUL.md").write_text("soul")
    found = _find_identity_files(tmp_path)
    assert "AGENTS.md" in found
    assert "SOUL.md" in found
    assert "IDENTITY.md" not in found


# --- convert_agents ---


def test_convert_agents(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("agents")
    (workspace / "IDENTITY.md").write_text("identity")

    config = {
        "agents": {"list": [
            {"id": "coach", "name": "coach", "workspace": str(workspace),
             "model": "anthropic/claude-sonnet-4-6"},
        ]},
        "bindings": [
            {"type": "route", "agentId": "coach",
             "match": {"channel": "discord", "peer": {"kind": "channel", "id": "9999"}}},
        ],
    }
    agents = convert_agents(config)
    assert len(agents) == 1
    a = agents[0]
    assert a["name"] == "coach"
    assert a["model"] == "claude-sonnet-4-6"
    assert "AGENTS.md" in a["system_prompt_files"]
    assert a["discord"]["channel_id"] == "9999"


def test_convert_agents_no_channel(tmp_path: Path) -> None:
    config = {
        "agents": {"list": [
            {"id": "trainer", "name": "trainer", "workspace": str(tmp_path),
             "model": "anthropic/claude-haiku-4-5"},
        ]},
        "bindings": [],
    }
    agents = convert_agents(config)
    assert agents[0]["discord"] == {}


# --- convert_cron_jobs ---


def test_convert_cron_jobs_cron_schedule() -> None:
    data = {"jobs": [
        {"id": "x", "agentId": "coach", "name": "weekly", "enabled": True,
         "schedule": {"kind": "cron", "expr": "0 20 * * 0"}, "payload": {"message": "Write plan."}},
    ]}
    result = convert_cron_jobs(data)
    assert result["jobs"]["weekly"]["schedule"] == "0 20 * * 0"
    assert result["jobs"]["weekly"]["prompt"] == "Write plan."


def test_convert_cron_jobs_every_schedule() -> None:
    data = {"jobs": [
        {"id": "x", "agentId": "trainer", "name": "heartbeat", "enabled": True,
         "schedule": {"kind": "every", "everyMs": 7200000}, "payload": {"message": "Scan."}},
    ]}
    result = convert_cron_jobs(data)
    assert result["jobs"]["heartbeat"]["schedule"] == "*/120 * * * *"


def test_convert_cron_jobs_disabled() -> None:
    data = {"jobs": [
        {"id": "x", "agentId": "coach", "name": "paused", "enabled": False,
         "schedule": {"kind": "cron", "expr": "0 7 * * *"}, "payload": {"message": "hi"}},
    ]}
    result = convert_cron_jobs(data)
    assert result["jobs"]["paused"]["enabled"] is False


# --- import_from_path ---


def test_import_from_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("agents")
    oc_dir = _make_oc_dir(tmp_path, workspace)
    arc_dir = tmp_path / ".arc"

    summary = import_from_path(oc_dir, arc_dir)

    assert "coach" in summary["agents_imported"]
    assert "trainer" in summary["agents_imported"]
    assert "weekly-plan" in summary["jobs_imported"]
    assert not summary["errors"]

    coach_yaml = yaml.safe_load((arc_dir / "agents" / "coach.yaml").read_text())
    assert coach_yaml["model"] == "claude-sonnet-4-6"
    assert coach_yaml["discord"]["channel_id"] == "9999"


def test_import_dry_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    oc_dir = _make_oc_dir(tmp_path, workspace)
    arc_dir = tmp_path / ".arc"

    summary = import_from_path(oc_dir, arc_dir, dry_run=True)

    assert "coach" in summary["agents_imported"]
    assert not (arc_dir / "agents" / "coach.yaml").exists()


def test_import_skips_existing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    oc_dir = _make_oc_dir(tmp_path, workspace)
    arc_dir = tmp_path / ".arc"
    (arc_dir / "agents").mkdir(parents=True)
    (arc_dir / "agents" / "coach.yaml").write_text("name: coach\n")

    summary = import_from_path(oc_dir, arc_dir)

    assert any("coach" in s for s in summary["skipped"])
    assert "coach" not in summary["agents_imported"]


def test_import_missing_openclaw_json(tmp_path: Path) -> None:
    summary = import_from_path(tmp_path / "nonexistent", tmp_path / ".arc")
    assert summary["errors"]
