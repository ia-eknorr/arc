"""Import agents and cron jobs from an existing OpenClaw installation."""
import json
import logging
from pathlib import Path

import yaml

log = logging.getLogger("arc.import")

_IDENTITY_FILES = ["AGENTS.md", "IDENTITY.md", "SOUL.md", "USER.md", "TOOLS.md"]

_MODEL_MAP = {
    "anthropic/claude-sonnet-4-6": "sonnet",
    "anthropic/claude-haiku-4-5": "haiku",
    "anthropic/claude-opus-4-7": "opus",
}


def _map_model(oc_model: str | dict) -> str:
    """Convert OpenClaw model spec to an acpx model alias."""
    if isinstance(oc_model, dict):
        oc_model = oc_model.get("primary", "sonnet")
    return _MODEL_MAP.get(oc_model, oc_model.removeprefix("anthropic/"))


def _find_identity_files(workspace: Path) -> list[str]:
    """Return identity filenames that exist in workspace (relative to workspace)."""
    return [f for f in _IDENTITY_FILES if (workspace / f).exists()]


def _build_channel_map(bindings: list[dict]) -> dict[str, str]:
    """Return agentId -> discord channel_id from OpenClaw bindings."""
    channel_map: dict[str, str] = {}
    for b in bindings:
        if b.get("type") == "route" and b.get("match", {}).get("channel") == "discord":
            peer = b.get("match", {}).get("peer", {})
            if peer.get("kind") == "channel":
                channel_map[b["agentId"]] = str(peer["id"])
    return channel_map


def convert_agents(openclaw_json: dict) -> list[dict]:
    """Convert OpenClaw agent list to arc agent YAML dicts."""
    agents_list = openclaw_json.get("agents", {}).get("list", [])
    bindings = openclaw_json.get("bindings", [])
    channel_map = _build_channel_map(bindings)

    result = []
    for oc_agent in agents_list:
        agent_id = oc_agent.get("id") or oc_agent.get("name")
        workspace = Path(oc_agent.get("workspace", ""))
        identity_files = _find_identity_files(workspace) if workspace.exists() else []

        agent = {
            "name": agent_id,
            "description": oc_agent.get("description", ""),
            "workspace": str(workspace),
            "system_prompt_files": identity_files,
            "model": _map_model(oc_agent.get("model", "sonnet")),
            "allowed_models": [],
            "permission_mode": "approve-all",
        }

        channel_id = channel_map.get(agent_id)
        if channel_id:
            agent["discord"] = {"channel_id": channel_id}
        else:
            agent["discord"] = {}

        result.append(agent)
    return result


def convert_cron_jobs(cron_jobs_json: dict) -> dict:
    """Convert OpenClaw cron jobs to arc jobs.yaml format."""
    jobs: dict[str, dict] = {}
    for job in cron_jobs_json.get("jobs", []):
        name = job.get("name") or job.get("id", "unknown")
        schedule_data = job.get("schedule", {})

        if schedule_data.get("kind") == "cron":
            schedule = schedule_data["expr"]
        elif schedule_data.get("kind") == "every":
            every_ms = schedule_data.get("everyMs", 3600000)
            every_min = max(1, every_ms // 60000)
            schedule = f"*/{every_min} * * * *"
        else:
            schedule = "0 * * * *"

        payload = job.get("payload", {})
        prompt = payload.get("message", "")

        arc_job = {
            "description": job.get("description", ""),
            "schedule": schedule,
            "agent": job.get("agentId", "coach"),
            "prompt": prompt,
            "notify": "discord",
            "enabled": job.get("enabled", True),
        }
        jobs[name] = arc_job
    return {"jobs": jobs}


def import_from_path(
    openclaw_dir: Path,
    arc_dir: Path,
    dry_run: bool = False,
) -> dict:
    """
    Import agents and cron from an OpenClaw directory.

    Returns a summary dict with keys: agents_imported, jobs_imported, skipped, errors.
    """
    summary = {"agents_imported": [], "jobs_imported": [], "skipped": [], "errors": []}

    config_path = openclaw_dir / "openclaw.json"
    if not config_path.exists():
        summary["errors"].append(f"openclaw.json not found at {config_path}")
        return summary

    try:
        openclaw_json = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        summary["errors"].append(f"Failed to parse openclaw.json: {e}")
        return summary

    # Import agents
    agents_dir = arc_dir / "agents"
    if not dry_run:
        agents_dir.mkdir(parents=True, exist_ok=True)

    for agent in convert_agents(openclaw_json):
        dest = agents_dir / f"{agent['name']}.yaml"
        if dest.exists():
            summary["skipped"].append(f"agent:{agent['name']} (already exists)")
            continue
        if not dry_run:
            dest.write_text(yaml.dump(agent, default_flow_style=False, allow_unicode=True))
        summary["agents_imported"].append(agent["name"])

    # Import cron jobs
    cron_jobs_path = openclaw_dir / "cron" / "jobs.json"
    if cron_jobs_path.exists():
        try:
            cron_json = json.loads(cron_jobs_path.read_text())
        except json.JSONDecodeError as e:
            summary["errors"].append(f"Failed to parse cron/jobs.json: {e}")
            cron_json = {}

        arc_cron = convert_cron_jobs(cron_json)
        cron_dir = arc_dir / "cron"
        jobs_yaml = cron_dir / "jobs.yaml"

        if arc_cron["jobs"]:
            if jobs_yaml.exists():
                summary["skipped"].append("cron:jobs.yaml (already exists)")
            else:
                if not dry_run:
                    cron_dir.mkdir(parents=True, exist_ok=True)
                    jobs_yaml.write_text(
                        yaml.dump(arc_cron, default_flow_style=False, allow_unicode=True)
                    )
                summary["jobs_imported"].extend(arc_cron["jobs"].keys())

    return summary
