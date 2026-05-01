from pathlib import Path
from unittest.mock import patch

import yaml

from arc.setup_wizard import (
    check_all_deps,
    create_arc_dirs,
    create_default_config,
    create_default_env,
    setup_summary,
    write_discord_config,
)


def test_create_arc_dirs(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    create_arc_dirs(arc_dir)
    assert (arc_dir / "agents").is_dir()
    assert (arc_dir / "cron").is_dir()
    assert (arc_dir / "logs").is_dir()


def test_create_default_config_creates(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    assert create_default_config(arc_dir) is True
    cfg = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert cfg["daemon"]["auto_start"] is True
    assert cfg["discord"]["enabled"] is False


def test_create_default_config_skips_existing(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    (arc_dir / "config.yaml").write_text("existing: true\n")
    assert create_default_config(arc_dir) is False
    assert "existing" in (arc_dir / "config.yaml").read_text()


def test_create_default_env(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    assert create_default_env(arc_dir) is True
    env_path = arc_dir / ".env"
    assert env_path.exists()
    assert oct(env_path.stat().st_mode)[-3:] == "600"


def test_create_default_env_skips_existing(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    (arc_dir / ".env").write_text("EXISTING=1\n")
    assert create_default_env(arc_dir) is False


def test_write_discord_config(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    create_default_config(arc_dir)
    write_discord_config(arc_dir, "token-abc", "guild-123")
    cfg = yaml.safe_load((arc_dir / "config.yaml").read_text())
    assert cfg["discord"]["enabled"] is True
    assert cfg["discord"]["guild_id"] == "guild-123"
    env = (arc_dir / ".env").read_text()
    assert "token-abc" in env


def test_check_all_deps_finds_git() -> None:
    deps = check_all_deps()
    assert deps["git"] is not None


def test_check_all_deps_missing() -> None:
    with patch("arc.setup_wizard.shutil.which", return_value=None):
        deps = check_all_deps()
    assert all(v is None for v in deps.values())


def test_setup_summary(tmp_path: Path) -> None:
    arc_dir = tmp_path / ".arc"
    create_arc_dirs(arc_dir)
    create_default_config(arc_dir)
    (arc_dir / "agents" / "coach.yaml").write_text("name: coach\n")
    summary = setup_summary(arc_dir, {"acpx": "/usr/bin/acpx", "claude": None})
    assert summary["config_exists"] is True
    assert summary["agent_count"] == 1
    assert summary["deps"]["acpx"] == "/usr/bin/acpx"
