"""AudioManager: one speech at a time, with a deterministic, configurable policy.

Policies for a new request while something is speaking or queued:
  queue          wait in FIFO order; if the queue is full the OLDEST queued item is dropped
  interrupt      stop current speech, discard the queue, speak the new request next
  drop_if_busy   discard the new request

Queued requests older than ``max_age_s`` are dropped instead of being read late.
"""
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, Optional

logger = logging.getLogger("audio")


@dataclass
class SpeechRequest:
    text: str
    source: str = "ocr"
    created: float = field(default_factory=time.monotonic)


class AudioManager:
    def __init__(self, cfg: Dict, speak_fn: Callable[[str], object], stop_fn: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic):
        self.policy = cfg["policy"]
        self.max_queue_size = int(cfg["max_queue_size"])
        self.max_age_s = float(cfg["max_age_s"])
        self.shutdown_timeout_s = float(cfg["shutdown_timeout_s"])
        self._speak = speak_fn
        self._stop = stop_fn
        self._clock = clock
        self._queue: Deque[SpeechRequest] = deque()
        self._cond = threading.Condition()
        self._speaking: Optional[SpeechRequest] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.stats = {"spoken": 0, "failed": 0, "interrupted": 0, "dropped_busy": 0,
                      "dropped_full": 0, "dropped_stale": 0}
        self.last_error: Optional[str] = None

    # ----- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        with self._cond:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._worker, name="audio", daemon=True)
        self._thread.start()

    def shutdown(self) -> bool:
        """Stop speech, drop the queue and join the worker. Returns True if it exited."""
        with self._cond:
            self._running = False
            self._queue.clear()
            if self._speaking is not None:
                self._stop()
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(self.shutdown_timeout_s)
            alive = self._thread.is_alive()
            if alive:
                logger.error("audio worker did not stop within %.1fs", self.shutdown_timeout_s)
            return not alive
        return True

    # ----- requests ----------------------------------------------------------------------------
    def submit(self, text: str, source: str = "ocr") -> str:
        """Apply the policy to a new request. Returns what happened to it."""
        req = SpeechRequest(text, source, self._clock())
        with self._cond:
            if not self._running:
                return "rejected_stopped"
            busy = self._speaking is not None or bool(self._queue)
            if self.policy == "drop_if_busy" and busy:
                self.stats["dropped_busy"] += 1
                return "dropped_busy"
            outcome = "queued"
            if self.policy == "interrupt":
                self._queue.clear()
                if self._speaking is not None:
                    # Stop while holding the lock: the worker cannot start the next request
                    # until we release it, so only the old speech can be cut off.
                    self.stats["interrupted"] += 1
                    self._stop()
                    outcome = "interrupting"
            elif len(self._queue) >= self.max_queue_size:
                self._queue.popleft()
                self.stats["dropped_full"] += 1
            self._queue.append(req)
            self._cond.notify_all()
        return outcome

    @property
    def is_speaking(self) -> bool:
        return self._speaking is not None

    def pending(self) -> int:
        with self._cond:
            return len(self._queue)

    def wait_idle(self, timeout: float) -> bool:
        """Block until nothing is queued or speaking (for tests and shutdown)."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._queue or self._speaking is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)
        return True

    # ----- worker ------------------------------------------------------------------------------
    def _worker(self) -> None:
        while True:
            with self._cond:
                while self._running and not self._queue:
                    self._cond.wait()
                if not self._running:
                    return
                req = self._queue.popleft()
                if self._clock() - req.created > self.max_age_s:
                    self.stats["dropped_stale"] += 1
                    logger.debug("dropping stale speech request (%.1fs old)", self._clock() - req.created)
                    self._cond.notify_all()
                    continue
                self._speaking = req
            try:
                self._speak(req.text)
                self.stats["spoken"] += 1
            except Exception as e:  # TTS failures must never kill the worker
                self.stats["failed"] += 1
                self.last_error = str(e)
                logger.error("speech failed: %s", e)
            finally:
                with self._cond:
                    self._speaking = None
                    self._cond.notify_all()
