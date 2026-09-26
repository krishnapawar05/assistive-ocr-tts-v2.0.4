"""TrOCR adapter (line-level handwriting recognizer).

v2.0.4 ran TrOCR on the whole frame, where it produced text even for blank frames. Here it
only sees line crops from ``regions.find_text_lines``, and each line gets a real confidence
(mean token probability), so hallucinated lines can be dropped.
"""
from typing import List

import cv2
import numpy as np

from .base import OCRAdapter, logger
from .regions import find_text_lines
from .types import EngineStatus, OCRResult


class TrOCRAdapter(OCRAdapter):
    name = "trocr"
    input_kind = "gray"

    def __init__(self, engine_cfg, language, region_cfg):
        super().__init__(engine_cfg, language)
        self.region_cfg = region_cfg
        self._processor = None
        self._model = None
        self._torch = None

    def _load(self):
        try:
            import torch
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel
            from transformers.utils import logging as hf_logging
        except ImportError:
            return EngineStatus.NOT_AVAILABLE, "transformers/torch not installed"
        model = self.cfg["model"]
        hf_logging.set_verbosity_error()  # silence the harmless "pooler weights not initialized" warning
        try:
            self._processor = TrOCRProcessor.from_pretrained(model, local_files_only=True)
            self._model = VisionEncoderDecoderModel.from_pretrained(model, local_files_only=True).eval()
        except OSError as e:
            return EngineStatus.MODEL_NOT_AVAILABLE, f"{model} not in local cache: {str(e)[:160]}"
        self._torch = torch
        return EngineStatus.READY, f"trocr {model}"

    def _recognize(self, image: np.ndarray) -> OCRResult:
        boxes = find_text_lines(image, self.region_cfg)
        if not boxes:
            return OCRResult(metadata={"regions": 0})
        rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB) if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        crops = [rgb[y:y + h, x:x + w] for x, y, w, h in boxes]
        torch = self._torch
        with torch.no_grad():
            pixel_values = self._processor(images=crops, return_tensors="pt").pixel_values
            out = self._model.generate(pixel_values, max_new_tokens=int(self.cfg["max_new_tokens"]),
                                       num_beams=1, return_dict_in_generate=True, output_scores=True)
            trans = self._model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
        texts = self._processor.batch_decode(out.sequences, skip_special_tokens=True)
        pad_id = self._model.generation_config.pad_token_id
        generated = out.sequences[:, 1:]  # first token is the decoder start token

        line_min = float(self.cfg["line_min_confidence"])
        kept_text: List[str] = []
        kept_conf: List[float] = []
        kept_boxes = []
        for i, text in enumerate(texts):
            mask = generated[i] != pad_id
            probs = torch.exp(trans[i][mask[: trans.shape[1]]])
            conf = float(probs.mean()) if probs.numel() else 0.0
            text = text.strip()
            logger.debug("trocr line %d conf=%.2f", i, conf)
            if text and conf >= line_min:
                kept_text.append(text)
                kept_conf.append(conf)
                kept_boxes.append(boxes[i])
        confidence = float(np.mean(kept_conf)) if kept_conf else 0.0
        return OCRResult(text=" ".join(kept_text), confidence=confidence, bounding_boxes=kept_boxes,
                         metadata={"regions": len(boxes), "lines_kept": len(kept_text),
                                   "line_confidences": kept_conf})
