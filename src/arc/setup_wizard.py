"""First-run setup wizard for arc."""
import logging
import shutil
from pathlib import Path

import yaml

log = logging.getLogger("arc.setup")

_DEFAULT_CONFIG = """\
daemon:
  auto_start: true
  socket_path: ~/.arc/arc.sock
  pid_file: ~/.arc/daemon.pid
  log_level: info

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
  token_env: DISCORD_BOT_TOKEN
  guild_id: ""
  thread_mode: false
  rate_limit:
    messages_per_minute: 5

git:
  auto_pull: true
  auto_commit: true
  auto_push: false

timeouts:
  acpx_request: 300
  ollama_request: 120
  ipc_connect: 5

output:
  default_format: raw
  color: true

logging:
  log_routing: true
"""


def check_dependency(command: str) -> str | None:
    """Return the full path to command, or None if not found."""
    return shutil.which(command)


def check_all_deps() -> dict[str, str | None]:
    """Check all required and optional dependencies."""
    return {
        "acpx": check_dependency("acpx"),
        "claude": check_dependency("claude"),
        "git": check_dependency("git"),
        "node": check_dependency("node"),
    }


def create_arc_dirs(arc_dir: Path) -> None:
    """Create the ~/.arc directory structure."""
    for subdir in ("agents", "cron", "logs"):
        (arc_dir / subdir).mkdir(parents=True, exist_ok=True)


def create_default_config(arc_dir: Path) -> bool:
    """Write default config.yaml if it doesn't exist. Returns True if created."""
    config_path = arc_dir / "config.yaml"
    if config_path.exists():
        return False
    config_path.write_text(_DEFAULT_CONFIG)
    return True


def create_default_env(arc_dir: Path) -> bool:
    """Create empty .env with secure permissions if it doesn't exist."""
    env_path = arc_dir / ".env"
    if env_path.exists():
        return False
    env_path.touch(mode=0o600)
    return True


def write_discord_config(arc_dir: Path, token: str, guild_id: str) -> None:
    """Write Discord token to .env and enable Discord in config.yaml."""
    env_path = arc_dir / ".env"
    env_path.touch(mode=0o600)
    env_path.chmod(0o600)
    env_path.write_text(f"DISCORD_BOT_TOKEN={token}\n")

    config_path = arc_dir / "config.yaml"
    if not config_path.exists():
        return
    data = yaml.safe_load(config_path.read_text()) or {}
    data.setdefault("discord", {})
    data["discord"]["enabled"] = True
    data["discord"]["guild_id"] = guild_id
    config_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def setup_summary(arc_dir: Path, deps: dict[str, str | None]) -> dict:
    """Return a summary of the setup state."""
    config_path = arc_dir / "config.yaml"
    agents_dir = arc_dir / "agents"
    agents = list(agents_dir.glob("*.yaml")) if agents_dir.exists() else []
    return {
        "arc_dir": str(arc_dir),
        "config_exists": config_path.exists(),
        "agent_count": len(agents),
        "deps": deps,
    }
