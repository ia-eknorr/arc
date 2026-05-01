import asyncio
import logging
import os
import signal
from pathlib import Path

from arc import ipc
from arc.agents import load_agent
from arc.config import ArcConfig, load_config
from arc.dispatcher import DispatchError, dispatch
from arc.types import CronJob
from arc.utils import append_jsonl, configure_logging, git_pull, load_dotenv, now_iso, write_pid

log = logging.getLogger("arc.daemon")


class ArcDaemon:
    def __init__(self, config: ArcConfig):
        self.config = config
        self.model_overrides: dict[str, str] = {}
        self._server: asyncio.AbstractServer | None = None
        self._discord_bot = None
        self._discord_task: asyncio.Task | None = None
        self._cron: "CronManager | None" = None

    async def start(self) -> None:
        """Start the daemon: write PID, bind socket, register signals, serve."""
        configure_logging(self.config.daemon.log_level)

        config_dir = Path(self.config.daemon.pid_file).expanduser().parent
        load_dotenv(config_dir / ".env")

        pid_path = Path(self.config.daemon.pid_file).expanduser()
        write_pid(pid_path)

        socket_path = Path(self.config.daemon.socket_path).expanduser()
        socket_path.unlink(missing_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(socket_path),
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        if self.config.discord.enabled:
            self._start_discord_bot()

        from arc.cron import CronManager
        self._cron = CronManager(self.config)
        self._cron.start(self.run_cron_job)

        log.info(f"arc daemon started (pid={pid_path.read_text().strip()}, socket={socket_path})")

        async with self._server:
            await self._server.serve_forever()

    def _start_discord_bot(self) -> None:
        """Start the Discord bot as a background task."""
        from arc.discord_bridge import ArcDiscordBot

        token = os.environ.get(self.config.discord.token_env, "")
        if not token:
            log.error(
                f"Discord enabled but {self.config.discord.token_env} is not set. "
                "Add it to ~/.arc/.env"
            )
            return

        self._discord_bot = ArcDiscordBot(self.config, self)

        async def _run() -> None:
            try:
                await self._discord_bot.start(token)
            except Exception as e:
                log.error(f"Discord bot exited: {e}")

        self._discord_task = asyncio.create_task(_run())

    async def shutdown(self) -> None:
        """Graceful shutdown: close socket, stop Discord bot, remove PID and socket files."""
        log.info("arc daemon shutting down")

        if self._cron:
            self._cron.stop()

        if self._discord_bot and not self._discord_bot.is_closed():
            await self._discord_bot.close()
        if self._discord_task:
            self._discord_task.cancel()

        if self._server:
            self._server.close()

        for path_str in (self.config.daemon.socket_path, self.config.daemon.pid_file):
            Path(path_str).expanduser().unlink(missing_ok=True)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one IPC connection: read request, dispatch, send response."""
        try:
            request = await ipc.recv_message(reader)
            response = await self.handle_request(request)
            await ipc.send_message(writer, response)
        except Exception as e:
            log.exception("Error handling IPC request")
            try:
                await ipc.send_message(writer, {"status": "error", "error": str(e)})
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_status(self) -> dict:
        """Return daemon state, configured agents, and cron next-run times."""
        from arc.agents import list_agents

        agents = [
            {
                "name": a.name,
                "model": a.model,
                "workspace": a.workspace,
                "discord_channel": a.discord.get("channel_id"),
            }
            for a in list_agents()
        ]

        cron: list[dict] = []
        if self._cron:
            next_times = self._cron.next_run_times()
            for job in self._cron.get_jobs():
                cron.append({
                    "name": job.name,
                    "schedule": job.schedule,
                    "enabled": job.enabled,
                    "next_run": next_times.get(job.name),
                })

        pid_path = Path(self.config.daemon.pid_file).expanduser()
        pid = int(pid_path.read_text().strip()) if pid_path.exists() else None

        return {
            "status": "ok",
            "daemon": {"pid": pid, "socket": self.config.daemon.socket_path},
            "agents": agents,
            "cron": cron,
        }

    async def handle_request(self, request: dict) -> dict:
        """Central request handler shared by CLI, Discord, and cron sources."""
        if request.get("op") == "status":
            return await self._handle_status()

        prompt = request.get("prompt", "")
        agent_name = request.get("agent")
        model_override = request.get("model")
        source = request.get("source", "cli")
        thread_id = request.get("thread_id")
        channel_id = request.get("channel_id")

        if not agent_name:
            return {"status": "error", "error": "No agent specified."}

        try:
            agent = load_agent(agent_name, None)
        except FileNotFoundError as e:
            return {"status": "error", "error": str(e)}

        # Discord per-channel model override (sticky until reset)
        if not model_override and channel_id and channel_id in self.model_overrides:
            model_override = self.model_overrides[channel_id]

        # Discord threads use persistent named sessions; everything else is one-shot.
        if source == "discord" and thread_id:
            session_name = f"{agent.name}-{thread_id}"
            one_shot = False
        else:
            session_name = None
            one_shot = True

        if agent.workspace and self.config.git.auto_pull:
            await git_pull(agent.workspace)

        try:
            result = await dispatch(
                prompt=prompt,
                agent=agent,
                model_override=model_override,
                session_name=session_name,
                one_shot=one_shot,
                config=self.config,
            )
        except DispatchError as e:
            return {"status": "error", "error": str(e)}

        if self.config.logging.log_routing:
            append_jsonl(
                Path(self.config.daemon.socket_path).expanduser().parent / "logs" / "routing.jsonl",
                {
                    "timestamp": now_iso(),
                    "agent": agent.name,
                    "model": result.model_used,
                    "dispatch_type": result.dispatch_type,
                    "source": source,
                    "one_shot": one_shot,
                    "prompt_preview": prompt[:100],
                },
            )

        return {"status": "ok", "result": result.output}

    async def run_cron_job(self, job: CronJob) -> None:
        """Execute a scheduled cron job and notify Discord if configured."""
        log.info(f"cron: running {job.name}")
        try:
            result = await self.handle_request(
                {
                    "prompt": job.prompt,
                    "agent": job.agent,
                    "model": job.model,
                    "source": "cron",
                }
            )

            if result["status"] == "ok":
                output = result["result"]
                should_notify = job.notify == "discord" or (
                    job.notify == "discord_on_urgent" and "urgent" in output.lower()
                )
                if should_notify:
                    await self._notify_discord(output, job.agent)

            append_jsonl(
                Path(self.config.daemon.socket_path).expanduser().parent / "logs" / "cron.jsonl",
                {
                    "timestamp": now_iso(),
                    "job": job.name,
                    "status": result["status"],
                    "output_preview": result.get("result", result.get("error", ""))[:200],
                },
            )
        except Exception as e:
            log.error(f"cron: {job.name} failed: {e}")

    async def _notify_discord(self, content: str, agent_name: str) -> None:
        """Send content to the agent's configured Discord channel."""
        if self._discord_bot and not self._discord_bot.is_closed():
            await self._discord_bot.send_to_default_channel(content, agent_name)
        else:
            log.debug(f"Discord notify skipped (bot not running): agent={agent_name}")

    def set_model_override(self, channel_id: str, model: str | None) -> None:
        """Set or clear a sticky model override for a Discord channel."""
        if model:
            self.model_overrides[channel_id] = model
        else:
            self.model_overrides.pop(channel_id, None)


def run_daemon() -> None:
    """Entry point for running the daemon (called by `arc daemon start --foreground`)."""
    config = load_config()
    daemon = ArcDaemon(config)
    asyncio.run(daemon.start())
