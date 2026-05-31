"""yt-dlp + FFmpeg audio source.

Resolves YouTube URLs and search queries into a streamable PCM source for
discord.py. Stream URLs are short-lived, so resolution happens just before
playback (see GuildPlayer).
"""

from __future__ import annotations

import asyncio
from typing import Optional

import discord
import yt_dlp

from .errors import TrackNotFoundError
from .track import TrackInfo


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


class YTDLSourceFactory:
    """Resolves queries into TrackInfo and produces audio sources on demand."""

    def __init__(self, ytdl_options: Optional[dict] = None) -> None:
        self._ytdl = yt_dlp.YoutubeDL(ytdl_options or _YTDL_OPTIONS)

    async def resolve(self, query: str, *, requester: discord.abc.User) -> TrackInfo:
        """Resolve a query (URL or free text) into TrackInfo metadata."""

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: self._ytdl.extract_info(query, download=False)
            )
        except yt_dlp.utils.DownloadError as error:
            raise TrackNotFoundError(str(error)) from error

        if data is None:
            raise TrackNotFoundError(f"No results for: {query}")

        if "entries" in data:
            entries = [entry for entry in data["entries"] if entry]
            if not entries:
                raise TrackNotFoundError(f"No results for: {query}")
            data = entries[0]

        return TrackInfo(
            title=data.get("title") or "Unknown title",
            webpage_url=data.get("webpage_url") or query,
            duration_seconds=data.get("duration"),
            uploader=data.get("uploader"),
            requester_id=requester.id,
            requester_name=str(requester),
            query=query,
        )

    async def build_audio_source(
        self, track: TrackInfo, *, volume: float
    ) -> discord.PCMVolumeTransformer:
        """Re-resolve the track and return a volume-adjustable PCM source."""

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                None, lambda: self._ytdl.extract_info(track.query, download=False)
            )
        except yt_dlp.utils.DownloadError as error:
            raise TrackNotFoundError(str(error)) from error

        if data is None:
            raise TrackNotFoundError(f"Could not stream: {track.title}")

        if "entries" in data:
            entries = [entry for entry in data["entries"] if entry]
            if not entries:
                raise TrackNotFoundError(f"Could not stream: {track.title}")
            data = entries[0]

        stream_url = data.get("url")
        if not stream_url:
            raise TrackNotFoundError(f"No audio stream for: {track.title}")

        pcm = discord.FFmpegPCMAudio(
            stream_url,
            before_options=_FFMPEG_BEFORE_OPTIONS,
            options=_FFMPEG_OPTIONS,
        )
        return discord.PCMVolumeTransformer(pcm, volume=volume)
