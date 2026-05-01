from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

from arc.config import ArcConfig, DiscordConfig, DiscordRateLimit
from arc.discord_bridge import ArcDiscordBot, _RateLimiter

# --- helpers ---


def _make_config(guild_id: str = "1234", thread_mode: bool = True) -> ArcConfig:
    cfg = ArcConfig()
    cfg.discord = DiscordConfig(
        enabled=True,
        guild_id=guild_id,
        thread_mode=thread_mode,
        rate_limit=DiscordRateLimit(messages_per_minute=5),
    )
    return cfg


def _make_bot(cfg: ArcConfig | None = None) -> tuple[ArcDiscordBot, MagicMock]:
    cfg = cfg or _make_config()
    daemon = MagicMock()
    daemon.model_overrides = {}
    daemon.handle_request = AsyncMock(return_value={"status": "ok", "result": "pong"})
    daemon.set_model_override = MagicMock()
    bot = ArcDiscordBot.__new__(ArcDiscordBot)
    bot.config = cfg
    bot.daemon = daemon
    bot._rate_limiter = _RateLimiter(cfg.discord.rate_limit.messages_per_minute)
    bot_user = MagicMock(spec=discord.ClientUser)
    bot_user.id = 42
    bot._connection = MagicMock()
    bot._connection.user = bot_user
    bot._connection._command_tree = None
    bot.http = MagicMock()
    bot.tree = app_commands.CommandTree(bot)
    bot._register_slash_commands()
    return bot, daemon


def _make_interaction(channel_id: str = "9999") -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel_id = int(channel_id)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_message(
    bot_user,
    content: str,
    channel_id: str = "9999",
    guild_id: str = "1234",
    is_thread: bool = False,
    parent_channel_id: str | None = None,
    mentioned: bool = True,
) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.author = MagicMock()
    msg.author.__eq__ = lambda s, other: False

    guild = MagicMock()
    guild.id = int(guild_id)
    msg.guild = guild

    if is_thread:
        channel = MagicMock(spec=discord.Thread)
        channel.parent_id = int(parent_channel_id or channel_id)
    else:
        channel = MagicMock(spec=discord.TextChannel)

    channel.id = int(channel_id)
    channel.send = AsyncMock()
    channel.typing = MagicMock(return_value=_async_ctx())
    msg.channel = channel

    msg.mentions = [bot_user] if mentioned else []
    msg.content = f"<@{bot_user.id}> {content}" if mentioned else content
    msg.reply = AsyncMock()
    msg.create_thread = AsyncMock(return_value=_make_thread())
    return msg


def _make_thread(thread_id: str = "8888") -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = int(thread_id)
    thread.send = AsyncMock()
    thread.typing = MagicMock(return_value=_async_ctx())
    return thread


class _async_ctx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


# --- _RateLimiter ---


def test_rate_limiter_allows_within_limit() -> None:
    rl = _RateLimiter(5)
    for _ in range(5):
        assert rl.is_allowed("chan") is True


def test_rate_limiter_blocks_over_limit() -> None:
    rl = _RateLimiter(3)
    for _ in range(3):
        rl.is_allowed("chan")
    assert rl.is_allowed("chan") is False


def test_rate_limiter_independent_channels() -> None:
    rl = _RateLimiter(1)
    assert rl.is_allowed("chan-a") is True
    assert rl.is_allowed("chan-b") is True
    assert rl.is_allowed("chan-a") is False


# --- on_message: ignore cases ---


async def test_ignores_own_messages(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot()
    msg = _make_message(bot.user, "hello")
    msg.author = bot.user  # same object
    msg.author.__eq__ = lambda s, other: s is other
    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=None):
        await bot.on_message(msg)
    daemon.handle_request.assert_not_awaited()


async def test_ignores_wrong_guild(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot(_make_config(guild_id="1234"))
    msg = _make_message(bot.user, "hi", guild_id="9999")
    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=None):
        await bot.on_message(msg)
    daemon.handle_request.assert_not_awaited()


async def test_ignores_no_agent_for_channel(config_dir: Path) -> None:
    bot, daemon = _make_bot()
    msg = _make_message(bot.user, "hi", channel_id="0000")
    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=None):
        await bot.on_message(msg)
    daemon.handle_request.assert_not_awaited()


async def test_ignores_not_mentioned_when_require_mention(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    bot, daemon = _make_bot()
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    agent.discord["require_mention"] = True
    msg = _make_message(bot.user, "hi", mentioned=False)
    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)
    daemon.handle_request.assert_not_awaited()


async def test_responds_without_mention_by_default(
    config_dir: Path, coach_agent_yaml: dict
) -> None:
    bot, daemon = _make_bot(_make_config(thread_mode=False))
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(bot.user, "hi", channel_id="9999", mentioned=False)
    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)
    daemon.handle_request.assert_awaited_once()


# --- on_message: dispatch ---


