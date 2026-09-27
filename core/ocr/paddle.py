"""PaddleOCR 3.x adapter.

Models are passed as explicit local directories so PaddleX never downloads at runtime.
The 2.x API used by v2.0.4 (``use_gpu``, ``show_log``, ``ocr()``) does not exist in 3.x.

Call an instance from one long-lived thread only (OCRService does): driven from a new thread per
call, a PaddlePaddle predictor leaks ~0.1 GB per thread and crashes natively (ADR 0006 addendum).
"""
import logging
import os
from typing import List

import numpy as np

from .base import OCRAdapter, logger
from .types import BBox, EngineStatus, OCRResult


class PaddleOCRAdapter(OCRAdapter):
    name = "paddle"
    input_kind = "color"

    def __init__(self, engine_cfg, language):
        super().__init__(engine_cfg, language)
        self._ocr = None

    def _model_dir(self, model_name: str) -> str:
        return os.path.join(os.path.expanduser(self.cfg["model_root"]), model_name)

    def _load(self):
        det_name = self.cfg["det_model"]
        rec_name = self.cfg["rec_models"].get(self.language)
        if not rec_name:
            return EngineStatus.LANGUAGE_NOT_SUPPORTED, f"no rec model configured for '{self.language}'"
        missing = [n for n in (det_name, rec_name)
                   if not os.path.isfile(os.path.join(self._model_dir(n), "inference.yml"))]
        if missing:
            return EngineStatus.MODEL_NOT_AVAILABLE, (
                f"model(s) not found under {self.cfg['model_root']}: {', '.join(missing)}")
        # Skip PaddleX's network check of the model hoster; everything is local.
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        # Creating a PaddleOCR engine sets the ROOT logger to WARNING, which silenced every INFO
        # log of the app once Paddle was lazily loaded. Restore the root logger afterwards.
        root = logging.getLogger()
        saved_level, saved_handlers = root.level, list(root.handlers)
        try:
            return self._create(det_name, rec_name)
        finally:
            root.setLevel(saved_level)
            root.handlers[:] = saved_handlers

    def _create(self, det_name: str, rec_name: str):
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            return EngineStatus.NOT_AVAILABLE, "paddleocr package not installed"
        kwargs = dict(
            device=self.cfg["device"],
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name=det_name,
            text_detection_model_dir=self._model_dir(det_name),
            text_recognition_model_name=rec_name,
            text_recognition_model_dir=self._model_dir(rec_name),
        )
        if self.cfg.get("det_limit_side_len"):
            kwargs["text_det_limit_side_len"] = int(self.cfg["det_limit_side_len"])
            kwargs["text_det_limit_type"] = self.cfg["det_limit_type"]
        self._ocr = PaddleOCR(**kwargs)
        return EngineStatus.READY, f"paddleocr det={det_name} rec={rec_name} device={self.cfg['device']}"

    def _recognize(self, image: np.ndarray) -> OCRResult:
        if image.ndim == 2:
            import cv2
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        results = self._ocr.predict(image)
        texts: List[str] = []
        confs: List[float] = []
        boxes: List[BBox] = []
        regions = []
        for res in results or []:
            rec_boxes = res.get("rec_boxes")
            for i, (text, score) in enumerate(zip(res.get("rec_texts", []), res.get("rec_scores", []))):
                text = (text or "").strip()
                if not text:
                    continue
                texts.append(text)
                confs.append(float(score))
                if rec_boxes is not None and i < len(rec_boxes):
                    x1, y1, x2, y2 = (int(v) for v in rec_boxes[i][:4])
                    boxes.append((x1, y1, x2 - x1, y2 - y1))
                    regions.append({"box": boxes[-1], "text": text})
        confidence = float(np.mean(confs)) if confs else 0.0
        logger.debug("paddle: %d lines, conf=%.2f", len(texts), confidence)
        return OCRResult(text=" ".join(texts), confidence=confidence, bounding_boxes=boxes,
                         metadata={"line_confidences": confs, "text_regions": regions})
