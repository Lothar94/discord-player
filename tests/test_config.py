"""Unit tests for config.load_config."""

from __future__ import annotations

import pytest

from config import MissingConfigError, load_config


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    # Prevent the .env file in the repo from satisfying the variable.
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)
    with pytest.raises(MissingConfigError):
        load_config()


def test_default_values_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.delenv("COMMAND_PREFIX", raising=False)
    monkeypatch.delenv("DEFAULT_VOLUME", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)

    config = load_config()

    assert config.command_prefix == "!"
    assert config.default_volume == pytest.approx(0.5)
    assert config.log_level == "INFO"


def test_volume_out_of_range_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DEFAULT_VOLUME", "2.5")
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)
    with pytest.raises(MissingConfigError):
        load_config()


def test_volume_not_a_number_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DEFAULT_VOLUME", "loud")
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)
    with pytest.raises(MissingConfigError):
        load_config()


def test_inactivity_timeout_default_is_300(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.delenv("INACTIVITY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)

    config = load_config()

    assert config.inactivity_timeout_seconds == 300


def test_empty_channel_grace_default_is_60(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.delenv("EMPTY_CHANNEL_GRACE_SECONDS", raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)

    config = load_config()

    assert config.empty_channel_grace_seconds == 60


def test_disconnect_when_alone_default_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.delenv("DISCONNECT_WHEN_ALONE", raising=False)
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)

    config = load_config()

    assert config.disconnect_when_alone is True


def test_invalid_inactivity_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("INACTIVITY_TIMEOUT_SECONDS", "fast")
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: False)

    with pytest.raises(MissingConfigError):
        load_config()
