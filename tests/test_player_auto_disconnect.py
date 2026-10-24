"""Unit tests for GuildPlayer auto-disconnect behavior."""

from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from music.errors import TrackNotFoundError
from music.player import AutoDisconnectConfig, GuildPlayer
from music.queue import LoopMode
from music.track import TrackInfo


def _make_track(title: str = "track") -> TrackInfo:
    return TrackInfo(
        title=title,
        webpage_url=f"https://example.com/{title}",
        duration_seconds=180,
        uploader="tester",
        requester_id=1,
        requester_name="tester",
        query=title,
    )


def _make_player(
    inactivity_timeout: int = 300,
    empty_channel_grace: int = 60,
    disconnect_when_alone: bool = True,
    on_disconnect=None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> GuildPlayer:
    guild = MagicMock()
    guild.id = 1
    guild.voice_client = None
    source_factory = MagicMock()
    source_factory.build_audio_source = AsyncMock()
    return GuildPlayer(
        guild=guild,
        source_factory=source_factory,
        default_volume=0.5,
        loop=loop or asyncio.get_running_loop(),
        auto_disconnect=AutoDisconnectConfig(
            inactivity_timeout=inactivity_timeout,
            empty_channel_grace=empty_channel_grace,
            disconnect_when_alone=disconnect_when_alone,
        ),
        on_disconnect=on_disconnect,
    )


@pytest.mark.asyncio
async def test_idle_timer_starts_when_queue_exhausted() -> None:
    player = _make_player(inactivity_timeout=300)

    await player._play_next()

    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_idle_timer_cancelled_on_enqueue() -> None:
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = False
    voice_client.is_paused.return_value = False
    voice_client.play = MagicMock()

    player = _make_player(inactivity_timeout=300)
    player._guild.voice_client = voice_client

    player._source_factory.build_audio_source = AsyncMock(return_value=MagicMock())

    await player._play_next()
    assert player._idle_task is not None

    await player.enqueue(_make_track())

    assert player._idle_task is None


@pytest.mark.asyncio
async def test_idle_timer_cancelled_on_stop() -> None:
    player = _make_player(inactivity_timeout=300)
    player._guild.voice_client = None

    await player._play_next()
    assert player._idle_task is not None

    await player.stop_and_disconnect()

    assert player._idle_task is None


@pytest.mark.asyncio
async def test_on_disconnect_callback_called_after_timeout() -> None:
    callback = MagicMock()
    player = _make_player(inactivity_timeout=1, on_disconnect=callback)
    player._guild.voice_client = None

    player._restart_idle_timer()
    assert player._idle_task is not None

    await asyncio.sleep(1.1)

    callback.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_empty_channel_timer_starts_when_called() -> None:
    player = _make_player(empty_channel_grace=60, disconnect_when_alone=True)

    player.start_empty_channel_timer()

    assert player._empty_channel_task is not None
    player._empty_channel_task.cancel()


@pytest.mark.asyncio
async def test_empty_channel_timer_cancelled_on_repopulate() -> None:
    player = _make_player(empty_channel_grace=60, disconnect_when_alone=True)

    player.start_empty_channel_timer()
    assert player._empty_channel_task is not None

    player.cancel_empty_channel_timer()

    assert player._empty_channel_task is None


@pytest.mark.asyncio
async def test_disabled_inactivity_does_not_schedule_timer() -> None:
    player = _make_player(inactivity_timeout=0)

    await player._play_next()

    assert player._idle_task is None


@pytest.mark.asyncio
async def test_disabled_alone_does_not_schedule_timer() -> None:
    player = _make_player(disconnect_when_alone=False)

    player.start_empty_channel_timer()

    assert player._empty_channel_task is None


async def _suspend(*args, **kwargs) -> None:
    await asyncio.sleep(0)


def _make_voice_client(playing: bool = False, paused: bool = False) -> MagicMock:
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = playing
    voice_client.is_paused.return_value = paused
    voice_client.disconnect = AsyncMock(side_effect=_suspend)
    return voice_client


async def _wait_for_task(task: asyncio.Task) -> None:
    done, _ = await asyncio.wait([task], timeout=1)
    assert task in done


@pytest.mark.asyncio
async def test_idle_timer_completes_disconnect_when_disconnect_suspends() -> None:
    callback = MagicMock()
    player = _make_player(inactivity_timeout=0.01, on_disconnect=callback)
    voice_client = _make_voice_client()
    player._guild.voice_client = voice_client

    player._restart_idle_timer()
    task = player._idle_task
    await _wait_for_task(task)

    assert not task.cancelled()
    voice_client.disconnect.assert_awaited_once()
    callback.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_empty_channel_timer_completes_disconnect_when_disconnect_suspends() -> None:
    callback = MagicMock()
    player = _make_player(empty_channel_grace=0.01, on_disconnect=callback)
    voice_client = _make_voice_client()
    player._guild.voice_client = voice_client

    player.start_empty_channel_timer()
    task = player._empty_channel_task
    await _wait_for_task(task)

    assert not task.cancelled()
    voice_client.disconnect.assert_awaited_once()
    callback.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_on_disconnect_called_even_if_disconnect_raises() -> None:
    callback = MagicMock()
    player = _make_player(on_disconnect=callback)
    voice_client = _make_voice_client()
    voice_client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))
    player._guild.voice_client = voice_client

    await player.stop_and_disconnect()

    callback.assert_called_once_with(1)
    voice_client.disconnect.assert_any_await(force=True)


