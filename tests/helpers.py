"""Shared test helpers: default config and a fake OCR adapter."""
import copy
from typing import Optional

import numpy as np

from core.config import DEFAULT_CONFIG
from core.ocr.base import OCRAdapter
from core.ocr.types import EngineStatus, OCRResult


def default_config(**overrides) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for path, value in overrides.items():
        cur = cfg
        parts = path.split("__")
        for p in parts[:-1]:
            cur = cur[p]
        cur[parts[-1]] = value
    return cfg


class FakeOCRAdapter(OCRAdapter):
    """Returns a scripted result; can simulate being unavailable, failing, or slow."""

    def __init__(self, name: str, text: str = "", confidence: float = 0.9,
                 load_status: EngineStatus = EngineStatus.READY, raise_exc: Optional[Exception] = None,
                 delay_s: float = 0.0, timeout_s: float = 5.0, language: str = "en"):
        self.name = name
        super().__init__({"enabled": True, "timeout_s": timeout_s}, language)
        self.text = text
        self.confidence = confidence
        self.load_status = load_status
        self.raise_exc = raise_exc
        self.delay_s = delay_s
        self.calls = 0

    def _load(self):
        return self.load_status, "fake"

    def _recognize(self, image: np.ndarray) -> OCRResult:
        import time
        self.calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.raise_exc:
            raise self.raise_exc
        h, w = image.shape[:2]
        return OCRResult(text=self.text, confidence=self.confidence, bounding_boxes=[(0, 0, w // 2, h // 2)])


class NetworkAccessAttempted(AssertionError):
    pass


class no_network:
    """Context manager that makes any outbound socket connection raise.

    Used to prove engines load and run offline (no hidden network calls).
    """

    def __enter__(self):
        import socket
        self._socket = socket
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex
        self._orig_create = socket.create_connection
        self.attempts = []

        def refuse(sock_self, address, *a, **k):
            self.attempts.append(address)
            raise NetworkAccessAttempted(f"network access attempted: {address}")

        def refuse_create(address, *a, **k):
            self.attempts.append(address)
            raise NetworkAccessAttempted(f"network access attempted: {address}")

        socket.socket.connect = refuse
        socket.socket.connect_ex = refuse
        socket.create_connection = refuse_create
        return self

    def __exit__(self, *exc):
        self._socket.socket.connect = self._orig_connect
        self._socket.socket.connect_ex = self._orig_connect_ex
        self._socket.create_connection = self._orig_create
        return False


def blank_frame(w: int = 320, h: int = 240, value: int = 255) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def text_frame(text: str = "Room 204", w: int = 640, h: int = 240) -> np.ndarray:
    import cv2
    img = blank_frame(w, h)
    cv2.putText(img, text, (20, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4)
    return img
