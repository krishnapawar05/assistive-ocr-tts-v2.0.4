"""Test/demo camera that replays in-memory frames and can simulate failures."""
import threading
import time
from typing import List, Optional

import numpy as np

from .base import CameraError, CameraInterface


class FrameSequenceCamera(CameraInterface):
    """Serves ``frames`` in order (looping by default).

    ``fail_opens`` makes the first N open() calls fail; ``disconnect_after`` makes read()
    return None forever after that many frames until the camera is reopened.
    """

    def __init__(self, frames: List[Optional[np.ndarray]], loop: bool = True, fail_opens: int = 0,
                 disconnect_after: Optional[int] = None, frame_interval_s: float = 0.01):
        self.frames = frames
        self.loop = loop
        self.fail_opens = fail_opens
        self.disconnect_after = disconnect_after
        self.frame_interval_s = frame_interval_s  # emulate a real camera's frame period
        self.open_calls = 0
        self.reads = 0
        self._open = False
        self._index = 0
        self._served_since_open = 0
        self._lock = threading.Lock()

    def open(self) -> None:
        with self._lock:
            self.open_calls += 1
            if self.open_calls <= self.fail_opens:
                raise CameraError("simulated: camera not connected")
            self._open = True
            self._served_since_open = 0

    def read(self) -> Optional[np.ndarray]:
        time.sleep(self.frame_interval_s)
        with self._lock:
            if not self._open:
                return None
            self.reads += 1
            if self.disconnect_after is not None and self._served_since_open >= self.disconnect_after:
                return None
            if self._index >= len(self.frames):
                if not self.loop:
                    return None
                self._index = 0
            frame = self.frames[self._index]
            self._index += 1
            self._served_since_open += 1
            return None if frame is None else frame.copy()

    def close(self) -> None:
        with self._lock:
            self._open = False

    @property
    def is_open(self) -> bool:
        return self._open
