from pathlib import Path

import pytest

from arc.agents import build_system_prompt, list_agents, load_agent, resolve_agent_for_channel
from arc.types import AgentConfig


def test_load_agent(config_dir: Path, coach_agent_yaml: dict) -> None:
    agent = load_agent("coach", config_dir)
    assert agent.name == "coach"
    assert agent.model == "claude-sonnet-4-6"
    assert "claude-haiku-4-5" in agent.allowed_models


def test_load_agent_not_found(config_dir: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Agent 'ghost' not found"):
        load_agent("ghost", config_dir)


def test_load_agent_not_found_lists_available(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    with pytest.raises(FileNotFoundError, match="coach"):
        load_agent("ghost", config_dir)


def test_list_agents(config_dir: Path, coach_agent_yaml: dict, trainer_agent_yaml: dict) -> None:
    agents = list_agents(config_dir)
    names = [a.name for a in agents]
    assert "coach" in names
    assert "trainer" in names


def test_list_agents_empty(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    (arc_dir / "agents").mkdir(parents=True)
    agents = list_agents(arc_dir)
    assert agents == []


def test_list_agents_missing_dir(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    agents = list_agents(arc_dir)
    assert agents == []


async def test_build_system_prompt(
    workspace: Path, coach_agent_yaml: dict, config_dir: Path
) -> None:
    agent = load_agent("coach", config_dir)
    prompt = await build_system_prompt(agent)
    assert "# AGENTS.md" in prompt
    assert "# IDENTITY.md" in prompt
    assert "Agent dispatch instructions." in prompt
    assert "---" in prompt


async def test_build_system_prompt_missing_file(workspace: Path) -> None:
    agent = AgentConfig(
        name="test",
        workspace=str(workspace),
        system_prompt_files=["MISSING.md", "IDENTITY.md"],
        model="claude-sonnet-4-6",
    )
    prompt = await build_system_prompt(agent)
    # Missing file is skipped, existing file is included
    assert "# IDENTITY.md" in prompt
    assert "MISSING.md" not in prompt


async def test_build_system_prompt_all_missing(workspace: Path) -> None:
    agent = AgentConfig(
        name="test",
        workspace=str(workspace),
        system_prompt_files=["NOPE.md"],
        model="claude-sonnet-4-6",
    )
    prompt = await build_system_prompt(agent)
    assert prompt == ""


def test_resolve_agent_for_channel(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    agent = resolve_agent_for_channel("9999", config_dir)
    assert agent is not None
    assert agent.name == "coach"


def test_resolve_agent_for_channel_not_found(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    agent = resolve_agent_for_channel("0000", config_dir)
    assert agent is None
