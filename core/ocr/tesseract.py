"""Tesseract adapter. Requires the pytesseract package AND the tesseract executable with the
traineddata for the configured language."""
import os
import shutil
from typing import List, Optional

import numpy as np

from ..languages import engine_language
from .base import OCRAdapter, logger
from .types import BBox, EngineStatus, OCRResult


class TesseractOCRAdapter(OCRAdapter):
    name = "tesseract"
    input_kind = "gray"

    def __init__(self, engine_cfg, language):
        super().__init__(engine_cfg, language)
        self._pt = None
        self._lang = engine_language(self.name, language)
        self.executable: Optional[str] = None
        self.installed_languages: List[str] = []

    def _find_executable(self) -> Optional[str]:
        configured = self.cfg.get("executable")
        if configured:
            return configured if os.path.isfile(configured) else None
        found = shutil.which("tesseract")
        if found:
            return found
        for path in self.cfg.get("search_paths", []):
            if os.path.isfile(path):
                return path
        return None

    def _load(self):
        try:
            import pytesseract
        except ImportError:
            return EngineStatus.NOT_AVAILABLE, "pytesseract package not installed"
        exe = self._find_executable()
        if not exe:
            return EngineStatus.NOT_AVAILABLE, (
                "tesseract executable not found (set ocr.engines.tesseract.executable or add it "
                "to PATH; see README 'Tesseract')")
        pytesseract.pytesseract.tesseract_cmd = exe
        version = pytesseract.get_tesseract_version()
        self.installed_languages = sorted(pytesseract.get_languages(config=""))
        if self._lang not in self.installed_languages:
            return EngineStatus.MODEL_NOT_AVAILABLE, (
                f"traineddata '{self._lang}' not installed (have: {', '.join(self.installed_languages)})")
        self._pt = pytesseract
        self.executable = exe
        return EngineStatus.READY, f"tesseract {version} at {exe}"

    def _recognize(self, image: np.ndarray) -> OCRResult:
        pt = self._pt
        config = f"--oem {int(self.cfg['oem'])} --psm {int(self.cfg['psm'])}"
        data = pt.image_to_data(image, lang=self._lang, config=config, output_type=pt.Output.DICT,
                                timeout=float(self.cfg["timeout_s"]))
        lines = {}
        confs: List[float] = []
        boxes: List[BBox] = []
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            conf = float(data["conf"][i])
            if not word or conf < 0:  # conf -1 marks non-word layout rows
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
            confs.append(conf / 100.0)
            boxes.append((int(data["left"][i]), int(data["top"][i]), int(data["width"][i]), int(data["height"][i])))
        text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
        confidence = float(np.mean(confs)) if confs else 0.0
        logger.debug("tesseract: %d words, conf=%.2f", len(confs), confidence)
        return OCRResult(text=text, confidence=confidence, bounding_boxes=boxes,
                         metadata={"word_confidences": confs})
