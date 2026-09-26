"""FrameController: owns the capture thread, rate-limits frames and recovers from camera loss."""
import logging
import threading
import time
from typing import Any, Dict, Optional

import numpy as np

from .base import CameraError, CameraInterface

logger = logging.getLogger("camera")


class FrameController:
    """Keeps only the newest frame (older ones are useless for reading) and reconnects with
    exponential backoff when the camera cannot be opened or stops delivering frames."""

    def __init__(self, camera: CameraInterface, cam_cfg: Dict[str, Any], capture_interval: float):
        self.camera = camera
        self.cfg = cam_cfg
        self.interval = float(capture_interval)
        self.state = "stopped"          # stopped | connecting | streaming | reconnecting
        self.last_error: Optional[str] = None
        self.frames_delivered = 0
        self.reconnects = 0
        self._latest: Optional[np.ndarray] = None
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self, timeout: float) -> bool:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        alive = False
        if self._thread is not None:
            self._thread.join(timeout)
            alive = self._thread.is_alive()
        self.camera.close()
        self.state = "stopped"
        return not alive

    def get_frame(self, timeout: float) -> Optional[np.ndarray]:
        """Take the newest frame (each frame is handed out once)."""
        with self._cond:
            if self._latest is None:
                self._cond.wait(timeout)
            frame, self._latest = self._latest, None
            return frame

    def status(self) -> Dict[str, Any]:
        return {"state": self.state, "last_error": self.last_error, "frames": self.frames_delivered,
                "reconnects": self.reconnects, **self.camera.describe()}

    def _set_state(self, state: str, error: Optional[str] = None) -> None:
        if state != self.state:
            if state == "streaming":
                logger.info("camera streaming")
            elif state == "reconnecting":
                logger.warning("camera unavailable: %s (retrying)", error)
            self.state = state
        if error:
            self.last_error = error

    def _run(self) -> None:
        delay = float(self.cfg["reconnect_initial_delay_s"])
        max_delay = float(self.cfg["reconnect_max_delay_s"])
        max_failures = int(self.cfg["max_consecutive_read_failures"])
        fail_sleep = float(self.cfg["read_failure_sleep_s"])
        failures = 0
        last_push = 0.0
        self._set_state("connecting")
        while not self._stop.is_set():
            if not self.camera.is_open:
                try:
                    self.camera.open()
                    delay = float(self.cfg["reconnect_initial_delay_s"])
                    failures = 0
                except CameraError as e:
                    self._set_state("reconnecting", str(e))
                    self._stop.wait(delay)
                    delay = min(max_delay, delay * 2)
                    continue
                except Exception as e:  # driver-level surprises must not kill capture
                    logger.error("camera open crashed: %s", e, exc_info=True)
                    self._set_state("reconnecting", f"{type(e).__name__}: {e}")
                    self._stop.wait(delay)
                    delay = min(max_delay, delay * 2)
                    continue

            frame = self.camera.read()
            if frame is None:
                failures += 1
                if failures >= max_failures:
                    self._set_state("reconnecting", f"no frames after {failures} reads (disconnected?)")
                    self.camera.close()
                    self.reconnects += 1
                    failures = 0
                else:
                    self._stop.wait(fail_sleep)
                continue
            failures = 0
            self._set_state("streaming")
            now = time.monotonic()
            if now - last_push < self.interval:
                continue  # keep draining the driver buffer so the next frame is fresh
            last_push = now
            with self._cond:
                self._latest = frame
                self.frames_delivered += 1
                self._cond.notify_all()
        self.camera.close()
