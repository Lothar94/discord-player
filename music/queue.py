"""Per-guild music queue with loop modes."""

from __future__ import annotations

import random
from collections import deque
from enum import Enum
from typing import Deque, List, Optional

from .errors import EmptyQueueError, InvalidPositionError
from .track import TrackInfo


class LoopMode(str, Enum):
    OFF = "off"
    TRACK = "track"
    QUEUE = "queue"


class MusicQueue:
    """In-memory FIFO queue with shuffle, remove, move and loop support."""

    def __init__(self) -> None:
        self._tracks: Deque[TrackInfo] = deque()
        self._loop_mode: LoopMode = LoopMode.OFF
        self._current: Optional[TrackInfo] = None

    @property
    def current(self) -> Optional[TrackInfo]:
        return self._current

    @property
    def loop_mode(self) -> LoopMode:
        return self._loop_mode

    @property
    def upcoming(self) -> List[TrackInfo]:
        return list(self._tracks)

    @property
    def is_empty(self) -> bool:
        return not self._tracks and self._current is None

    def __len__(self) -> int:
        return len(self._tracks)

    def enqueue(self, track: TrackInfo) -> None:
        self._tracks.append(track)

    def set_loop_mode(self, mode: LoopMode) -> None:
        self._loop_mode = mode

    def advance(self) -> Optional[TrackInfo]:
        """Pick the next track to play, honoring the active loop mode."""

        if self._loop_mode is LoopMode.TRACK and self._current is not None:
            return self._current

        if self._loop_mode is LoopMode.QUEUE and self._current is not None:
            self._tracks.append(self._current)

        if not self._tracks:
            self._current = None
            return None

        self._current = self._tracks.popleft()
        return self._current

    def clear(self) -> None:
        self._tracks.clear()

    def shuffle(self) -> None:
        if not self._tracks:
            raise EmptyQueueError("There is nothing to shuffle.")
        items = list(self._tracks)
        random.shuffle(items)
        self._tracks = deque(items)

    def remove_at(self, position: int) -> TrackInfo:
        index = self._validate_index(position)
        track = self._tracks[index]
        del self._tracks[index]
        return track

    def move(self, from_position: int, to_position: int) -> TrackInfo:
        source_index = self._validate_index(from_position)
        target_index = self._validate_index(to_position)
        track = self._tracks[source_index]
        del self._tracks[source_index]
        self._tracks.insert(target_index, track)
        return track

    def reset(self) -> None:
        self._tracks.clear()
        self._current = None
        self._loop_mode = LoopMode.OFF

    def _validate_index(self, one_based_position: int) -> int:
        if not self._tracks:
            raise EmptyQueueError("The queue is empty.")
        if one_based_position < 1 or one_based_position > len(self._tracks):
            raise InvalidPositionError(
                f"Position must be between 1 and {len(self._tracks)}."
            )
        return one_based_position - 1
