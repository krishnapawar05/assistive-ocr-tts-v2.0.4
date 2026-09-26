"""OCRAdapter interface. Every OCR engine is wrapped by one adapter; nothing outside
``core/ocr/`` imports an OCR library directly."""
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np

from ..languages import engine_language
from .types import EngineStatus, OCRError, OCRErrorCode, OCRResult

logger = logging.getLogger("ocr")


class OCRAdapter(ABC):
    #: Engine id used in config, results and logs.
    name: str = ""
    #: "color" (BGR) or "gray" — which preprocessed image the engine expects.
    input_kind: str = "color"

    def __init__(self, engine_cfg: Dict[str, Any], language: str):
        self.cfg = engine_cfg
        self.language = language
        self.status = EngineStatus.UNINITIALIZED
        self.status_detail = ""
        self.init_time = 0.0

    # ----- lifecycle -------------------------------------------------------------------
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
        except Exception as e:  # engine libraries raise anything on init
            logger.warning("%s init failed: %s", self.name, e, exc_info=logger.isEnabledFor(logging.DEBUG))
            status, detail = EngineStatus.INIT_FAILED, f"{type(e).__name__}: {e}"
        self.init_time = time.perf_counter() - t0
        return self._set_status(status, detail)

    def _set_status(self, status: EngineStatus, detail: str = "") -> EngineStatus:
        self.status, self.status_detail = status, detail
        if status == EngineStatus.READY:
            logger.info("OCR engine %s ready (%.1fs)", self.name, self.init_time)
        elif status != EngineStatus.DISABLED:
            logger.warning("OCR engine %s %s: %s", self.name, status.value, detail)
        return status

    @property
    def is_available(self) -> bool:
        return self.status == EngineStatus.READY

    # ----- inference -------------------------------------------------------------------
    def recognize(self, image: np.ndarray) -> OCRResult:
        """Run OCR on one preprocessed image. Raises OCRError on failure."""
        if not self.is_available:
            raise OCRError(OCRErrorCode.ENGINE_NOT_AVAILABLE, self.name, self.status.value)
        if not isinstance(image, np.ndarray) or image.size == 0 or image.ndim not in (2, 3):
            raise OCRError(OCRErrorCode.INVALID_INPUT, self.name, "empty or malformed image")
        t0 = time.perf_counter()
        try:
            result = self._recognize(image)
        except OCRError:
            raise
        except Exception as e:
            logger.error("%s inference failed: %s", self.name, e, exc_info=True)
            raise OCRError(OCRErrorCode.INFERENCE_FAILED, self.name, f"{type(e).__name__}: {e}") from e
        result.engine = self.name
        result.language = self.language
        result.processing_time = time.perf_counter() - t0
        result.text = result.text.strip()
        result.confidence = float(min(1.0, max(0.0, result.confidence)))
        return result

    # ----- engine specific ---------------------------------------------------------------
    @abstractmethod
    def _load(self) -> "tuple[EngineStatus, str]":
        """Load models from local storage only. Return (status, detail)."""

    @abstractmethod
    def _recognize(self, image: np.ndarray) -> OCRResult:
        """Engine inference. May raise; the base class maps exceptions to OCRError."""

    def describe(self) -> Dict[str, Any]:
        return {"engine": self.name, "status": self.status.value, "detail": self.status_detail,
                "init_time_s": round(self.init_time, 2)}
