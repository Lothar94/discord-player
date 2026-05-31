"""Unit tests for GuildPlayer auto-disconnect behavior."""

from __future__ import annotations

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music.player import GuildPlayer
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
        loop=loop or asyncio.get_event_loop(),
        inactivity_timeout=inactivity_timeout,
        empty_channel_grace=empty_channel_grace,
        disconnect_when_alone=disconnect_when_alone,
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

    player._start_idle_timer()
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
