import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("arc")


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: str | Path, data: dict) -> None:
    """Append a JSON record to a JSONL log file."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(data) + "\n")


def split_message(text: str, max_length: int = 2000) -> list[str]:
    """Split a long string into chunks that fit within max_length."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Try to split on a newline boundary
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def write_pid(pid_file: str | Path) -> None:
    """Write the current process PID to pid_file."""
    p = Path(pid_file).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(os.getpid()))


def read_pid(pid_file: str | Path) -> int | None:
    """Read the PID from pid_file. Returns None if the file does not exist."""
    p = Path(pid_file).expanduser()
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except ValueError:
        return None


def is_process_running(pid: int) -> bool:
    """Return True if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


async def git_pull(workspace: str | Path) -> bool:
    """Run git pull in workspace. Returns True on success."""
    workspace = str(workspace)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", workspace, "pull", "--ff-only",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            log.warning(f"git pull failed in {workspace}: {stderr.decode().strip()}")
            return False
        return True
    except asyncio.TimeoutError:
        log.warning(f"git pull timed out in {workspace}")
        return False
    except Exception as e:
        log.warning(f"git pull error in {workspace}: {e}")
        return False


def load_dotenv(env_file: str | Path) -> None:
    """Load KEY=VALUE pairs from env_file into os.environ. Silently skips if missing."""
    p = Path(env_file).expanduser()
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def configure_logging(level: str = "info") -> None:
    """Configure root logger for arc."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        level=numeric,
    )
