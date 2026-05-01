"""Discord bot bridge for arc daemon."""
import collections
import logging
import time
from typing import TYPE_CHECKING

import discord

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

    async def on_ready(self) -> None:
        log.info(f"Discord bot ready: {self.user}")

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

        if prompt.startswith("/model"):
            await self._handle_model_command(message, agent, prompt)
            return

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

    async def _handle_model_command(
        self, message: discord.Message, agent, prompt: str
    ) -> None:
        channel_id = str(message.channel.id)
        parts = prompt.split(maxsplit=1)
        if len(parts) == 2:
            model = parts[1].strip()
            if model == "reset":
                self.daemon.set_model_override(channel_id, None)
                await message.reply("Model reset to agent default.")
            elif model in (agent.allowed_models or []):
                self.daemon.set_model_override(channel_id, model)
                await message.reply(f"Model set to {model}.")
            else:
                allowed = ", ".join(agent.allowed_models or ["(none)"])
                await message.reply(f"Model '{model}' not allowed. Options: {allowed}")
        else:
            current = self.daemon.model_overrides.get(channel_id, agent.model)
            await message.reply(f"Current model: {current}")

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
