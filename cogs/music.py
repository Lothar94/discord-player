"""Music Cog: exposes all user-facing commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

import discord
from discord.ext import commands

from music.errors import (
    EmptyQueueError,
    InvalidPositionError,
    MusicError,
    NotConnectedError,
    TrackNotFoundError,
    UserNotInVoiceError,
)
from music.player import AutoDisconnectConfig, GuildPlayer
from music.queue import LoopMode
from music.sources import MAX_PLAYLIST_TRACKS, ResolvedQuery, YTDLSourceFactory
from music.track import TrackInfo

logger = logging.getLogger(__name__)

_QUEUE_PAGE_SIZE = 10


class Music(commands.Cog):
    """Music commands: play, queue, skip, pause, resume, etc."""

    def __init__(
        self,
        bot: commands.Bot,
        default_volume: float,
        auto_disconnect: AutoDisconnectConfig,
        source_factory: YTDLSourceFactory,
    ) -> None:
        self._bot = bot
        self._default_volume = default_volume
        self._auto_disconnect = auto_disconnect
        self._source_factory = source_factory
        self._players: Dict[int, GuildPlayer] = {}

    # --- Command implementations -------------------------------------------------

    @commands.command(name="join", aliases=["connect"])
    async def join(self, ctx: commands.Context) -> None:
        """Join the author's current voice channel."""

        await self._ensure_voice_connection(ctx)
        await ctx.send(f"Joined **{ctx.author.voice.channel.name}**.")

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a song or playlist by URL, or a YouTube search."""

        await self._ensure_voice_connection(ctx)
        player = self._get_player(ctx.guild)
        player.set_notify_channel(ctx.channel)

        async with ctx.typing():
            resolved = await self._source_factory.resolve(query, requester=ctx.author)
            await player.enqueue_many(resolved.tracks)

        await ctx.send(self._format_resolved(resolved, position=len(player.queue)))

    @commands.command(name="search")
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """Alias of play that forces YouTube search."""

        search_query = query if query.startswith("http") else f"ytsearch:{query}"
        await self.play(ctx, query=search_query)

    @commands.command(name="queue", aliases=["q"])
    async def show_queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Display the upcoming queue."""

        player = self._optional_player(ctx.guild)
        if player is None or player.queue.is_empty:
            await ctx.send("The queue is empty.")
            return

        upcoming = player.queue.upcoming
        total_pages = max(1, (len(upcoming) + _QUEUE_PAGE_SIZE - 1) // _QUEUE_PAGE_SIZE)
        page = max(1, min(page, total_pages))
        start = (page - 1) * _QUEUE_PAGE_SIZE
        end = start + _QUEUE_PAGE_SIZE

        lines = []
        current = player.queue.current
        if current is not None:
            lines.append(f"**Now playing:** {current.title} ({current.duration_label})")
        if upcoming:
            lines.append(f"\n**Up next (page {page}/{total_pages}):**")
            for offset, track in enumerate(upcoming[start:end], start=start + 1):
                lines.append(f"`{offset}.` {track.title} ({track.duration_label})")
        lines.append(f"\nLoop mode: `{player.queue.loop_mode.value}`")

        await ctx.send("\n".join(lines))

    @commands.command(name="clear")
    async def clear(self, ctx: commands.Context) -> None:
        """Clear all upcoming tracks (keeps the current song playing)."""

        player = self._require_player(ctx.guild)
        player.queue.clear()
        await ctx.send("Queue cleared.")

    @commands.command(name="skip", aliases=["s", "next"])
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current song."""

        player = self._require_player(ctx.guild)
        await player.skip()
        await ctx.send("Skipped.")

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        """Pause playback."""

        player = self._require_player(ctx.guild)
        await player.pause()
        await ctx.send("Paused.")

    @commands.command(name="resume")
    async def resume(self, ctx: commands.Context) -> None:
        """Resume playback."""

        player = self._require_player(ctx.guild)
        await player.resume()
        await ctx.send("Resumed.")

    @commands.command(name="remove", aliases=["rm"])
    async def remove(self, ctx: commands.Context, position: int) -> None:
        """Remove a song by its position in the queue."""

        player = self._require_player(ctx.guild)
        removed = player.queue.remove_at(position)
        await ctx.send(f"Removed `{position}.` **{removed.title}**.")

    @commands.command(name="move", aliases=["mv"])
    async def move(
        self, ctx: commands.Context, from_position: int, to_position: int
    ) -> None:
        """Move a song from one position to another."""

        player = self._require_player(ctx.guild)
        track = player.queue.move(from_position, to_position)
        await ctx.send(
            f"Moved **{track.title}** from `{from_position}` to `{to_position}`."
        )

    @commands.command(name="shuffle")
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle the queue."""

        player = self._require_player(ctx.guild)
        player.queue.shuffle()
        await ctx.send("Queue shuffled.")

    @commands.command(name="loop", aliases=["repeat"])
    async def loop(self, ctx: commands.Context, mode: str = "off") -> None:
        """Set loop mode: off, track, queue."""

        try:
            loop_mode = LoopMode(mode.lower())
        except ValueError:
            await ctx.send("Loop mode must be one of: `off`, `track`, `queue`.")
            return
        player = self._require_player(ctx.guild)
        await player.set_loop(loop_mode)
        await ctx.send(f"Loop mode set to `{loop_mode.value}`.")

    @commands.command(name="volume", aliases=["vol"])
    async def volume(self, ctx: commands.Context, percent: Optional[int] = None) -> None:
        """Show or set the volume (0-100)."""

        player = self._require_player(ctx.guild)
        if percent is None:
            await ctx.send(f"Current volume: `{int(player.volume * 100)}%`.")
            return
        if not 0 <= percent <= 100:
            await ctx.send("Volume must be between 0 and 100.")
            return
        await player.set_volume(percent / 100.0)
        await ctx.send(f"Volume set to `{percent}%`.")

    @commands.command(name="nowplaying", aliases=["np", "current"])
    async def now_playing(self, ctx: commands.Context) -> None:
        """Show the current song."""

        player = self._optional_player(ctx.guild)
        current = player.queue.current if player else None
        if current is None:
            await ctx.send("Nothing is playing.")
            return
        await ctx.send(
            f"**Now playing:** {current.title}\n"
            f"Duration: {current.duration_label}\n"
            f"Requested by: {current.requester_name}\n"
            f"Link: <{current.webpage_url}>"
        )

    @commands.command(name="stop", aliases=["leave", "disconnect", "dc"])
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback, clear the queue and leave the voice channel."""

        player = self._optional_player(ctx.guild)
        if player is not None:
            await player.stop_and_disconnect()
            self._players.pop(ctx.guild.id, None)
        await ctx.send("Stopped and disconnected.")

    # --- Error handling ---------------------------------------------------------

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument: {error}")
            return
        original = getattr(error, "original", error)
        if isinstance(original, (UserNotInVoiceError, NotConnectedError,
                                  EmptyQueueError, InvalidPositionError,
                                  TrackNotFoundError, MusicError)):
            await ctx.send(str(original))
            return
        logger.exception("Unexpected command error", exc_info=original)
        await ctx.send("An unexpected error occurred. Check the logs.")

    # --- Helpers ----------------------------------------------------------------

    async def _ensure_voice_connection(self, ctx: commands.Context) -> None:
        author_voice = getattr(ctx.author, "voice", None)
        if author_voice is None or author_voice.channel is None:
            raise UserNotInVoiceError("You must be in a voice channel first.")

        target_channel = author_voice.channel
        voice_client = ctx.guild.voice_client
        if voice_client is None:
            await target_channel.connect()
        elif voice_client.channel != target_channel:
            await voice_client.move_to(target_channel)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        for guild_id, player in list(self._players.items()):
            voice = player.voice_client
            if voice is None or not voice.is_connected():
                continue
            human_members = [m for m in voice.channel.members if not m.bot]
            if len(human_members) == 0:
                player.start_empty_channel_timer()
            else:
                player.cancel_empty_channel_timer()

    def _get_player(self, guild: discord.Guild) -> GuildPlayer:
        player = self._players.get(guild.id)
        if player is None:
            player = GuildPlayer(
                guild=guild,
                source_factory=self._source_factory,
                default_volume=self._default_volume,
                loop=asyncio.get_running_loop(),
                auto_disconnect=self._auto_disconnect,
                on_disconnect=lambda guild_id: self._players.pop(guild_id, None),
            )
            self._players[guild.id] = player
        return player

    def _optional_player(self, guild: discord.Guild) -> Optional[GuildPlayer]:
        return self._players.get(guild.id)

    def _require_player(self, guild: discord.Guild) -> GuildPlayer:
        player = self._players.get(guild.id)
        if player is None:
            raise NotConnectedError("I'm not connected to a voice channel.")
        return player

    @classmethod
    def _format_resolved(cls, resolved: ResolvedQuery, position: int) -> str:
        if len(resolved.tracks) == 1:
            return cls._format_enqueued(resolved.tracks[0], position=position)
        message = f"Enqueued **{len(resolved.tracks)}** tracks"
        if resolved.playlist_title:
            return f"{message} from playlist **{resolved.playlist_title}**."
        return f"{message}."

    @staticmethod
    def _format_enqueued(track: TrackInfo, position: int) -> str:
        if position == 0:
            return f"Playing now: **{track.title}** ({track.duration_label})"
        return (
            f"Enqueued at position `{position}`: **{track.title}** "
            f"({track.duration_label})"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(
        bot,
        default_volume=getattr(bot, "default_volume", 0.5),
        auto_disconnect=AutoDisconnectConfig(
            inactivity_timeout=getattr(bot, "inactivity_timeout_seconds", 300),
            disconnect_when_alone=getattr(bot, "disconnect_when_alone", True),
            empty_channel_grace=getattr(bot, "empty_channel_grace_seconds", 60),
        ),
        source_factory=YTDLSourceFactory(
            max_playlist_tracks=getattr(bot, "max_playlist_tracks", MAX_PLAYLIST_TRACKS),
        ),
    ))
