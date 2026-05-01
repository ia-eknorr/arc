import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from arc.config import ArcConfig, DaemonConfig, GitConfig, LoggingConfig
from arc.daemon import ArcDaemon
from arc.types import CronJob, DispatchResult


@pytest.fixture
def daemon_config() -> ArcConfig:
    # Unix sockets have a ~104-char path limit on macOS. Use /tmp directly.
    pid = os.getpid()
    cfg = ArcConfig()
    cfg.daemon = DaemonConfig(
        auto_start=False,
        socket_path=f"/tmp/arc-test-{pid}.sock",
        pid_file=f"/tmp/arc-test-{pid}.pid",
        log_level="warning",
    )
    cfg.git = GitConfig(auto_pull=False)
    cfg.logging = LoggingConfig(log_routing=False)
    return cfg


@pytest.fixture
def daemon(daemon_config: ArcConfig) -> ArcDaemon:
    return ArcDaemon(daemon_config)


# --- handle_request ---


async def test_handle_request_missing_agent(daemon: ArcDaemon) -> None:
    response = await daemon.handle_request({"prompt": "hello"})
    assert response["status"] == "error"
    assert "No agent" in response["error"]


async def test_handle_request_unknown_agent(daemon: ArcDaemon) -> None:
    response = await daemon.handle_request({"prompt": "hello", "agent": "ghost"})
    assert response["status"] == "error"
    assert "ghost" in response["error"]


