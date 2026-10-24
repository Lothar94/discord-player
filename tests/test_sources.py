"""Unit tests for YTDLSourceFactory (yt-dlp mocked, no network)."""

from __future__ import annotations

from typing import Iterator, Tuple
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from music.errors import TrackNotFoundError
from music.sources import YTDLSourceFactory
from music.track import TrackInfo

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL123"
WATCH_IN_PLAYLIST_URL = "https://www.youtube.com/watch?v=aaa&list=PL123"
VIDEO_URL = "https://www.youtube.com/watch?v=aaa"


class _Requester:
    id = 42

    def __str__(self) -> str:
        return "tester#0001"


REQUESTER = _Requester()


def _flat_entry(video_id: str, title: str, duration: float = 200.0) -> dict:
    return {
        "_type": "url",
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "duration": duration,
        "channel": "Some Channel",
    }


def _playlist(entries: list, title: str = "My Mix") -> dict:
    return {"_type": "playlist", "title": title, "entries": entries}


@pytest.fixture
def ytdl_mocks() -> Iterator[Tuple[MagicMock, MagicMock, MagicMock]]:
    """Patch YoutubeDL; yields (constructor, single instance, playlist instance)."""

    single_ytdl = MagicMock(name="single_ytdl")
    playlist_ytdl = MagicMock(name="playlist_ytdl")
    with patch("music.sources.yt_dlp.YoutubeDL", side_effect=[single_ytdl, playlist_ytdl]) as constructor:
        yield constructor, single_ytdl, playlist_ytdl


