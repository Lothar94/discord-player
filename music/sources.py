"""yt-dlp + FFmpeg audio source.

Resolves YouTube URLs, playlists and search queries into TrackInfo metadata,
and produces a streamable PCM source for discord.py. Stream URLs are
short-lived, so stream resolution happens just before playback (see
GuildPlayer).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp

from .errors import TrackNotFoundError
from .track import TrackInfo


MAX_PLAYLIST_TRACKS = 100

_YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "skip_download": True,
    "source_address": "0.0.0.0",
}

_FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
)
_FFMPEG_OPTIONS = "-vn"

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
_YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
_UNAVAILABLE_TITLES = frozenset(
    {"[Private video]", "[Deleted video]", "[Unavailable video]"}
)


@dataclass(frozen=True)
class ResolvedQuery:
    """Tracks resolved from a single user query.

    `playlist_title` is only set when the query was a playlist link.
    """

    tracks: List[TrackInfo] = field(default_factory=list)
    playlist_title: Optional[str] = None


class YTDLSourceFactory:
    """Resolves queries into TrackInfo and produces audio sources on demand."""

    def __init__(
        self,
        ytdl_options: Optional[dict] = None,
        *,
        max_playlist_tracks: int = MAX_PLAYLIST_TRACKS,
    ) -> None:
        options = ytdl_options or _YTDL_OPTIONS
        self._ytdl = yt_dlp.YoutubeDL(options)
        self._playlist_ytdl = yt_dlp.YoutubeDL(
            _playlist_options(options, max_playlist_tracks)
        )

    async def resolve(
        self, query: str, *, requester: discord.abc.User
    ) -> ResolvedQuery:
        """Resolve a query into tracks.

        Playlist links yield every available entry in order; URLs of single
        videos and free-text searches yield exactly one track.
        """

        if _is_playlist_url(query):
            return await self._resolve_playlist(query, requester)
        return ResolvedQuery(tracks=[await self._resolve_single(query, requester)])

    async def build_audio_source(
        self, track: TrackInfo, *, volume: float
    ) -> discord.PCMVolumeTransformer:
        """Re-resolve the track and return a volume-adjustable PCM source."""

        not_found_message = f"Could not stream: {track.title}"
        data = await self._extract(
            self._ytdl, track.webpage_url or track.query, not_found_message
        )
        data = _first_entry(data, not_found_message)

        stream_url = data.get("url")
        if not stream_url:
            raise TrackNotFoundError(f"No audio stream for: {track.title}")

        pcm = discord.FFmpegPCMAudio(
            stream_url,
            before_options=_FFMPEG_BEFORE_OPTIONS,
            options=_FFMPEG_OPTIONS,
        )
        return discord.PCMVolumeTransformer(pcm, volume=volume)

    async def _resolve_single(
        self, query: str, requester: discord.abc.User
    ) -> TrackInfo:
        not_found_message = f"No results for: {query}"
        data = await self._extract(self._ytdl, query, not_found_message)
        data = _first_entry(data, not_found_message)
        return _build_track(
            data,
            requester,
            webpage_url=data.get("webpage_url") or query,
            query=query,
        )

    async def _resolve_playlist(
        self, query: str, requester: discord.abc.User
    ) -> ResolvedQuery:
        data = await self._extract(
            self._playlist_ytdl, query, f"No results for: {query}"
        )
        if "entries" not in data:
            # yt-dlp may resolve the link to a lone video; treat it as such.
            url = _entry_url(data) or query
            track = _build_track(data, requester, webpage_url=url, query=url)
            return ResolvedQuery(tracks=[track])

        tracks = []
        for entry in data["entries"]:
            if not _is_available(entry):
                continue
            url = _entry_url(entry)
            if url is None:
                continue
            tracks.append(_build_track(entry, requester, webpage_url=url, query=url))

        if not tracks:
            raise TrackNotFoundError(f"No playable tracks in playlist: {query}")
        return ResolvedQuery(tracks=tracks, playlist_title=data.get("title"))

    @staticmethod
    async def _extract(
        ytdl: yt_dlp.YoutubeDL, query: str, not_found_message: str
    ) -> dict:
        """Run the blocking yt-dlp extraction in the default executor."""

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=False)
            )
        except yt_dlp.utils.DownloadError as error:
            raise TrackNotFoundError(str(error)) from error

        if data is None:
            raise TrackNotFoundError(not_found_message)
        return data


def _playlist_options(base_options: dict, max_playlist_tracks: int) -> dict:
    """Options for fast playlist listing: flat entries, no per-video lookups.

    A `max_playlist_tracks` of 0 disables the cap.
    """

    options = {**base_options, "noplaylist": False, "extract_flat": "in_playlist"}
    if max_playlist_tracks > 0:
        options["playlistend"] = max_playlist_tracks
    return options


def _is_playlist_url(query: str) -> bool:
    """True for YouTube links carrying a `list` parameter.

    Covers both `/playlist?list=...` and `watch?v=...&list=...`.
    """

    parsed = urlparse(query)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not any(host == domain or host.endswith(f".{domain}") for domain in _YOUTUBE_HOSTS):
        return False
    return bool(parse_qs(parsed.query).get("list"))


def _first_entry(data: dict, not_found_message: str) -> dict:
    """Unwrap search results to their first non-empty entry."""

    if "entries" not in data:
        return data
    entries = [entry for entry in data["entries"] if entry]
    if not entries:
        raise TrackNotFoundError(not_found_message)
    return entries[0]


def _is_available(entry: Optional[dict]) -> bool:
    return entry is not None and entry.get("title") not in _UNAVAILABLE_TITLES


def _entry_url(entry: dict) -> Optional[str]:
    """Individual video URL of a (possibly flat) playlist entry."""

    for key in ("webpage_url", "url"):
        url = entry.get(key)
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    video_id = entry.get("id")
    if video_id:
        return _YOUTUBE_WATCH_URL.format(video_id=video_id)
    return None


def _build_track(
    data: dict,
    requester: discord.abc.User,
    *,
    webpage_url: str,
    query: str,
) -> TrackInfo:
    return TrackInfo(
        title=data.get("title") or "Unknown title",
        webpage_url=webpage_url,
        duration_seconds=_parse_duration(data.get("duration")),
        uploader=data.get("uploader") or data.get("channel"),
        requester_id=requester.id,
        requester_name=str(requester),
        query=query,
    )


def _parse_duration(raw_duration: object) -> Optional[int]:
    # Flat playlist entries may report durations as floats.
    if isinstance(raw_duration, (int, float)):
        return int(raw_duration)
    return None
