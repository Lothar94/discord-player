"""Track metadata, dependency-free.

Lives in its own module so the pure-logic queue can be imported and tested
without pulling discord.py / yt-dlp transitively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrackInfo:
    """Metadata of a queued track.

    The original `query` is preserved so the playable stream URL can be
    re-resolved at play time (yt-dlp URLs are short-lived).
    """

    title: str
    webpage_url: str
    duration_seconds: Optional[int]
    uploader: Optional[str]
    requester_id: int
    requester_name: str
    query: str

    @property
    def duration_label(self) -> str:
        if self.duration_seconds is None:
            return "live"
        minutes, seconds = divmod(self.duration_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
