import logging
from pathlib import Path

import yaml

from arc.types import AgentConfig

log = logging.getLogger("arc")


def load_agent(name: str, config_dir: Path | None = None) -> AgentConfig:
    """Load agent config from <config_dir>/agents/<name>.yaml."""
    agents_dir = (config_dir or Path("~/.arc").expanduser()) / "agents"
    path = agents_dir / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in sorted(agents_dir.glob("*.yaml"))]
        hint = f" Available: {', '.join(available)}" if available else ""
        raise FileNotFoundError(f"Agent '{name}' not found at {path}.{hint}")
    data = yaml.safe_load(path.read_text())
    return AgentConfig(**data)


def list_agents(config_dir: Path | None = None) -> list[AgentConfig]:
    """List all configured agents."""
    agents_dir = (config_dir or Path("~/.arc").expanduser()) / "agents"
    if not agents_dir.exists():
        return []
    agents = []
    for path in sorted(agents_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
            agents.append(AgentConfig(**data))
        except Exception as e:
            log.warning(f"Skipping malformed agent file {path}: {e}")
    return agents


async def build_system_prompt(agent: AgentConfig) -> str:
    """Concatenate all agent identity files into a single system prompt."""
    parts = []
    for filename in agent.system_prompt_files:
        path = Path(agent.workspace) / filename
        if path.exists():
            parts.append(f"# {filename}\n\n{path.read_text()}")
        else:
            log.warning(f"Agent '{agent.name}': identity file not found: {path}")
    return "\n\n---\n\n".join(parts)


def resolve_agent_for_channel(
    channel_id: str, config_dir: Path | None = None
) -> AgentConfig | None:
    """Find the agent bound to a Discord channel."""
    for agent in list_agents(config_dir):
        if agent.discord.get("channel_id") == channel_id:
            return agent
    return None
