"""Discord bot bridge for arc daemon."""
import collections
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from arc.agents import load_agent, list_agents, resolve_agent_for_channel
from arc.config import ArcConfig
from arc.utils import split_message

if TYPE_CHECKING:
    from arc.daemon import ArcDaemon

log = logging.getLogger("arc.discord")


class _RateLimiter:
    """Sliding-window rate limiter per channel."""

    def __init__(self, messages_per_minute: int) -> None:
        self._limit = messages_per_minute
        self._timestamps: dict[str, collections.deque] = {}

    def is_allowed(self, channel_id: str) -> bool:
        now = time.monotonic()
        dq = self._timestamps.setdefault(channel_id, collections.deque())
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= self._limit:
            return False
        dq.append(now)
        return True


def _format_delta(dt: datetime) -> str:
    delta = dt - datetime.now(dt.tzinfo)
    mins = max(0, int(delta.total_seconds() / 60))
    if mins < 60:
        return f"in {mins}m"
    return f"in {mins // 60}h {mins % 60}m"


class ArcDiscordBot(discord.Client):
    def __init__(self, config: ArcConfig, daemon: "ArcDaemon") -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.daemon = daemon
        self._rate_limiter = _RateLimiter(config.discord.rate_limit.messages_per_minute)
        self.tree = app_commands.CommandTree(self)
        self._register_slash_commands()

    def _log_path(self, name: str) -> Path:
        return Path(self.config.daemon.socket_path).expanduser().parent / "logs" / f"{name}.jsonl"

    def _register_slash_commands(self) -> None:

        # --- /model ---

        @self.tree.command(name="model", description="Switch or view the active model for this channel")
        @app_commands.describe(model="Model to switch to, or 'reset' to restore the agent default")
        async def model_command(interaction: discord.Interaction, model: str = "") -> None:
            channel_id = str(interaction.channel_id)
            agent = resolve_agent_for_channel(channel_id, None)
            if not agent and isinstance(interaction.channel, discord.Thread):
                agent = resolve_agent_for_channel(str(interaction.channel.parent_id), None)
            if not agent:
                await interaction.response.send_message(
                    "No agent configured for this channel.", ephemeral=True
                )
                return

            if not model:
                current = self.daemon.model_overrides.get(channel_id, agent.model)
                await interaction.response.send_message(
                    f"Current model: `{current}`", ephemeral=True
                )
            elif model == "reset":
                self.daemon.set_model_override(channel_id, None)
                await interaction.response.send_message("Model reset to agent default.")
            elif model in (agent.allowed_models or []):
                self.daemon.set_model_override(channel_id, model)
                await interaction.response.send_message(f"Model set to `{model}`.")
            else:
                allowed = ", ".join(agent.allowed_models or ["(any)"])
                await interaction.response.send_message(
                    f"Model `{model}` not allowed here. Options: {allowed}", ephemeral=True
                )

        @model_command.autocomplete("model")
        async def model_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            channel_id = str(interaction.channel_id)
            agent = resolve_agent_for_channel(channel_id, None)
            if not agent and isinstance(interaction.channel, discord.Thread):
                agent = resolve_agent_for_channel(str(interaction.channel.parent_id), None)

            options = ["reset"] + (agent.allowed_models if agent and agent.allowed_models else [])
            return [
                app_commands.Choice(name=m, value=m)
                for m in options
                if current.lower() in m.lower()
            ][:25]

        # --- /status ---

        @self.tree.command(name="status", description="Show daemon status, agents, and next cron runs")
        async def status_command(interaction: discord.Interaction) -> None:
            data = await self.daemon._handle_status()
            lines = [
                f"**daemon** pid={data['daemon']['pid']} `{data['daemon']['socket']}`",
                "",
                "**agents**",
            ]
            for a in data["agents"]:
                ch = f" | <#{a['discord_channel']}>" if a["discord_channel"] else ""
                lines.append(f"  `{a['name']}` — {a['model']}{ch}")

            if data["cron"]:
                lines += ["", "**cron**"]
                for c in data["cron"]:
                    if not c["enabled"]:
                        next_str = "disabled"
                    elif c["next_run"]:
                        next_str = _format_delta(datetime.fromisoformat(c["next_run"]))
                    else:
                        next_str = "unknown"
                    lines.append(f"  `{c['name']}` — {next_str}")

            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # --- /agents ---

        @self.tree.command(name="agents", description="List configured agents and their bound channels")
        async def agents_command(interaction: discord.Interaction) -> None:
            agents = list_agents()
            if not agents:
                await interaction.response.send_message("No agents configured.", ephemeral=True)
                return
            lines = []
            for a in agents:
                ch = a.discord.get("channel_id", "")
                ch_str = f" | <#{ch}>" if ch else ""
                lines.append(f"**{a.name}** — `{a.model}`{ch_str}\n  `{a.workspace}`")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # --- /history ---

        @self.tree.command(name="history", description="Show recent routing log entries")
        @app_commands.describe(last="Number of entries to show (default 5)")
        async def history_command(interaction: discord.Interaction, last: int = 5) -> None:
            log_path = self._log_path("routing")
            if not log_path.exists():
                await interaction.response.send_message("No routing log found.", ephemeral=True)
                return
            raw = [l for l in log_path.read_text().strip().splitlines() if l][-last:]
            if not raw:
                await interaction.response.send_message("No history yet.", ephemeral=True)
                return
            lines = []
            for line in raw:
                entry = json.loads(line)
                ts = entry["timestamp"][:16].replace("T", " ")
                preview = entry.get("prompt_preview", "")[:60]
                lines.append(f"`{ts}` **{entry['agent']}** via `{entry['model']}` — {preview}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)

        # --- /ask ---

        @self.tree.command(name="ask", description="Send a prompt to a specific agent from any channel")
        @app_commands.describe(agent="Agent to send the prompt to", prompt="Prompt text")
        async def ask_command(interaction: discord.Interaction, agent: str, prompt: str) -> None:
            await interaction.response.defer()
            result = await self.daemon.handle_request({
                "prompt": prompt,
                "agent": agent,
                "source": "discord",
                "channel_id": str(interaction.channel_id),
            })
            output = result.get("result") or result.get("error") or "No response."
            chunks = list(split_message(output, max_length=2000))
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        @ask_command.autocomplete("agent")
        async def ask_agent_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            return [
                app_commands.Choice(name=a.name, value=a.name)
                for a in list_agents()
                if current.lower() in a.name.lower()
            ][:25]

        # --- /cron group ---

        cron_group = app_commands.Group(name="cron", description="Manage scheduled cron jobs")

        @cron_group.command(name="run", description="Run a cron job immediately")
        @app_commands.describe(job="Job name to run")
        async def cron_run(interaction: discord.Interaction, job: str) -> None:
            await interaction.response.defer()
            result = await self.daemon.handle_request({"op": "cron_run", "job": job})
            output = result.get("result") or result.get("error") or "Done."
            chunks = list(split_message(output, max_length=2000))
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        @cron_run.autocomplete("job")
        async def cron_run_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            if self.daemon._cron:
                jobs = self.daemon._cron.get_jobs()
            else:
                from arc.cron import load_jobs
                jobs = load_jobs(self.config)
            return [
                app_commands.Choice(name=j.name, value=j.name)
                for j in jobs
                if current.lower() in j.name.lower()
            ][:25]

        @cron_group.command(name="next", description="Show next scheduled run time for each job")
        async def cron_next(interaction: discord.Interaction) -> None:
            if not self.daemon._cron:
                await interaction.response.send_message(
                    "Cron scheduler not running.", ephemeral=True
                )
                return
            next_times = self.daemon._cron.next_run_times()
            lines = []
            for job in self.daemon._cron.get_jobs():
                if not job.enabled:
                    lines.append(f"`{job.name}` — disabled")
                elif next_times.get(job.name):
                    dt = datetime.fromisoformat(next_times[job.name])
                    lines.append(f"`{job.name}` — {_format_delta(dt)}")
                else:
                    lines.append(f"`{job.name}` — unknown")
            await interaction.response.send_message(
                "\n".join(lines) or "No jobs scheduled.", ephemeral=True
            )

        self.tree.add_command(cron_group)

    async def on_ready(self) -> None:
        log.info(f"Discord bot ready: {self.user}")
        if self.config.discord.guild_id:
            guild = discord.Object(id=int(self.config.discord.guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild")
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally (may take up to 1 hour)")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        if self.config.discord.guild_id and str(message.guild.id) != self.config.discord.guild_id:
            return

        channel_id = str(message.channel.id)
        agent = resolve_agent_for_channel(channel_id, None)
        if not agent and isinstance(message.channel, discord.Thread):
            agent = resolve_agent_for_channel(str(message.channel.parent_id), None)
        if not agent:
            return

        require_mention = agent.discord.get("require_mention", False)
        if require_mention and self.user not in message.mentions:
            return

        prompt = message.content.replace(f"<@{self.user.id}>", "").strip()

        if not self._rate_limiter.is_allowed(channel_id):
            log.warning(f"Rate limit hit for channel {channel_id}")
            return

        if self.config.discord.thread_mode and not isinstance(message.channel, discord.Thread):
            thread = await message.create_thread(name=prompt[:50] or "conversation")
            target = thread
            thread_id = str(thread.id)
        else:
            target = message.channel
            thread_id = channel_id

        async with target.typing():
            result = await self.daemon.handle_request({
                "prompt": prompt,
                "agent": agent.name,
                "source": "discord",
                "thread_id": thread_id,
                "channel_id": channel_id,
            })

        output = result.get("result") or result.get("error") or "No response."
        for chunk in split_message(output, max_length=2000):
            await target.send(chunk)

    async def send_to_default_channel(self, content: str, agent_name: str) -> None:
        """Send cron output to the agent's configured Discord channel."""
        try:
            agent = load_agent(agent_name, None)
        except FileNotFoundError:
            log.warning(f"Cannot notify Discord: agent '{agent_name}' not found")
            return

        channel_id = agent.discord.get("channel_id")
        if not channel_id:
            return

        channel = self.get_channel(int(channel_id))
        if not channel:
            log.warning(f"Discord channel {channel_id} not found")
            return

        for chunk in split_message(content, max_length=2000):
            try:
                await channel.send(chunk)
            except discord.DiscordException as e:
                log.error(f"Failed to send to channel {channel_id}: {e}")
