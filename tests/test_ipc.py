import asyncio

import pytest

from arc.ipc import recv_message, send_message


async def _make_stream_pair() -> tuple:
    """Create an in-process stream pair for testing."""
    server_reader, client_writer = await asyncio.open_connection("127.0.0.1", 0)
    # Use a pipe instead: asyncio.StreamReader/StreamWriter backed by a socket pair
    # Actually use asyncio.Queue-backed approach via unix socket on a tmp path
    pass


# Use a loopback TCP connection for stream pair in tests
async def _loopback_pair(tmp_path):
    """Start a throwaway TCP server and connect to it, returning both ends."""
    received = []

    async def handler(reader, writer):
        received.append((reader, writer))

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    addr = server.sockets[0].getsockname()
    client_reader, client_writer = await asyncio.open_connection(*addr)

    # Wait for server to accept
    while not received:
        await asyncio.sleep(0)

    server_reader, server_writer = received[0]
    return client_reader, client_writer, server_reader, server_writer, server


async def test_send_recv_round_trip(tmp_path) -> None:
    cr, cw, sr, sw, server = await _loopback_pair(tmp_path)
    try:
        data = {"status": "ok", "result": "hello from daemon"}
        await send_message(cw, data)
        received = await recv_message(sr)
        assert received == data
    finally:
        cw.close()
        sw.close()
        server.close()


async def test_send_recv_large_payload(tmp_path) -> None:
    cr, cw, sr, sw, server = await _loopback_pair(tmp_path)
    try:
        big = {"content": "x" * 100_000, "nested": {"a": list(range(1000))}}
        await send_message(cw, big)
        received = await recv_message(sr)
        assert received == big
    finally:
        cw.close()
        sw.close()
        server.close()


async def test_multiple_messages(tmp_path) -> None:
    cr, cw, sr, sw, server = await _loopback_pair(tmp_path)
    try:
        messages = [{"i": i, "v": f"msg-{i}"} for i in range(5)]
        for msg in messages:
            await send_message(cw, msg)
        for expected in messages:
            received = await recv_message(sr)
            assert received == expected
    finally:
        cw.close()
        sw.close()
        server.close()


async def test_connect_returns_none_when_no_daemon(tmp_path) -> None:
    from arc.config import ArcConfig, DaemonConfig
    from arc.ipc import connect

    cfg = ArcConfig()
    cfg.daemon = DaemonConfig(socket_path=str(tmp_path / "nonexistent.sock"))
    result = await connect(cfg)
    assert result is None


async def test_request_returns_none_when_no_daemon(tmp_path) -> None:
    from arc.config import ArcConfig, DaemonConfig
    from arc.ipc import request

    cfg = ArcConfig()
    cfg.daemon = DaemonConfig(socket_path=str(tmp_path / "nonexistent.sock"))
    result = await request(cfg, {"prompt": "hello"})
    assert result is None
