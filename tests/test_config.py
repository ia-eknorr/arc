from pathlib import Path

import pytest

from arc.config import ArcConfig, create_default_config, load_config


def test_load_config_defaults(config_dir: Path) -> None:
    cfg = load_config(config_dir)
    assert isinstance(cfg, ArcConfig)
    assert cfg.daemon.log_level == "warning"
    assert cfg.acpx.command == "acpx"
    assert cfg.timeouts.acpx_request == 30


def test_load_config_ollama_endpoints(config_dir: Path) -> None:
    cfg = load_config(config_dir)
    assert "local" in cfg.ollama.endpoints
    assert cfg.ollama.endpoints["local"].url == "http://localhost:11434/v1"
    assert "kyle" in cfg.ollama.endpoints
    assert cfg.ollama.endpoints["kyle"].url == "http://kyle.local:11434/v1"


def test_load_config_creates_defaults_when_missing(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    cfg = load_config(arc_dir)
    assert isinstance(cfg, ArcConfig)
    assert cfg.daemon.auto_start is True
    assert (arc_dir / "config.yaml").exists()


def test_create_default_config_idempotent(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    path1 = create_default_config(arc_dir)
    content1 = path1.read_text()
    path2 = create_default_config(arc_dir)
    content2 = path2.read_text()
    assert content1 == content2


def test_create_default_config_creates_dirs(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    create_default_config(arc_dir)
    assert (arc_dir / "agents").is_dir()
    assert (arc_dir / "cron").is_dir()
    assert (arc_dir / "logs").is_dir()


def test_load_config_corrupt_yaml(config_dir: Path) -> None:
    (config_dir / "config.yaml").write_text("daemon: {broken: [yaml}")
    with pytest.raises(ValueError, match="Corrupt config"):
        load_config(config_dir)


def test_load_config_discord_fields(config_dir: Path) -> None:
    (config_dir / "config.yaml").write_text(
        "discord:\n  enabled: true\n  guild_id: '9876'\n  thread_mode: false\n"
    )
    cfg = load_config(config_dir)
    assert cfg.discord.enabled is True
    assert cfg.discord.guild_id == "9876"
    assert cfg.discord.thread_mode is False
