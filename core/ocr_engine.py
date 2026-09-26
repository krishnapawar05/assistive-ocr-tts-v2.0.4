import logging
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("ocr_engine")

# Tesseract import (global so app-level diagnostics can use the flag)
try:
    import pytesseract
    try:
        pytesseract.get_tesseract_version()
        TESSER_AVAILABLE = True
    except Exception:
        TESSER_AVAILABLE = False
except ImportError:
    TESSER_AVAILABLE = False

LANG_MAP = {"eng": "en", "hin": "hi", "kan": "kn"}


class OCRResult:
    def __init__(self, text: str, boxes: List[Tuple[int, int, int, int]] = None, confidence: float = 0.0, engine: str = ""):
        self.text = text
        self.boxes = boxes or []
        self.confidence = confidence
        self.engine = engine


class OCREngine:
    """
    High-level OCR engine that can use multiple backends:
    - Tesseract          (always attempted – fastest to initialize)
    - PaddleOCR          (if installed)
    - EasyOCR            (if installed and handwriting_fallback=True)
    - TrOCR (Transformers) (if installed and use_trocr=True)

    We still keep the runtime lightweight by:
    - Doing minimal preprocessing
    - Running engines sequentially and choosing the best text
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lang = cfg.get("language", "eng")
        self.min_confidence = float(cfg.get("min_confidence", 0.5))
        self.min_text_len = int(cfg.get("min_text_len", 3))
        self.use_trocr = bool(cfg.get("use_trocr", True))
        self.handwriting_fallback = bool(cfg.get("handwriting_fallback", True))
        self.easyocr_langs = cfg.get("easyocr_languages", ["en"])
        self.parallel_ocr = bool(cfg.get("parallel_ocr", False))

        # --- Tesseract (always available if TESSER_AVAILABLE) ---
        if not TESSER_AVAILABLE:
            logger.warning("⚠️ Tesseract not available - install pytesseract and Tesseract OCR executable")

        # --- Optional engines: PaddleOCR, EasyOCR, TrOCR ---
        self.paddle = None
        self.easyocr = None
        self.trocr_processor = None
        self.trocr_model = None

        # PaddleOCR
        try:
            from paddleocr import PaddleOCR  # type: ignore

            lang_code = LANG_MAP.get(self.lang, "en")
            try:
                self.paddle = PaddleOCR(lang=lang_code, use_gpu=False, show_log=False)
                logger.info("✅ PaddleOCR initialized with lang=%s", lang_code)
            except Exception as e:
                logger.warning("⚠️ PaddleOCR init failed: %s", str(e)[:200])
                self.paddle = None
        except Exception as e:
            logger.info("ℹ️ PaddleOCR not available: %s", str(e)[:80])

        # EasyOCR (handwriting fallback)
        if self.handwriting_fallback:
            try:
                import easyocr  # type: ignore

                self.easyocr = easyocr.Reader(self.easyocr_langs, gpu=False)
                logger.info("✅ EasyOCR initialized with langs=%s", self.easyocr_langs)
            except Exception as e:
                logger.info("ℹ️ EasyOCR not available or failed to init: %s", str(e)[:120])
                self.easyocr = None

        # TrOCR (Transformers)
        if self.use_trocr:
            try:
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel  # type: ignore

                try:
                    self.trocr_processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-handwritten")
                    self.trocr_model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-handwritten")
                    self.trocr_model.eval()
                    logger.info("✅ TrOCR initialized (base-handwritten)")
                except Exception as e:
                    logger.warning("⚠️ TrOCR model load failed: %s", str(e)[:200])
                    self.trocr_processor = None
                    self.trocr_model = None
            except Exception as e:
                logger.info("ℹ️ TrOCR not available: %s", str(e)[:80])

    def _is_plausible_text(self, text: str) -> bool:
        """
        Extremely lightweight plausibility check.
        Goal: almost never block text as long as it has a few visible characters.
        """
        if not text:
            return False

        stripped = text.strip()
        if len(stripped) < self.min_text_len:
            return False

        # If we have at least one letter or digit, accept it.
        if any(c.isalnum() for c in stripped):
            return True

        # Otherwise reject (pure symbols/whitespace).
        return False

    def _ocr_tesseract(self, img: np.ndarray) -> Tuple[OCRResult, float]:
        """Ultra-fast Tesseract OCR - single PSM mode only."""
        if not TESSER_AVAILABLE:
            return OCRResult("", [], 0.0, "tesseract"), 0.0
        
        try:
            lang = LANG_MAP.get(self.lang, "eng")
            # Use only PSM 6 (fastest and most accurate for most cases)
            config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(img, lang=lang, config=config).strip()
            
            if not text or len(text) < self.min_text_len:
                return OCRResult("", [], 0.0, "tesseract"), 0.0
            
            if not self._is_plausible_text(text):
                return OCRResult("", [], 0.0, "tesseract"), 0.0
            
            # Estimate confidence based on text quality
            word_count = len(text.split())
            conf = 0.7 if word_count > 2 else 0.6
            
            return OCRResult(text, [], conf, "tesseract"), conf
        except Exception as e:
            logger.debug("Tesseract error: %s", str(e)[:50])
            return OCRResult("", [], 0.0, "tesseract"), 0.0

    def _ocr_paddle(self, img: np.ndarray) -> Tuple[OCRResult, float]:
        """Simple PaddleOCR wrapper."""
        if self.paddle is None:
            return OCRResult("", [], 0.0, "paddle"), 0.0
        try:
            res = self.paddle.ocr(img)
            if not res:
                return OCRResult("", [], 0.0, "paddle"), 0.0

            # Newer PaddleOCR returns [ [ [box], (text, conf) ], ... ]
            lines = res[0] if isinstance(res, list) and len(res) > 0 else res
            texts = []
            confidences = []
            for item in lines:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                data = item[1]
                if isinstance(data, (list, tuple)) and len(data) >= 2:
                    txt, conf = str(data[0]).strip(), float(data[1])
                else:
                    txt, conf = str(data).strip(), 0.6
                if txt:
                    texts.append(txt)
                    confidences.append(conf)
            if not texts:
                return OCRResult("", [], 0.0, "paddle"), 0.0
            text = " ".join(texts).strip()
            if not self._is_plausible_text(text):
                return OCRResult("", [], 0.0, "paddle"), 0.0
            conf = float(np.mean(confidences)) if confidences else 0.6
            return OCRResult(text, [], conf, "paddle"), conf
        except Exception as e:
            logger.debug("PaddleOCR error: %s", str(e)[:80])
            return OCRResult("", [], 0.0, "paddle"), 0.0

    def _ocr_easy(self, img: np.ndarray) -> Tuple[OCRResult, float]:
        """Simple EasyOCR wrapper."""
        if self.easyocr is None:
            return OCRResult("", [], 0.0, "easyocr"), 0.0
        try:
            # Ensure 3‑channel image
            if len(img.shape) == 2:
                img_color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                img_color = img
            output = self.easyocr.readtext(img_color, detail=1)
            if not output:
                return OCRResult("", [], 0.0, "easyocr"), 0.0
            texts = []
            confs = []
            for bbox, text, conf in output:
                text = (text or "").strip()
                if not text:
                    continue
                texts.append(text)
                confs.append(float(conf))
            if not texts:
                return OCRResult("", [], 0.0, "easyocr"), 0.0
            text = " ".join(texts).strip()
            if not self._is_plausible_text(text):
                return OCRResult("", [], 0.0, "easyocr"), 0.0
            conf = float(np.mean(confs)) if confs else 0.6
            return OCRResult(text, [], conf, "easyocr"), conf
        except Exception as e:
            logger.debug("EasyOCR error: %s", str(e)[:80])
            return OCRResult("", [], 0.0, "easyocr"), 0.0

    def _ocr_trocr(self, img: np.ndarray) -> Tuple[OCRResult, float]:
        """Simple TrOCR wrapper."""
        if self.trocr_processor is None or self.trocr_model is None:
            return OCRResult("", [], 0.0, "trocr"), 0.0
        try:
            # img is grayscale or BGR; convert to RGB PIL
            if len(img.shape) == 2:
                rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            else:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            inputs = self.trocr_processor(images=pil_img, return_tensors="pt").pixel_values
            generated_ids = self.trocr_model.generate(inputs)
            text = self.trocr_processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
            if not text or not self._is_plausible_text(text):
                return OCRResult("", [], 0.0, "trocr"), 0.0
            # Rough confidence estimate
            conf = 0.7
            return OCRResult(text, [], conf, "trocr"), conf
        except Exception as e:
            logger.debug("TrOCR error: %s", str(e)[:80])
            return OCRResult("", [], 0.0, "trocr"), 0.0

    def extract_text(self, frame: np.ndarray) -> OCRResult:
        """
        Ultra-fast text extraction - optimized for speed and detection.
        """
        if frame is None or frame.size == 0:
            return OCRResult("", [])
        
        # Use full frame for maximum text detection (faster than cropping)
        # Only crop if frame is very large
        h, w = frame.shape[:2]
        if max(h, w) > 1920:
            # Crop center 80% for very large frames
            x1, y1 = int(w * 0.1), int(h * 0.1)
            x2, y2 = int(w * 0.9), int(h * 0.9)
            crop = frame[y1:y2, x1:x2]
        else:
            crop = frame
        
        if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return OCRResult("", [])
        
        # Minimal preprocessing: convert to grayscale
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop
        
        # Quick resize if too small (improves detection)
        h_gray, w_gray = gray.shape[:2]
        if max(h_gray, w_gray) < 400:
            scale = 400 / max(h_gray, w_gray)
            new_w, new_h = int(w_gray * scale), int(h_gray * scale)
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # Run available engines and pick the best result
        candidates: List[Tuple[OCRResult, float]] = []

        # Tesseract
        res_tess, conf_tess = self._ocr_tesseract(gray)
        if res_tess.text:
            candidates.append((res_tess, conf_tess))

        # PaddleOCR (color image works better)
        if self.paddle is not None:
            res_pad, conf_pad = self._ocr_paddle(crop)
            if res_pad.text:
                candidates.append((res_pad, conf_pad))

        # EasyOCR
        if self.easyocr is not None:
            res_easy, conf_easy = self._ocr_easy(crop)
            if res_easy.text:
                candidates.append((res_easy, conf_easy))

        # TrOCR
        if self.trocr_model is not None and self.trocr_processor is not None:
            res_trocr, conf_trocr = self._ocr_trocr(gray)
            if res_trocr.text:
                candidates.append((res_trocr, conf_trocr))

        if not candidates:
            return OCRResult("", [])

        # Choose the best candidate by length, then confidence
        best_res, best_conf = max(
            candidates,
            key=lambda rc: (len(rc[0].text or ""), rc[1])
        )

        if best_res.text and len(best_res.text) >= self.min_text_len and best_conf >= self.min_confidence:
            return best_res

        return OCRResult("", [])