@pytest.mark.asyncio
async def test_no_idle_timer_after_stop_and_disconnect() -> None:
    player = _make_player(inactivity_timeout=0.01)
    notify_channel = MagicMock()
    notify_channel.send = AsyncMock()
    player.set_notify_channel(notify_channel)
    player._guild.voice_client = _make_voice_client(playing=True)

    await player.stop_and_disconnect()
    # voice.stop() fires the `after` callback, which advances the queue.
    await player._play_next()
    player._restart_idle_timer()
    await asyncio.sleep(0.05)

    assert player._idle_task is None
    notify_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_track_loop_with_missing_track_does_not_recurse() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client()
    player._guild.voice_client = voice_client
    player._source_factory.build_audio_source = AsyncMock(
        side_effect=TrackNotFoundError("gone")
    )
    player.queue.enqueue(_make_track("a"))
    player.queue.advance()
    player.queue.set_loop_mode(LoopMode.TRACK)

    await asyncio.wait_for(player._play_next(), timeout=1)

    voice_client.play.assert_not_called()
    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_track_loop_with_missing_track_plays_next_one() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client()
    player._guild.voice_client = voice_client
    audio_source = MagicMock()
    player._source_factory.build_audio_source = AsyncMock(
        side_effect=[TrackNotFoundError("gone"), audio_source]
    )
    player.queue.enqueue(_make_track("a"))
    player.queue.enqueue(_make_track("b"))
    player.queue.advance()
    player.queue.set_loop_mode(LoopMode.TRACK)

    await asyncio.wait_for(player._play_next(), timeout=1)

    assert player.queue.current.title == "b"
    voice_client.play.assert_called_once()


@pytest.mark.asyncio
async def test_skip_in_track_loop_moves_to_next_track() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client(playing=True)
    player._guild.voice_client = voice_client
    player._source_factory.build_audio_source = AsyncMock(return_value=MagicMock())
    player.queue.enqueue(_make_track("a"))
    player.queue.enqueue(_make_track("b"))
    player.queue.advance()
    player.queue.set_loop_mode(LoopMode.TRACK)

    await player.skip()
    voice_client.is_playing.return_value = False
    await player._play_next()  # what the `after` callback triggers

    voice_client.stop.assert_called_once()
    assert player.queue.current.title == "b"
    assert player.queue.loop_mode is LoopMode.TRACK


@pytest.mark.asyncio
async def test_enqueue_while_paused_keeps_idle_timer() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client(playing=True)
    player._guild.voice_client = voice_client

    await player.pause()
    voice_client.is_playing.return_value = False
    voice_client.is_paused.return_value = True
    await player.enqueue(_make_track())

    assert player._idle_task is not None
    assert not player._idle_task.cancelled()
    voice_client.play.assert_not_called()
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_voice_play_failure_restarts_idle_timer() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client()
    voice_client.play.side_effect = discord.ClientException("Already playing audio.")
    player._guild.voice_client = voice_client
    player._source_factory.build_audio_source = AsyncMock(return_value=MagicMock())

    with pytest.raises(discord.ClientException):
        await player.enqueue(_make_track())

    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_source_factory_failure_restarts_idle_timer() -> None:
    player = _make_player(inactivity_timeout=300)
    player._guild.voice_client = _make_voice_client()
    player._source_factory.build_audio_source = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await player.enqueue(_make_track())

    assert player._idle_task is not None
    player._idle_task.cancel()


@pytest.mark.asyncio
async def test_concurrent_enqueue_starts_playback_once() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client()
    voice_client.play.side_effect = (
        lambda *args, **kwargs: setattr(voice_client.is_playing, "return_value", True)
    )
    player._guild.voice_client = voice_client

    async def _build(*args, **kwargs) -> MagicMock:
        await asyncio.sleep(0)
        return MagicMock()

    player._source_factory.build_audio_source = AsyncMock(side_effect=_build)

    await asyncio.gather(
        player.enqueue(_make_track("a")),
        player.enqueue(_make_track("b")),
    )

    voice_client.play.assert_called_once()
    assert player.queue.current.title == "a"
    assert [track.title for track in player.queue.upcoming] == ["b"]
    assert player._idle_task is None


@pytest.mark.asyncio
async def test_disconnect_during_stream_resolution_does_not_play() -> None:
    player = _make_player(inactivity_timeout=300)
    voice_client = _make_voice_client()
    player._guild.voice_client = voice_client
    audio_source = MagicMock()

    async def _build(*args, **kwargs) -> MagicMock:
        player.mark_disconnected()
        return audio_source

    player._source_factory.build_audio_source = AsyncMock(side_effect=_build)

    await player.enqueue(_make_track())

    voice_client.play.assert_not_called()
    audio_source.cleanup.assert_called_once()
    assert player._idle_task is None


@pytest.mark.asyncio
async def test_idle_timer_notifies_after_disconnect() -> None:
    events = []
    channel = MagicMock()
    channel.send = AsyncMock(side_effect=lambda message: events.append("notify"))
    player = _make_player(inactivity_timeout=0.01)
    player.set_notify_channel(channel)
    voice_client = _make_voice_client()
    voice_client.disconnect = AsyncMock(side_effect=lambda **kwargs: events.append("disconnect"))
    player._guild.voice_client = voice_client

    player._restart_idle_timer()
    await _wait_for_task(player._idle_task)

    assert events == ["disconnect", "notify"]


@pytest.mark.asyncio
async def test_idle_timer_skips_notice_when_already_disconnecting() -> None:
    channel = MagicMock()
    channel.send = AsyncMock()
    player = _make_player(inactivity_timeout=0.01)
    player.set_notify_channel(channel)
    player._guild.voice_client = _make_voice_client()

    player._restart_idle_timer()
    task = player._idle_task
    player._disconnecting = True
    await _wait_for_task(task)

    channel.send.assert_not_called()