async def test_playlist_url_returns_all_entries_in_order(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.return_value = _playlist(
        [_flat_entry("aaa", "First"), _flat_entry("bbb", "Second"), _flat_entry("ccc", "Third")]
    )
    factory = YTDLSourceFactory()

    resolved = await factory.resolve(PLAYLIST_URL, requester=REQUESTER)

    assert resolved.playlist_title == "My Mix"
    assert [track.title for track in resolved.tracks] == ["First", "Second", "Third"]
    assert [track.query for track in resolved.tracks] == [
        "https://www.youtube.com/watch?v=aaa",
        "https://www.youtube.com/watch?v=bbb",
        "https://www.youtube.com/watch?v=ccc",
    ]
    assert all(track.webpage_url == track.query for track in resolved.tracks)
    assert resolved.tracks[0].duration_seconds == 200
    assert resolved.tracks[0].uploader == "Some Channel"
    assert resolved.tracks[0].requester_id == 42
    playlist_ytdl.extract_info.assert_called_once_with(PLAYLIST_URL, download=False)
    single_ytdl.extract_info.assert_not_called()


async def test_watch_url_with_list_param_is_treated_as_playlist(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.return_value = _playlist(
        [_flat_entry("aaa", "First"), _flat_entry("bbb", "Second")]
    )
    factory = YTDLSourceFactory()

    resolved = await factory.resolve(WATCH_IN_PLAYLIST_URL, requester=REQUESTER)

    assert len(resolved.tracks) == 2
    single_ytdl.extract_info.assert_not_called()


async def test_search_query_returns_first_result_only(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    single_ytdl.extract_info.return_value = {
        "entries": [
            {"title": "Best match", "webpage_url": VIDEO_URL, "duration": 180},
            {"title": "Other", "webpage_url": "https://www.youtube.com/watch?v=zzz"},
        ]
    }
    factory = YTDLSourceFactory()

    resolved = await factory.resolve("ytsearch:some song", requester=REQUESTER)

    assert [track.title for track in resolved.tracks] == ["Best match"]
    assert resolved.tracks[0].webpage_url == VIDEO_URL
    assert resolved.tracks[0].query == "ytsearch:some song"
    assert resolved.playlist_title is None
    playlist_ytdl.extract_info.assert_not_called()


async def test_free_text_query_is_not_a_playlist(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    single_ytdl.extract_info.return_value = {"entries": [{"title": "Song", "webpage_url": VIDEO_URL}]}
    factory = YTDLSourceFactory()

    resolved = await factory.resolve("song with list=word", requester=REQUESTER)

    assert len(resolved.tracks) == 1
    playlist_ytdl.extract_info.assert_not_called()


async def test_single_video_url_returns_one_track(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    single_ytdl.extract_info.return_value = {
        "title": "Solo", "webpage_url": VIDEO_URL, "duration": 61, "uploader": "Artist"
    }
    factory = YTDLSourceFactory()

    resolved = await factory.resolve(VIDEO_URL, requester=REQUESTER)

    assert len(resolved.tracks) == 1
    track = resolved.tracks[0]
    assert (track.title, track.webpage_url, track.query, track.uploader) == (
        "Solo", VIDEO_URL, VIDEO_URL, "Artist"
    )
    playlist_ytdl.extract_info.assert_not_called()


async def test_non_youtube_url_with_list_param_is_not_a_playlist(ytdl_mocks) -> None:
    _, single_ytdl, playlist_ytdl = ytdl_mocks
    single_ytdl.extract_info.return_value = {"title": "Clip", "webpage_url": "https://example.com/v?list=1"}
    factory = YTDLSourceFactory()

    await factory.resolve("https://example.com/v?list=1", requester=REQUESTER)

    playlist_ytdl.extract_info.assert_not_called()


async def test_playlist_skips_missing_and_unavailable_entries(ytdl_mocks) -> None:
    _, _, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.return_value = _playlist([
        None,
        _flat_entry("aaa", "Keep me"),
        _flat_entry("bbb", "[Private video]"),
        _flat_entry("ccc", "[Deleted video]"),
        _flat_entry("ddd", "Keep me too"),
    ])
    factory = YTDLSourceFactory()

    resolved = await factory.resolve(PLAYLIST_URL, requester=REQUESTER)

    assert [track.title for track in resolved.tracks] == ["Keep me", "Keep me too"]


async def test_playlist_entry_url_built_from_id_when_missing(ytdl_mocks) -> None:
    _, _, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.return_value = _playlist([{"id": "xyz", "url": "xyz", "title": "Bare"}])
    factory = YTDLSourceFactory()

    resolved = await factory.resolve(PLAYLIST_URL, requester=REQUESTER)

    assert resolved.tracks[0].query == "https://www.youtube.com/watch?v=xyz"


@pytest.mark.parametrize("entries", [[], [None, _flat_entry("aaa", "[Private video]")]])
async def test_empty_playlist_raises_track_not_found(ytdl_mocks, entries: list) -> None:
    _, _, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.return_value = _playlist(entries)
    factory = YTDLSourceFactory()

    with pytest.raises(TrackNotFoundError):
        await factory.resolve(PLAYLIST_URL, requester=REQUESTER)


async def test_download_error_raises_track_not_found(ytdl_mocks) -> None:
    _, _, playlist_ytdl = ytdl_mocks
    playlist_ytdl.extract_info.side_effect = yt_dlp.utils.DownloadError("gone")
    factory = YTDLSourceFactory()

    with pytest.raises(TrackNotFoundError):
        await factory.resolve(PLAYLIST_URL, requester=REQUESTER)


def test_playlist_instance_uses_flat_extraction_with_cap(ytdl_mocks) -> None:
    constructor, _, _ = ytdl_mocks

    YTDLSourceFactory(max_playlist_tracks=25)

    single_options = constructor.call_args_list[0].args[0]
    playlist_options = constructor.call_args_list[1].args[0]
    assert single_options["noplaylist"] is True
    assert "playlistend" not in single_options
    assert playlist_options["noplaylist"] is False
    assert playlist_options["extract_flat"] == "in_playlist"
    assert playlist_options["playlistend"] == 25


def test_playlist_cap_defaults_to_100(ytdl_mocks) -> None:
    constructor, _, _ = ytdl_mocks

    YTDLSourceFactory()

    assert constructor.call_args_list[1].args[0]["playlistend"] == 100


def test_zero_playlist_cap_disables_limit(ytdl_mocks) -> None:
    constructor, _, _ = ytdl_mocks

    YTDLSourceFactory(max_playlist_tracks=0)

    assert "playlistend" not in constructor.call_args_list[1].args[0]


def _make_track(webpage_url: str, query: str) -> TrackInfo:
    return TrackInfo(
        title="Song",
        webpage_url=webpage_url,
        duration_seconds=100,
        uploader=None,
        requester_id=42,
        requester_name="tester#0001",
        query=query,
    )


@pytest.mark.parametrize(
    ("webpage_url", "expected_target"),
    [(VIDEO_URL, VIDEO_URL), ("", "ytsearch:song")],
)
async def test_build_audio_source_prefers_webpage_url(
    ytdl_mocks, webpage_url: str, expected_target: str
) -> None:
    _, single_ytdl, _ = ytdl_mocks
    single_ytdl.extract_info.return_value = {"url": "https://stream.example/audio"}
    factory = YTDLSourceFactory()

    with patch("music.sources.discord.FFmpegPCMAudio") as ffmpeg, \
            patch("music.sources.discord.PCMVolumeTransformer") as transformer:
        source = await factory.build_audio_source(
            _make_track(webpage_url, query="ytsearch:song"), volume=0.3
        )

    single_ytdl.extract_info.assert_called_once_with(expected_target, download=False)
    assert ffmpeg.call_args.args[0] == "https://stream.example/audio"
    transformer.assert_called_once_with(ffmpeg.return_value, volume=0.3)
    assert source is transformer.return_value


async def test_build_audio_source_without_stream_url_raises(ytdl_mocks) -> None:
    _, single_ytdl, _ = ytdl_mocks
    single_ytdl.extract_info.return_value = {"title": "Song"}
    factory = YTDLSourceFactory()

    with pytest.raises(TrackNotFoundError):
        await factory.build_audio_source(_make_track(VIDEO_URL, VIDEO_URL), volume=0.5)
