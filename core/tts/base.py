"""TTSAdapter interface. Nothing outside ``core/tts/`` talks to a speech engine directly.

Security rule: recognized text is untrusted. Adapters pass it via stdin, environment
variables or library calls, never inside a shell/PowerShell command string (ADR 0001).
"""
import logging
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List

from ..languages import engine_language, normalize_language
from ..status import EngineStatus

logger = logging.getLogger("tts")


class TTSErrorCode(str, Enum):
    ENGINE_NOT_AVAILABLE = "ENGINE_NOT_AVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    SYNTHESIS_FAILED = "SYNTHESIS_FAILED"
    AUDIO_DEVICE_UNAVAILABLE = "AUDIO_DEVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    ALL_ENGINES_FAILED = "ALL_ENGINES_FAILED"


class TTSError(Exception):
    def __init__(self, code: TTSErrorCode, engine: str, message: str = ""):
        super().__init__(f"[{engine}] {code.value}: {message}" if message else f"[{engine}] {code.value}")
        self.code = code
        self.engine = engine
        self.message = message


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class TTSAdapter(ABC):
    name: str = ""

    def __init__(self, engine_cfg: Dict[str, Any], tts_cfg: Dict[str, Any]):
        self.cfg = engine_cfg
        self.language = normalize_language(tts_cfg["language"])
        self.speed = float(tts_cfg["speed"])
        self.volume = clamp(float(tts_cfg["volume"]), 0.0, 1.0)
        self.status = EngineStatus.UNINITIALIZED
        self.status_detail = ""
        self.init_time = 0.0
        self._stop_requested = threading.Event()

    # ----- lifecycle -------------------------------------------------------------------------
    def initialize(self) -> EngineStatus:
        """Load the engine. Never raises; the outcome is recorded in ``status``."""
        if self.status != EngineStatus.UNINITIALIZED:
            return self.status
        if not self.cfg.get("enabled", True):
            return self._set_status(EngineStatus.DISABLED, "disabled in config")
        if engine_language(self.name, self.language) is None:
            return self._set_status(EngineStatus.LANGUAGE_NOT_SUPPORTED,
                                    f"language '{self.language}' not supported by {self.name}")
        t0 = time.perf_counter()
        try:
            status, detail = self._load()
        except Exception as e:
            logger.warning("%s init failed: %s", self.name, e, exc_info=logger.isEnabledFor(logging.DEBUG))
            status, detail = EngineStatus.INIT_FAILED, f"{type(e).__name__}: {e}"
        self.init_time = time.perf_counter() - t0
        return self._set_status(status, detail)

    def _set_status(self, status: EngineStatus, detail: str = "") -> EngineStatus:
        self.status, self.status_detail = status, detail
        if status == EngineStatus.READY:
            logger.info("TTS engine %s ready (%.1fs)", self.name, self.init_time)
        elif status != EngineStatus.DISABLED:
            logger.warning("TTS engine %s %s: %s", self.name, status.value, detail)
        return status

    def is_available(self) -> bool:
        return self.status == EngineStatus.READY

    # ----- speech ------------------------------------------------------------------------------
    def speak(self, text: str) -> bool:
        """Speak text and block until done. Returns False if interrupted by stop().

        Raises TTSError on failure.
        """
        if not self.is_available():
            raise TTSError(TTSErrorCode.ENGINE_NOT_AVAILABLE, self.name, self.status.value)
        if not isinstance(text, str) or not text.strip():
            raise TTSError(TTSErrorCode.INVALID_INPUT, self.name, "empty text")
        self._stop_requested.clear()
        try:
            self._speak(text)
        except TTSError:
            raise
        except Exception as e:
            logger.error("%s speech failed: %s", self.name, e, exc_info=True)
            raise TTSError(TTSErrorCode.SYNTHESIS_FAILED, self.name, f"{type(e).__name__}: {e}") from e
        return not self._stop_requested.is_set()

    def stop(self) -> None:
        """Interrupt current speech (safe to call from another thread, or when idle)."""
        self._stop_requested.set()
        try:
            self._stop()
        except Exception as e:
            logger.warning("%s stop failed: %s", self.name, e)

    # ----- engine specific -----------------------------------------------------------------------
    @abstractmethod
    def _load(self) -> "tuple[EngineStatus, str]":
        """Load from local storage only. Return (status, detail)."""

    @abstractmethod
    def _speak(self, text: str) -> None:
        """Synthesize and play; block until finished or stopped."""

    @abstractmethod
    def _stop(self) -> None:
        ...

    def get_languages(self) -> List[str]:
        return [self.language] if self.is_available() else []

    def get_voices(self) -> List[str]:
        return []

    def describe(self) -> Dict[str, Any]:
        return {"engine": self.name, "status": self.status.value, "detail": self.status_detail,
                "init_time_s": round(self.init_time, 2)}
