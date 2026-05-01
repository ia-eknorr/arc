"""Discord bot bridge for arc daemon."""
import collections
import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from arc.agents import load_agent, resolve_agent_for_channel
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

    def _register_slash_commands(self) -> None:
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
