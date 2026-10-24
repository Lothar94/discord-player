"""Unit tests for the Music cog voice lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.music import Music
from music.errors import TrackNotFoundError
from music.player import AutoDisconnectConfig

_BOT_USER_ID = 999


def _make_cog() -> Music:
    bot = MagicMock()
    bot.user.id = _BOT_USER_ID
    return Music(bot, default_volume=0.5, auto_disconnect=AutoDisconnectConfig())


def _make_voice_client(channel: MagicMock) -> MagicMock:
    voice_client = MagicMock()
    voice_client.channel = channel
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = False
    voice_client.is_paused.return_value = False
    voice_client.disconnect = AsyncMock()
    return voice_client


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.guild.id = 1
    ctx.send = AsyncMock()
    ctx.guild.voice_client = _make_voice_client(ctx.author.voice.channel)
    return ctx


@pytest.mark.asyncio
async def test_join_starts_idle_timer() -> None:
    cog = _make_cog()
    ctx = _make_ctx()

    await Music.join.callback(cog, ctx)

    player = cog._players[ctx.guild.id]
    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_join_while_playing_does_not_start_idle_timer() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    ctx.guild.voice_client.is_playing.return_value = True

    await Music.join.callback(cog, ctx)

    assert cog._players[ctx.guild.id]._idle_task is None


@pytest.mark.asyncio
async def test_play_that_fails_to_resolve_leaves_idle_timer() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    cog._source_factory.resolve = AsyncMock(side_effect=TrackNotFoundError("nope"))

    with pytest.raises(TrackNotFoundError):
        await Music.play.callback(cog, ctx, query="missing")

    player = cog._players[ctx.guild.id]
    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_stop_without_player_disconnects_voice_client() -> None:
    cog = _make_cog()
    ctx = _make_ctx()

    await Music.stop.callback(cog, ctx)

    ctx.guild.voice_client.disconnect.assert_awaited_once()

