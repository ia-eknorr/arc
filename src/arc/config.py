from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class DaemonConfig:
    auto_start: bool = True
    socket_path: str = "~/.arc/arc.sock"
    log_level: str = "info"
    pid_file: str = "~/.arc/daemon.pid"


@dataclass
class AcpxConfig:
    command: str = "acpx"
    default_agent: str = "claude"
    session_ttl: int = 300
    output_format: str = "text"


@dataclass
class OllamaEndpoint:
    url: str


@dataclass
class OllamaConfig:
    endpoints: dict[str, OllamaEndpoint] = field(
        default_factory=lambda: {
            "local": OllamaEndpoint(url="http://localhost:11434/v1"),
        }
    )


@dataclass
class DiscordRateLimit:
    messages_per_minute: int = 5


@dataclass
class DiscordConfig:
    enabled: bool = False
    token_env: str = "DISCORD_BOT_TOKEN"
    guild_id: str = ""
    thread_mode: bool = True
    rate_limit: DiscordRateLimit = field(default_factory=DiscordRateLimit)


@dataclass
class GitConfig:
    auto_pull: bool = True
    auto_commit: bool = True
    auto_push: bool = False


@dataclass
class TimeoutsConfig:
    acpx_request: int = 300
    ollama_request: int = 120
    ipc_connect: int = 5


@dataclass
class OutputConfig:
    default_format: str = "raw"
    color: bool = True


@dataclass
class LoggingConfig:
    log_routing: bool = True


@dataclass
class ArcConfig:
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    acpx: AcpxConfig = field(default_factory=AcpxConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    git: GitConfig = field(default_factory=GitConfig)
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def get_config_dir() -> Path:
    return Path("~/.arc").expanduser()


def _parse_ollama(data: dict) -> OllamaConfig:
    endpoints = {}
    for name, ep in data.get("endpoints", {}).items():
        endpoints[name] = OllamaEndpoint(url=ep["url"])
    return OllamaConfig(endpoints=endpoints or OllamaConfig().endpoints)


def _parse_discord(data: dict) -> DiscordConfig:
    rl_data = data.get("rate_limit", {})
    return DiscordConfig(
        enabled=data.get("enabled", False),
        token_env=data.get("token_env", "DISCORD_BOT_TOKEN"),
        guild_id=data.get("guild_id", ""),
        thread_mode=data.get("thread_mode", True),
        rate_limit=DiscordRateLimit(
            messages_per_minute=rl_data.get("messages_per_minute", 5)
        ),
    )


def _from_dict(data: dict) -> ArcConfig:
    """Build ArcConfig from a raw YAML dict."""
    d = data.get("daemon", {})
    a = data.get("acpx", {})
    o = data.get("ollama", {})
    dc = data.get("discord", {})
    g = data.get("git", {})
    t = data.get("timeouts", {})
    out = data.get("output", {})
    log = data.get("logging", {})

    return ArcConfig(
        daemon=DaemonConfig(
            auto_start=d.get("auto_start", True),
            socket_path=d.get("socket_path", "~/.arc/arc.sock"),
            log_level=d.get("log_level", "info"),
            pid_file=d.get("pid_file", "~/.arc/daemon.pid"),
        ),
        acpx=AcpxConfig(
            command=a.get("command", "acpx"),
            default_agent=a.get("default_agent", "claude"),
            session_ttl=a.get("session_ttl", 300),
            output_format=a.get("output_format", "text"),
        ),
        ollama=_parse_ollama(o),
        discord=_parse_discord(dc),
        git=GitConfig(
            auto_pull=g.get("auto_pull", True),
            auto_commit=g.get("auto_commit", True),
            auto_push=g.get("auto_push", False),
        ),
        timeouts=TimeoutsConfig(
            acpx_request=t.get("acpx_request", 300),
            ollama_request=t.get("ollama_request", 120),
            ipc_connect=t.get("ipc_connect", 5),
        ),
        output=OutputConfig(
            default_format=out.get("default_format", "raw"),
            color=out.get("color", True),
        ),
        logging=LoggingConfig(
            log_routing=log.get("log_routing", True),
        ),
    )


_DEFAULT_CONFIG_YAML = """\
daemon:
  auto_start: true
  socket_path: ~/.arc/arc.sock
  log_level: info
  pid_file: ~/.arc/daemon.pid

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
  thread_mode: true
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


def create_default_config(config_dir: Path | None = None) -> Path:
    """Write default config.yaml if it does not exist. Returns the config file path."""
    config_dir = config_dir or get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agents").mkdir(exist_ok=True)
    (config_dir / "cron").mkdir(exist_ok=True)
    (config_dir / "logs").mkdir(exist_ok=True)

    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_DEFAULT_CONFIG_YAML)
    return config_file


def load_config(config_dir: Path | None = None) -> ArcConfig:
    """Load config from config_dir/config.yaml, creating defaults if absent."""
    config_dir = config_dir or get_config_dir()
    config_file = config_dir / "config.yaml"

    if not config_file.exists():
        create_default_config(config_dir)
        return ArcConfig()

    try:
        data = yaml.safe_load(config_file.read_text()) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Corrupt config file {config_file}: {e}") from e

    cfg = _from_dict(data)

    # When daemon paths are not set in config.yaml, resolve them relative to
    # config_dir so that non-default config dirs work correctly.
    d = data.get("daemon", {})
    if "pid_file" not in d:
        cfg.daemon.pid_file = str(config_dir / "daemon.pid")
    if "socket_path" not in d:
        cfg.daemon.socket_path = str(config_dir / "arc.sock")

    return cfg
