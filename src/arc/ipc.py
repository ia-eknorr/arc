"""Unix socket IPC between the arc CLI and daemon.

Protocol: 4-byte big-endian unsigned int length prefix, then UTF-8 JSON payload.
"""
import asyncio
import json
import struct
from pathlib import Path

from arc.config import ArcConfig

_LENGTH_FMT = ">I"
_LENGTH_SIZE = struct.calcsize(_LENGTH_FMT)


async def send_message(writer: asyncio.StreamWriter, data: dict) -> None:
    """Write a length-prefixed JSON message to the stream."""
    payload = json.dumps(data).encode()
    writer.write(struct.pack(_LENGTH_FMT, len(payload)))
    writer.write(payload)
    await writer.drain()


async def recv_message(reader: asyncio.StreamReader) -> dict:
    """Read a length-prefixed JSON message from the stream."""
    length_bytes = await reader.readexactly(_LENGTH_SIZE)
    length = struct.unpack(_LENGTH_FMT, length_bytes)[0]
    payload = await reader.readexactly(length)
    return json.loads(payload)


async def connect(config: ArcConfig) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """Connect to the daemon socket. Returns None if the daemon is not running."""
    socket_path = Path(config.daemon.socket_path).expanduser()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(path=str(socket_path)),
            timeout=config.timeouts.ipc_connect,
        )
        return reader, writer
    except (FileNotFoundError, ConnectionRefusedError, OSError, asyncio.TimeoutError):
        return None


async def request(config: ArcConfig, data: dict) -> dict | None:
    """Send a request to the daemon and return its response.

    Returns None if the daemon is not reachable.
    """
    conn = await connect(config)
    if conn is None:
        return None
    reader, writer = conn
    try:
        await send_message(writer, data)
        return await recv_message(reader)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
