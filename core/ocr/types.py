"""Engine-independent OCR types shared by adapters, scoring and the pipeline."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..status import EngineStatus  # noqa: F401  (re-exported)

BBox = Tuple[int, int, int, int]  # x, y, w, h in the coordinates of the image given to the adapter


class OCRErrorCode(str, Enum):
    ENGINE_NOT_AVAILABLE = "ENGINE_NOT_AVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    TIMEOUT = "TIMEOUT"
    BUSY = "BUSY"


class OCRError(Exception):
    def __init__(self, code: OCRErrorCode, engine: str, message: str = ""):
        super().__init__(f"[{engine}] {code.value}: {message}" if message else f"[{engine}] {code.value}")
        self.code = code
        self.engine = engine
        self.message = message


@dataclass
class OCRResult:
    """Normalized output of one engine on one image."""

    text: str = ""
    confidence: float = 0.0
    engine: str = ""
    language: str = ""
    processing_time: float = 0.0
    bounding_boxes: List[BBox] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass
class ScoredCandidate:
    result: OCRResult
    cleaned_text: str
    final_score: float
    components: Dict[str, float] = field(default_factory=dict)
    penalties: Dict[str, float] = field(default_factory=dict)


@dataclass
class OCRDecision:
    """What the OCR service concluded for one frame."""

    winner: Optional[ScoredCandidate]
    candidates: List[ScoredCandidate] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)    # engine -> error code
    engines_run: List[str] = field(default_factory=list)
    reason: str = ""
    processing_time: float = 0.0

    @property
    def text(self) -> str:
        return self.winner.cleaned_text if self.winner else ""