async def test_handle_request_success(
    daemon: ArcDaemon, config_dir: Path, coach_agent_yaml: dict, workspace: Path
) -> None:
    result = DispatchResult("Coach response", "claude-sonnet-4-6", "acpx")
    with patch("arc.daemon.load_agent") as mock_load, \
         patch("arc.daemon.dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_load.return_value = coach_agent_yaml  # any truthy value
        mock_dispatch.return_value = result

        # load_agent needs to return a real AgentConfig
        from arc.agents import load_agent
        mock_load.side_effect = lambda name, _: load_agent(name, config_dir)

        response = await daemon.handle_request({"prompt": "hello", "agent": "coach"})

    assert response["status"] == "ok"
    assert response["result"] == "Coach response"


async def test_handle_request_cli_is_one_shot(
    daemon: ArcDaemon, config_dir: Path, coach_agent_yaml: dict, workspace: Path
) -> None:
    from arc.agents import load_agent as real_load

    with patch("arc.daemon.load_agent", side_effect=lambda n, _: real_load(n, config_dir)), \
         patch("arc.daemon.dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = DispatchResult("ok", "claude-sonnet-4-6", "acpx")
        await daemon.handle_request({"prompt": "hi", "agent": "coach", "source": "cli"})

    _, kwargs = mock_dispatch.call_args
    assert kwargs.get("one_shot") is True
    assert kwargs.get("session_name") is None


async def test_handle_request_discord_uses_session(
    daemon: ArcDaemon, config_dir: Path, coach_agent_yaml: dict, workspace: Path
) -> None:
    from arc.agents import load_agent as real_load

    with patch("arc.daemon.load_agent", side_effect=lambda n, _: real_load(n, config_dir)), \
         patch("arc.daemon.dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = DispatchResult("ok", "claude-sonnet-4-6", "acpx")
        await daemon.handle_request({
            "prompt": "hi",
            "agent": "coach",
            "source": "discord",
            "thread_id": "12345",
        })

    _, kwargs = mock_dispatch.call_args
    assert kwargs.get("one_shot") is False
    assert kwargs.get("session_name") == "coach-12345"


# --- status op ---


async def test_handle_status_op_returns_structure(daemon: ArcDaemon) -> None:
    response = await daemon.handle_request({"op": "status", "source": "cli"})
    assert response["status"] == "ok"
    assert "daemon" in response
    assert "agents" in response
    assert "cron" in response


async def test_handle_status_includes_pid(daemon: ArcDaemon, tmp_path: Path) -> None:
    pid_file = tmp_path / "arc.pid"
    pid_file.write_text("9999")
    daemon.config.daemon.pid_file = str(pid_file)
    response = await daemon.handle_request({"op": "status"})
    assert response["daemon"]["pid"] == 9999


async def test_handle_status_agents_listed(
    daemon: ArcDaemon, config_dir: Path, coach_agent_yaml: dict
) -> None:
    with patch("arc.agents.list_agents") as mock_list:
        from arc.agents import load_agent
        mock_list.return_value = [load_agent("coach", config_dir)]
        response = await daemon.handle_request({"op": "status"})
    assert any(a["name"] == "coach" for a in response["agents"])


async def test_handle_status_cron_listed(daemon: ArcDaemon) -> None:
    from arc.cron import CronManager
    from arc.types import CronJob

    cron = CronManager(daemon.config)
    job = CronJob(name="daily", schedule="0 7 * * *", agent="coach", prompt="go")
    cron._jobs = [job]
    cron._scheduler.start()
    cron._scheduler.add_job(lambda: None, "cron", id="daily")
    daemon._cron = cron

    response = await daemon.handle_request({"op": "status"})
    cron.stop()
    assert any(j["name"] == "daily" for j in response["cron"])


async def test_handle_status_does_not_require_agent(daemon: ArcDaemon) -> None:
    response = await daemon.handle_request({"op": "status"})
    assert response["status"] == "ok"


# --- model_overrides ---


def test_set_model_override(daemon: ArcDaemon) -> None:
    daemon.set_model_override("chan-1", "claude-haiku-4-5")
    assert daemon.model_overrides["chan-1"] == "claude-haiku-4-5"


def test_clear_model_override(daemon: ArcDaemon) -> None:
    daemon.set_model_override("chan-1", "claude-haiku-4-5")
    daemon.set_model_override("chan-1", None)
    assert "chan-1" not in daemon.model_overrides


async def test_model_override_applied_to_discord_request(
    daemon: ArcDaemon, config_dir: Path, coach_agent_yaml: dict, workspace: Path
) -> None:
    from arc.agents import load_agent as real_load

    daemon.set_model_override("chan-99", "claude-haiku-4-5")

    with patch("arc.daemon.load_agent", side_effect=lambda n, _: real_load(n, config_dir)), \
         patch("arc.daemon.dispatch", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = DispatchResult("ok", "claude-haiku-4-5", "acpx")
        await daemon.handle_request({
            "prompt": "hi",
            "agent": "coach",
            "source": "discord",
            "thread_id": "999",
            "channel_id": "chan-99",
        })

    _, kwargs = mock_dispatch.call_args
    assert kwargs.get("model_override") == "claude-haiku-4-5"


# --- cron ---


async def test_run_cron_job_success(daemon: ArcDaemon) -> None:
    job = CronJob(
        name="test-job",
        schedule="0 7 * * *",
        agent="coach",
        prompt="daily brief",
        notify=None,
    )
    with patch.object(daemon, "handle_request", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = {"status": "ok", "result": "done"}
        await daemon.run_cron_job(job)

    mock_handle.assert_awaited_once()
    req = mock_handle.call_args[0][0]
    assert req["source"] == "cron"
    assert req["prompt"] == "daily brief"


async def test_run_cron_job_discord_on_urgent(daemon: ArcDaemon) -> None:
    job = CronJob(
        name="heartbeat",
        schedule="*/30 * * * *",
        agent="coach",
        prompt="check flags",
        notify="discord_on_urgent",
    )
    with patch.object(daemon, "handle_request", new_callable=AsyncMock) as mock_handle, \
         patch.object(daemon, "_notify_discord", new_callable=AsyncMock) as mock_notify:
        mock_handle.return_value = {"status": "ok", "result": "URGENT: elbow flare"}
        await daemon.run_cron_job(job)

    mock_notify.assert_awaited_once()


async def test_run_cron_job_no_notify_when_not_urgent(daemon: ArcDaemon) -> None:
    job = CronJob(
        name="heartbeat",
        schedule="*/30 * * * *",
        agent="coach",
        prompt="check flags",
        notify="discord_on_urgent",
    )
    with patch.object(daemon, "handle_request", new_callable=AsyncMock) as mock_handle, \
         patch.object(daemon, "_notify_discord", new_callable=AsyncMock) as mock_notify:
        mock_handle.return_value = {"status": "ok", "result": "All clear."}
        await daemon.run_cron_job(job)

    mock_notify.assert_not_awaited()


# --- socket lifecycle ---


async def test_daemon_start_and_shutdown(daemon: ArcDaemon) -> None:
    """Daemon binds socket, accepts a connection, then shuts down cleanly."""
    socket_path = Path(daemon.config.daemon.socket_path)

    start_task = asyncio.create_task(daemon.start())
    await asyncio.sleep(0.1)

    assert socket_path.exists()

    # Connect and send a request
    reader, writer = await asyncio.open_unix_connection(path=str(socket_path))
    from arc import ipc
    with patch.object(daemon, "handle_request", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = {"status": "ok", "result": "pong"}
        await ipc.send_message(writer, {"prompt": "ping", "agent": "any"})
        response = await ipc.recv_message(reader)
    writer.close()

    assert response["status"] == "ok"
    assert response["result"] == "pong"

    await daemon.shutdown()
    start_task.cancel()
    try:
        await start_task
    except (asyncio.CancelledError, Exception):
        pass

    assert not socket_path.exists()
