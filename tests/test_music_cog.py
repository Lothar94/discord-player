"""Unit tests for the Music cog voice lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs.music import Music
from music.errors import TrackNotFoundError
from music.player import AutoDisconnectConfig

_BOT_USER_ID = 999


def _make_cog() -> Music:
    bot = MagicMock()
    bot.user.id = _BOT_USER_ID
    return Music(
        bot,
        default_volume=0.5,
        auto_disconnect=AutoDisconnectConfig(),
        source_factory=MagicMock(),
    )


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


def _make_member(member_id: int, bot: bool, guild_id: int = 1) -> MagicMock:
    member = MagicMock()
    member.id = member_id
    member.bot = bot
    member.guild.id = guild_id
    return member


def _make_voice_state(channel) -> MagicMock:
    state = MagicMock()
    state.channel = channel
    return state


@pytest.mark.asyncio
async def test_bot_self_disconnect_cleans_up_player() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    await Music.join.callback(cog, ctx)
    player = cog._players[ctx.guild.id]
    idle_task = player._idle_task
    player.start_empty_channel_timer()
    empty_channel_task = player._empty_channel_task
    voice_client = ctx.guild.voice_client
    bot_member = _make_member(_BOT_USER_ID, bot=True)

    await cog.on_voice_state_update(
        bot_member, _make_voice_state(MagicMock()), _make_voice_state(None)
    )
    await asyncio.sleep(0)

    assert ctx.guild.id not in cog._players
    assert idle_task.cancelled()
    assert empty_channel_task.cancelled()
    voice_client.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_bot_leaving_is_ignored() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    await Music.join.callback(cog, ctx)
    other_bot = _make_member(123, bot=True)

    await cog.on_voice_state_update(
        other_bot, _make_voice_state(MagicMock()), _make_voice_state(None)
    )

    player = cog._players[ctx.guild.id]
    assert player._empty_channel_task is None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_empty_channel_check_only_targets_event_guild() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    ctx.guild.voice_client.channel.members = []
    await Music.join.callback(cog, ctx)
    human = _make_member(5, bot=False, guild_id=2)

    await cog.on_voice_state_update(
        human, _make_voice_state(MagicMock()), _make_voice_state(None)
    )

    player = cog._players[ctx.guild.id]
    assert player._empty_channel_task is None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_last_human_leaving_starts_empty_channel_timer() -> None:
    cog = _make_cog()
    ctx = _make_ctx()
    ctx.guild.voice_client.channel.members = []
    await Music.join.callback(cog, ctx)
    human = _make_member(5, bot=False, guild_id=ctx.guild.id)

    await cog.on_voice_state_update(
        human, _make_voice_state(MagicMock()), _make_voice_state(None)
    )

    player = cog._players[ctx.guild.id]
    assert player._empty_channel_task is not None
    player._empty_channel_task.cancel()
    player._idle_task.cancel()
