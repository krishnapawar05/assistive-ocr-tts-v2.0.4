"""Frame preprocessing, quality assessment and change detection.

Preprocessing reproduces v2.0.4's ``OCREngine.extract_text`` steps (center crop of very large
frames, grayscale, upscale of tiny images), with every constant taken from config.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import cv2
import numpy as np


class FrameError(ValueError):
    """Frame is missing or malformed (corrupted buffer, wrong dtype/shape)."""


@dataclass
class PreparedFrame:
    color: np.ndarray            # BGR, possibly cropped/downscaled
    gray: np.ndarray             # grayscale, possibly upscaled

    def for_engine(self, input_kind: str) -> np.ndarray:
        return self.gray if input_kind == "gray" else self.color


@dataclass
class QualityReport:
    usable: bool
    reasons: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


def validate_frame(frame: Any) -> np.ndarray:
    if frame is None:
        raise FrameError("no frame")
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        raise FrameError("empty frame")
    if frame.dtype != np.uint8:
        raise FrameError(f"unexpected dtype {frame.dtype}")
    if frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if not (frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 3)):
        raise FrameError(f"unexpected shape {frame.shape}")
    return frame


class Preprocessor:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def prepare(self, frame: np.ndarray) -> PreparedFrame:
        frame = validate_frame(frame)
        color = frame if frame.ndim == 3 else cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        h, w = color.shape[:2]

        max_side = int(self.cfg["max_input_side"])
        if max_side and max(h, w) > max_side:
            scale = max_side / float(max(h, w))
            color = cv2.resize(color, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = color.shape[:2]

        if max(h, w) > int(self.cfg["crop_if_larger_than"]):
            m = float(self.cfg["crop_margin_fraction"])
            color = color[int(h * m):int(h * (1 - m)), int(w * m):int(w * (1 - m))]

        min_side = int(self.cfg["min_side"])
        if color.shape[0] < min_side or color.shape[1] < min_side:
            raise FrameError(f"frame too small after crop: {color.shape[:2]}")

        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        up = int(self.cfg["upscale_min_side"])
        gh, gw = gray.shape[:2]
        if max(gh, gw) < up:
            scale = up / float(max(gh, gw))
            gray = cv2.resize(gray, (int(gw * scale), int(gh * scale)), interpolation=cv2.INTER_LINEAR)
        return PreparedFrame(color=color, gray=gray)


class QualityAssessor:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg

    def assess(self, frame: np.ndarray) -> QualityReport:
        frame = validate_frame(frame)
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        mean, std = float(gray.mean()), float(gray.std())
        metrics = {"width": w, "height": h, "brightness": round(mean, 1), "contrast": round(std, 2)}
        if not self.cfg["enabled"]:
            return QualityReport(True, [], metrics)
        c = self.cfg
        reasons = []
        if w < c["min_width"] or h < c["min_height"]:
            reasons.append("low_resolution")
        if mean <= c["dark_mean_max"]:
            reasons.append("too_dark")
        if mean >= c["bright_mean_min"] and std <= c["bright_std_max"]:
            reasons.append("overexposed")
        if std < c["min_contrast_std"]:
            reasons.append("no_content")
        if c["min_sharpness"] > 0:
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            metrics["sharpness"] = round(sharp, 1)
            if sharp < c["min_sharpness"]:
                reasons.append("blurred")
        return QualityReport(not reasons, reasons, metrics)


class ChangeDetector:
    """Skip OCR on frames that look the same as the last processed one (event-driven, rule 6)."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self._last: Optional[np.ndarray] = None
        self._last_time = 0.0

    def _thumb(self, frame: np.ndarray) -> np.ndarray:
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        n = int(self.cfg["thumbnail_size"])
        return cv2.resize(gray, (n, n), interpolation=cv2.INTER_AREA).astype(np.int16)

    def is_unchanged(self, frame: np.ndarray, now: float) -> bool:
        if not self.cfg["enabled"] or self._last is None:
            return False
        if now - self._last_time >= float(self.cfg["max_skip_s"]):
            return False
        diff = float(np.abs(self._thumb(frame) - self._last).mean())
        return diff < float(self.cfg["min_mean_abs_diff"])

    def mark_processed(self, frame: np.ndarray, now: float) -> None:
        self._last = self._thumb(frame)
        self._last_time = now

    def reset(self) -> None:
        self._last = None
