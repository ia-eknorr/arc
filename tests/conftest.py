from pathlib import Path

import pytest
import yaml


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A temporary ~/.arc directory with default config and an example agent."""
    arc_dir = tmp_path / ".arc"
    agents_dir = arc_dir / "agents"
    logs_dir = arc_dir / "logs"
    agents_dir.mkdir(parents=True)
    logs_dir.mkdir()

    (arc_dir / "config.yaml").write_text(
        """\
daemon:
  auto_start: false
  log_level: warning
acpx:
  command: acpx
  default_agent: claude
  session_ttl: 300
  output_format: text
ollama:
  endpoints:
    local:
      url: http://localhost:11434/v1
    kyle:
      url: http://kyle.local:11434/v1
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
    return arc_dir


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A temporary agent workspace with identity files."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("# Agents\n\nAgent dispatch instructions.")
    (ws / "IDENTITY.md").write_text("# Identity\n\nYou are a test agent.")
    (ws / "SOUL.md").write_text("# Soul\n\nCore values here.")
    return ws


@pytest.fixture
def coach_agent_yaml(config_dir: Path, workspace: Path) -> dict:
    """Write a coach agent YAML and return its data dict."""
    data = {
        "name": "coach",
        "description": "Test coach agent",
        "workspace": str(workspace),
        "system_prompt_files": ["AGENTS.md", "IDENTITY.md", "SOUL.md"],
        "model": "claude-sonnet-4-6",
        "allowed_models": ["claude-sonnet-4-6", "claude-haiku-4-5", "ollama/qwen3:8b"],
        "permission_mode": "bypassPermissions",
        "discord": {"channel_id": "9999"},
    }
    (config_dir / "agents" / "coach.yaml").write_text(yaml.dump(data))
    return data


@pytest.fixture
def trainer_agent_yaml(config_dir: Path, workspace: Path) -> dict:
    """Write a trainer agent using a local Ollama model."""
    data = {
        "name": "trainer",
        "description": "Test trainer agent",
        "workspace": str(workspace),
        "system_prompt_files": ["IDENTITY.md"],
        "model": "ollama/qwen3:8b",
        "allowed_models": ["ollama/qwen3:8b"],
        "permission_mode": "bypassPermissions",
        "local_context_files": ["AGENTS.md"],
        "discord": {},
    }
    (config_dir / "agents" / "trainer.yaml").write_text(yaml.dump(data))
    return data
