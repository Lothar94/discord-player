"""Bot entrypoint.

Loads config from the environment, instantiates the bot, registers the Music
Cog and starts the connection. Designed to be small and replaceable.
"""

from __future__ import annotations

import asyncio
import logging
import signal

import discord
from discord.ext import commands

from config import BotConfig, load_config


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _build_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.guilds = True
    return intents


def _create_bot(config: BotConfig) -> commands.Bot:
    bot = commands.Bot(
        command_prefix=config.command_prefix,
        intents=_build_intents(),
        help_command=commands.DefaultHelpCommand(no_category="Commands"),
    )
    bot.default_volume = config.default_volume  # type: ignore[attr-defined]
    bot.inactivity_timeout_seconds = config.inactivity_timeout_seconds  # type: ignore[attr-defined]
    bot.disconnect_when_alone = config.disconnect_when_alone  # type: ignore[attr-defined]
    bot.empty_channel_grace_seconds = config.empty_channel_grace_seconds  # type: ignore[attr-defined]
    bot.max_playlist_tracks = config.max_playlist_tracks  # type: ignore[attr-defined]
    return bot


async def _run_bot(config: BotConfig) -> None:
    bot = _create_bot(config)

    @bot.event
    async def on_ready() -> None:
        logging.getLogger(__name__).info(
            "Logged in as %s (id=%s)", bot.user, getattr(bot.user, "id", "?")
        )

    await bot.load_extension("cogs.music")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_shutdown() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, sig_name), _request_shutdown)
        except NotImplementedError:
            # Signal handlers are not available on every platform (e.g. Windows).
            pass

    async with bot:
        bot_task = asyncio.create_task(bot.start(config.discord_token))
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if stop_task in done:
            await bot.close()
            await bot_task


def main() -> None:
    config = load_config()
    _configure_logging(config.log_level)
    asyncio.run(_run_bot(config))


if __name__ == "__main__":
    main()
