"""Unit tests for music.queue.MusicQueue."""

from __future__ import annotations

import pytest

from music.errors import EmptyQueueError, InvalidPositionError
from music.queue import LoopMode, MusicQueue
from music.track import TrackInfo


def _make_track(title: str) -> TrackInfo:
    return TrackInfo(
        title=title,
        webpage_url=f"https://example.com/{title}",
        duration_seconds=120,
        uploader="tester",
        requester_id=1,
        requester_name="tester",
        query=title,
    )


def test_new_queue_is_empty() -> None:
    queue = MusicQueue()
    assert queue.is_empty
    assert queue.current is None
    assert queue.loop_mode is LoopMode.OFF


def test_enqueue_and_advance_consumes_fifo_order() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))

    first = queue.advance()
    second = queue.advance()
    third = queue.advance()

    assert first.title == "a"
    assert second.title == "b"
    assert third is None


def test_loop_track_replays_current() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.advance()
    queue.set_loop_mode(LoopMode.TRACK)

    again = queue.advance()
    assert again.title == "a"


def test_loop_queue_rotates_tracks() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.advance()  # current = a
    queue.set_loop_mode(LoopMode.QUEUE)

    second = queue.advance()  # b, a re-enqueued
    third = queue.advance()  # a again

    assert second.title == "b"
    assert third.title == "a"


def test_remove_at_position_uses_one_based_index() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.enqueue(_make_track("c"))

    removed = queue.remove_at(2)

    assert removed.title == "b"
    assert [track.title for track in queue.upcoming] == ["a", "c"]


def test_remove_at_invalid_position_raises() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    with pytest.raises(InvalidPositionError):
        queue.remove_at(5)


def test_remove_on_empty_queue_raises() -> None:
    queue = MusicQueue()
    with pytest.raises(EmptyQueueError):
        queue.remove_at(1)


def test_move_reorders_tracks() -> None:
    queue = MusicQueue()
    for title in ("a", "b", "c"):
        queue.enqueue(_make_track(title))

    queue.move(3, 1)

    assert [track.title for track in queue.upcoming] == ["c", "a", "b"]


def test_shuffle_preserves_track_set() -> None:
    queue = MusicQueue()
    titles = ["a", "b", "c", "d", "e"]
    for title in titles:
        queue.enqueue(_make_track(title))

    queue.shuffle()

    assert sorted(track.title for track in queue.upcoming) == sorted(titles)


def test_shuffle_empty_raises() -> None:
    queue = MusicQueue()
    with pytest.raises(EmptyQueueError):
        queue.shuffle()


def test_clear_removes_upcoming_but_not_current() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.advance()  # current = a

    queue.clear()

    assert queue.current.title == "a"
    assert queue.upcoming == []


def test_reset_clears_everything() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.advance()
    queue.set_loop_mode(LoopMode.QUEUE)

    queue.reset()

    assert queue.is_empty
    assert queue.current is None
    assert queue.loop_mode is LoopMode.OFF


def test_drop_current_lets_track_loop_advance() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.advance()  # current = a
    queue.set_loop_mode(LoopMode.TRACK)

    queue.drop_current()

    assert queue.current is None
    assert queue.advance().title == "b"


def test_drop_current_is_not_requeued_in_queue_loop() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.advance()  # current = a
    queue.set_loop_mode(LoopMode.QUEUE)

    queue.drop_current()

    assert queue.advance() is None


def test_request_skip_advances_once_in_track_loop() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.advance()  # current = a
    queue.set_loop_mode(LoopMode.TRACK)

    queue.request_skip()
    skipped_to = queue.advance()
    looped = queue.advance()

    assert skipped_to.title == "b"
    assert looped.title == "b"
    assert queue.loop_mode is LoopMode.TRACK


def test_request_skip_keeps_queue_loop_rotation() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.enqueue(_make_track("b"))
    queue.advance()  # current = a
    queue.set_loop_mode(LoopMode.QUEUE)

    queue.request_skip()

    assert queue.advance().title == "b"
    assert [track.title for track in queue.upcoming] == ["a"]


def test_request_skip_is_consumed_by_next_advance() -> None:
    queue = MusicQueue()
    queue.enqueue(_make_track("a"))
    queue.request_skip()
    queue.advance()  # current = a, consumes the skip
    queue.set_loop_mode(LoopMode.TRACK)

    assert queue.advance().title == "a"
