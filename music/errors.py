"""Custom exceptions used by the music domain.

Wrapping third-party errors lets the Cog produce friendly Discord messages
without leaking stack traces (OWASP A05).
"""


class MusicError(Exception):
    """Base class for all music-related errors."""


class TrackNotFoundError(MusicError):
    """Raised when yt-dlp cannot resolve a track."""


class EmptyQueueError(MusicError):
    """Raised when an operation requires a non-empty queue."""


class InvalidPositionError(MusicError):
    """Raised when a queue index is out of range."""


class NotConnectedError(MusicError):
    """Raised when an action needs an active voice connection."""


class UserNotInVoiceError(MusicError):
    """Raised when the command author is not in a voice channel."""
