"""Centralized configuration loaded from environment variables.

Follows 12-factor app principles: all deploy-specific values come from the
environment, never from code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class MissingConfigError(Exception):
    """Raised when a mandatory environment variable is absent."""


@dataclass(frozen=True)
class BotConfig:
    """Immutable bot configuration."""

    discord_token: str
    command_prefix: str
    default_volume: float
    log_level: str
    inactivity_timeout_seconds: int
    disconnect_when_alone: bool
    empty_channel_grace_seconds: int
    max_playlist_tracks: int


def load_config() -> BotConfig:
    """Build a BotConfig from the process environment.

    Raises MissingConfigError if DISCORD_TOKEN is missing.
    """

    load_dotenv()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise MissingConfigError(
            "DISCORD_TOKEN is required. Copy .env.example to .env and set it."
        )

    return BotConfig(
        discord_token=token,
        command_prefix=os.getenv("COMMAND_PREFIX", "!"),
        default_volume=_parse_volume(os.getenv("DEFAULT_VOLUME", "0.5")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        inactivity_timeout_seconds=_parse_non_negative_int(
            os.getenv("INACTIVITY_TIMEOUT_SECONDS", "300"), "INACTIVITY_TIMEOUT_SECONDS"
        ),
        disconnect_when_alone=_parse_bool(
            os.getenv("DISCONNECT_WHEN_ALONE", "true"), "DISCONNECT_WHEN_ALONE"
        ),
        empty_channel_grace_seconds=_parse_non_negative_int(
            os.getenv("EMPTY_CHANNEL_GRACE_SECONDS", "60"), "EMPTY_CHANNEL_GRACE_SECONDS"
        ),
        max_playlist_tracks=_parse_non_negative_int(
            os.getenv("MAX_PLAYLIST_TRACKS", "100"), "MAX_PLAYLIST_TRACKS"
        ),
    )


def _parse_volume(raw_value: str) -> float:
    try:
        volume = float(raw_value)
    except ValueError as error:
        raise MissingConfigError(f"DEFAULT_VOLUME must be a number, got {raw_value!r}") from error
    if not 0.0 <= volume <= 1.0:
        raise MissingConfigError("DEFAULT_VOLUME must be between 0.0 and 1.0")
    return volume


def _parse_non_negative_int(raw_value: str, name: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise MissingConfigError(f"{name} must be a non-negative integer, got {raw_value!r}") from error
    if value < 0:
        raise MissingConfigError(f"{name} must be >= 0, got {value}")
    return value


def _parse_bool(raw_value: str, name: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise MissingConfigError(f"{name} must be true/false, got {raw_value!r}")
