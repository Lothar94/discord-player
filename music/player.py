"""Per-guild playback coordinator.

Owns the MusicQueue and drives the discord VoiceClient. After each track ends
discord schedules `_on_playback_finished` which advances the queue and starts
the next track.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Callable, Optional

import discord

from .errors import NotConnectedError, TrackNotFoundError
from .queue import LoopMode, MusicQueue
from .sources import YTDLSourceFactory
from .track import TrackInfo

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class AutoDisconnectConfig:
    inactivity_timeout: int = 300
    empty_channel_grace: int = 60
    disconnect_when_alone: bool = True


class GuildPlayer:
    """Coordinates queue + voice client for a single guild."""

    def __init__(
        self,
        guild: discord.Guild,
        source_factory: YTDLSourceFactory,
        default_volume: float,
        loop: asyncio.AbstractEventLoop,
        notify_channel: Optional[discord.abc.Messageable] = None,
        auto_disconnect: Optional[AutoDisconnectConfig] = None,
        on_disconnect: Optional[Callable[[int], None]] = None,
    ) -> None:
        cfg = auto_disconnect if auto_disconnect is not None else AutoDisconnectConfig()
        self._guild = guild
        self._source_factory = source_factory
        self._volume = default_volume
        self._notify_channel = notify_channel
        self._loop = loop
        self._queue = MusicQueue()
        self._lock = asyncio.Lock()
        self._inactivity_timeout = cfg.inactivity_timeout
        self._empty_channel_grace = cfg.empty_channel_grace
        self._disconnect_when_alone = cfg.disconnect_when_alone
        self._on_disconnect = on_disconnect
        self._idle_task: Optional[asyncio.Task] = None
        self._empty_channel_task: Optional[asyncio.Task] = None
        self._disconnecting: bool = False

    @property
    def queue(self) -> MusicQueue:
        return self._queue

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        return self._guild.voice_client  # type: ignore[return-value]

    def set_notify_channel(self, channel: discord.abc.Messageable) -> None:
        self._notify_channel = channel

    async def enqueue(self, track: TrackInfo) -> None:
        async with self._lock:
            self._queue.enqueue(track)
        self._cancel_idle_timer()
        if not self._is_playing_or_paused():
            await self._play_next()

    async def enqueue_many(self, tracks: list[TrackInfo]) -> None:
        """Enqueue tracks in order, starting playback once if idle."""

        if not tracks:
            return
        async with self._lock:
            for track in tracks:
                self._queue.enqueue(track)
        self._cancel_idle_timer()
        if not self._is_playing_or_paused():
            await self._play_next()

    async def skip(self) -> None:
        voice = self._require_voice_client()
        if voice.is_playing() or voice.is_paused():
            voice.stop()

    async def pause(self) -> None:
        voice = self._require_voice_client()
        if voice.is_playing():
            voice.pause()
            self._restart_idle_timer()

    async def resume(self) -> None:
        voice = self._require_voice_client()
        if voice.is_paused():
            self._cancel_idle_timer()
            voice.resume()

    async def set_volume(self, new_volume: float) -> None:
        self._volume = max(0.0, min(1.0, new_volume))
        voice = self.voice_client
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = self._volume

    async def set_loop(self, mode: LoopMode) -> None:
        self._queue.set_loop_mode(mode)

    async def stop_and_disconnect(self) -> None:
        if self._disconnecting:
            return
        self._disconnecting = True
        self._cancel_idle_timer()
        self.cancel_empty_channel_timer()
        voice = self.voice_client
        self._queue.reset()
        if voice is not None:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
            await voice.disconnect(force=False)
        if self._on_disconnect is not None:
            self._on_disconnect(self._guild.id)

    def start_empty_channel_timer(self) -> None:
        if not self._disconnect_when_alone:
            return
        if self._empty_channel_task is not None and not self._empty_channel_task.done():
            return
        self._empty_channel_task = asyncio.ensure_future(
            self._run_empty_channel_timer()
        )

    def cancel_empty_channel_timer(self) -> None:
        if self._empty_channel_task is not None:
            self._empty_channel_task.cancel()
            self._empty_channel_task = None

    def _restart_idle_timer(self) -> None:
        self._cancel_idle_timer()
        if self._inactivity_timeout <= 0:
            return
        self._idle_task = asyncio.ensure_future(
            self._run_idle_timer()
        )

    def _cancel_idle_timer(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    async def _run_idle_timer(self) -> None:
        await asyncio.sleep(self._inactivity_timeout)
        await self._notify(f"Disconnected after {self._inactivity_timeout}s of inactivity.")
        await self.stop_and_disconnect()

    async def _run_empty_channel_timer(self) -> None:
        await asyncio.sleep(self._empty_channel_grace)
        await self._notify("Disconnected because the channel was empty.")
        await self.stop_and_disconnect()

    def _require_voice_client(self) -> discord.VoiceClient:
        voice = self.voice_client
        if voice is None or not voice.is_connected():
            raise NotConnectedError("I'm not connected to a voice channel.")
        return voice

    def _is_playing_or_paused(self) -> bool:
        voice = self.voice_client
        return voice is not None and (voice.is_playing() or voice.is_paused())

    async def _play_next(self) -> None:
        next_track = self._queue.advance()
        if next_track is None:
            self._restart_idle_timer()
            return

        self._cancel_idle_timer()
        voice = self.voice_client
        if voice is None or not voice.is_connected():
            logger.warning("Voice client gone while advancing queue in guild %s", self._guild.id)
            return

        try:
            audio_source = await self._source_factory.build_audio_source(
                next_track, volume=self._volume
            )
        except TrackNotFoundError as error:
            await self._notify(f"Skipping '{next_track.title}': {error}")
            await self._play_next()
            return

        voice.play(audio_source, after=self._on_playback_finished)
        await self._notify_now_playing(next_track)

    def _on_playback_finished(self, error: Optional[Exception]) -> None:
        if error is not None:
            logger.error("Playback error in guild %s: %s", self._guild.id, error)
        # discord.py invokes this from the audio thread; never block it.
        future = asyncio.run_coroutine_threadsafe(self._play_next(), self._loop)
        future.add_done_callback(self._log_advance_failure)

    def _log_advance_failure(self, future) -> None:
        exception = future.exception()
        if exception is not None:
            logger.error(
                "Failed to advance queue in guild %s: %s",
                self._guild.id,
                exception,
            )

    async def _notify_now_playing(self, track: TrackInfo) -> None:
        await self._notify(f"Now playing: **{track.title}** ({track.duration_label})")

    async def _notify(self, message: str) -> None:
        if self._notify_channel is None:
            return
        try:
            await self._notify_channel.send(message)
        except discord.DiscordException:
            logger.warning("Failed to send notification in guild %s", self._guild.id)