async def test_dispatches_in_thread_mode(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot(_make_config(thread_mode=True))
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(bot.user, "what's my workout?", channel_id="9999")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)

    msg.create_thread.assert_awaited_once()
    daemon.handle_request.assert_awaited_once()
    req = daemon.handle_request.call_args[0][0]
    assert req["source"] == "discord"
    assert req["agent"] == "coach"
    assert req["thread_id"] == "8888"


async def test_dispatches_in_existing_thread(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot(_make_config(thread_mode=True))
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(
        bot.user, "follow-up", channel_id="8888", is_thread=True, parent_channel_id="9999"
    )

    with patch(
        "arc.discord_bridge.resolve_agent_for_channel",
        side_effect=lambda cid, _: agent if cid == "9999" else None,
    ):
        await bot.on_message(msg)

    msg.create_thread.assert_not_awaited()
    daemon.handle_request.assert_awaited_once()
    req = daemon.handle_request.call_args[0][0]
    assert req["thread_id"] == "8888"


async def test_dispatch_no_thread_mode(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot(_make_config(thread_mode=False))
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(bot.user, "hi", channel_id="9999")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)

    msg.create_thread.assert_not_awaited()
    daemon.handle_request.assert_awaited_once()


async def test_response_sent_to_target(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot(_make_config(thread_mode=False))
    daemon.handle_request.return_value = {"status": "ok", "result": "Here is your plan."}
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(bot.user, "hi", channel_id="9999")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)

    msg.channel.send.assert_awaited_once_with("Here is your plan.")


async def test_rate_limit_blocks_dispatch(config_dir: Path, coach_agent_yaml: dict) -> None:
    cfg = _make_config(thread_mode=False)
    cfg.discord.rate_limit.messages_per_minute = 1
    bot, daemon = _make_bot(cfg)
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    msg = _make_message(bot.user, "hi", channel_id="9999")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await bot.on_message(msg)  # first: allowed
        await bot.on_message(msg)  # second: blocked

    assert daemon.handle_request.await_count == 1


# --- /model slash command ---


async def test_model_set(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot()
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await cmd.callback(interaction, model="haiku")

    daemon.set_model_override.assert_called_once_with("9999", "haiku")
    interaction.response.send_message.assert_awaited_once()
    assert "haiku" in interaction.response.send_message.call_args[0][0]


async def test_model_reset(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot()
    daemon.model_overrides["9999"] = "haiku"
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await cmd.callback(interaction, model="reset")

    daemon.set_model_override.assert_called_once_with("9999", None)
    assert "reset" in interaction.response.send_message.call_args[0][0].lower()


async def test_model_unknown(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot()
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await cmd.callback(interaction, model="gpt-4")

    daemon.set_model_override.assert_not_called()
    assert "not allowed" in interaction.response.send_message.call_args[0][0]


async def test_model_show_current(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, daemon = _make_bot()
    daemon.model_overrides["9999"] = "haiku"
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        await cmd.callback(interaction, model="")

    assert "haiku" in interaction.response.send_message.call_args[0][0]


async def test_model_autocomplete(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, _ = _make_bot()
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        choices = await cmd._params["model"].autocomplete(interaction, "")

    names = [c.name for c in choices]
    assert "reset" in names
    assert "haiku" in names
    assert "sonnet" in names


async def test_model_autocomplete_filters(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, _ = _make_bot()
    from arc.agents import load_agent
    agent = load_agent("coach", config_dir)
    interaction = _make_interaction(channel_id="9999")
    cmd = bot.tree.get_command("model")

    with patch("arc.discord_bridge.resolve_agent_for_channel", return_value=agent):
        choices = await cmd._params["model"].autocomplete(interaction, "hai")

    assert all("hai" in c.name for c in choices)


# --- send_to_default_channel ---


async def test_send_to_default_channel(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, _ = _make_bot()
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel = MagicMock(return_value=channel)

    with patch("arc.discord_bridge.load_agent") as mock_load:
        from arc.agents import load_agent as real_load
        mock_load.side_effect = lambda n, _: real_load(n, config_dir)
        await bot.send_to_default_channel("Great workout today!", "coach")

    channel.send.assert_awaited_once_with("Great workout today!")


async def test_send_to_default_channel_missing_agent(config_dir: Path) -> None:
    bot, _ = _make_bot()
    with patch("arc.discord_bridge.load_agent", side_effect=FileNotFoundError("no agent")):
        await bot.send_to_default_channel("hello", "ghost")


async def test_send_to_default_channel_no_channel(config_dir: Path, coach_agent_yaml: dict) -> None:
    bot, _ = _make_bot()
    bot.get_channel = MagicMock(return_value=None)

    with patch("arc.discord_bridge.load_agent") as mock_load:
        from arc.agents import load_agent as real_load
        mock_load.side_effect = lambda n, _: real_load(n, config_dir)
        await bot.send_to_default_channel("hello", "coach")
