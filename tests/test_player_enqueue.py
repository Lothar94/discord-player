"""Unit tests for GuildPlayer.enqueue_many."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from music.player import AutoDisconnectConfig, GuildPlayer
from music.track import TrackInfo


def _make_track(title: str) -> TrackInfo:
    return TrackInfo(
        title=title,
        webpage_url=f"https://example.com/{title}",
        duration_seconds=180,
        uploader="tester",
        requester_id=1,
        requester_name="tester",
        query=title,
    )


def _make_voice_client(*, playing: bool) -> MagicMock:
    voice_client = MagicMock()
    voice_client.is_connected.return_value = True
    voice_client.is_playing.return_value = playing
    voice_client.is_paused.return_value = False
    return voice_client


def _make_player(voice_client: MagicMock) -> GuildPlayer:
    guild = MagicMock()
    guild.id = 1
    guild.voice_client = voice_client
    source_factory = MagicMock()
    source_factory.build_audio_source = AsyncMock(return_value=MagicMock())
    return GuildPlayer(
        guild=guild,
        source_factory=source_factory,
        default_volume=0.5,
        loop=asyncio.get_running_loop(),
        auto_disconnect=AutoDisconnectConfig(inactivity_timeout=0),
    )


@pytest.mark.asyncio
async def test_enqueue_many_plays_first_and_queues_rest_in_order() -> None:
    voice_client = _make_voice_client(playing=False)
    player = _make_player(voice_client)

    await player.enqueue_many([_make_track("a"), _make_track("b"), _make_track("c")])

    voice_client.play.assert_called_once()
    player._source_factory.build_audio_source.assert_awaited_once()
    assert player.queue.current.title == "a"
    assert [track.title for track in player.queue.upcoming] == ["b", "c"]


@pytest.mark.asyncio
async def test_enqueue_many_while_playing_only_appends() -> None:
    voice_client = _make_voice_client(playing=True)
    player = _make_player(voice_client)

    await player.enqueue_many([_make_track("a"), _make_track("b")])

    voice_client.play.assert_not_called()
    assert [track.title for track in player.queue.upcoming] == ["a", "b"]


@pytest.mark.asyncio
async def test_enqueue_many_with_no_tracks_does_nothing() -> None:
    voice_client = _make_voice_client(playing=False)
    player = _make_player(voice_client)

    await player.enqueue_many([])

    voice_client.play.assert_not_called()
    assert player.queue.is_empty
    assert player._idle_task is None
