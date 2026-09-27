"""EasyOCR adapter. Models are loaded from local storage only (download_enabled=False)."""
import os
from typing import List

import numpy as np

from ..languages import engine_language
from .base import OCRAdapter, logger
from .types import BBox, EngineStatus, OCRResult


class EasyOCRAdapter(OCRAdapter):
    name = "easyocr"
    input_kind = "color"

    def __init__(self, engine_cfg, language):
        super().__init__(engine_cfg, language)
        self._reader = None

    def _languages(self) -> List[str]:
        langs = [engine_language(self.name, self.language)]
        if self.language != "en" and self.cfg.get("include_english", True):
            langs.append("en")  # EasyOCR's Devanagari/Kannada models are trained alongside English
        return langs

    def _load(self):
        try:
            import easyocr
        except ImportError:
            return EngineStatus.NOT_AVAILABLE, "easyocr package not installed"
        model_dir = self.cfg.get("model_dir") or None
        if model_dir:
            model_dir = os.path.expanduser(model_dir)
        try:
            self._reader = easyocr.Reader(self._languages(), gpu=bool(self.cfg.get("gpu", False)),
                                          model_storage_directory=model_dir, download_enabled=False,
                                          verbose=False)
        except FileNotFoundError as e:
            return EngineStatus.MODEL_NOT_AVAILABLE, str(e)
        return EngineStatus.READY, f"easyocr langs={self._languages()}"

    def _recognize(self, image: np.ndarray) -> OCRResult:
        if image.ndim == 2:
            import cv2
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        output = self._reader.readtext(image, detail=1, canvas_size=int(self.cfg["canvas_size"]),
                                       mag_ratio=float(self.cfg["mag_ratio"]),
                                       paragraph=False)
        texts: List[str] = []
        confs: List[float] = []
        boxes: List[BBox] = []
        for poly, text, conf in output:
            text = (text or "").strip()
            if not text:
                continue
            xs = [int(p[0]) for p in poly]
            ys = [int(p[1]) for p in poly]
            texts.append(text)
            confs.append(float(conf))
            boxes.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
        # EasyOCR's own output order is kept (same as v2.0.4).
        confidence = float(np.mean(confs)) if confs else 0.0
        logger.debug("easyocr: %d regions, conf=%.2f", len(texts), confidence)
        return OCRResult(text=" ".join(texts), confidence=confidence, bounding_boxes=boxes,
                         metadata={"line_confidences": confs,
                                   "text_regions": [{"box": b, "text": t} for b, t in zip(boxes, texts)]})
