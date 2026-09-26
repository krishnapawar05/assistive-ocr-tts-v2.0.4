"""OCRService with the real engines on synthetic fixtures, in every mode."""
import copy
import os
import unittest

import cv2

from core.frame.processing import Preprocessor
from core.ocr.service import OCRService, build_adapters
from tests.helpers import FakeOCRAdapter, default_config
from tests.ocr import engine_case  # noqa: F401  (sets offline env)
from tests.ocr.engine_case import FIXTURES, MANIFEST, cer, load_adapter

PRE = Preprocessor(default_config()["frame"]["preprocess"])


def frame(fid):
    return PRE.prepare(cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"])))


def real_service(mode, engine, fallback_order, text_type="printed", **ocr_over):
    """OCRService over the cached real adapters (engines load once per test run)."""
    cfg = default_config()
    ocr = cfg["ocr"]
    ocr.update(mode=mode, engine=engine, fallback_order=fallback_order, text_type=text_type, **ocr_over)
    adapters = {name: load_adapter(name) for name in ("tesseract", "easyocr", "paddle", "trocr")}
    svc = OCRService(ocr, cfg["text"], adapters=adapters)
    svc.initialize()
    return svc


class OCRPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not load_adapter("easyocr").is_available or not load_adapter("paddle").is_available:
            raise unittest.SkipTest("NOT_AVAILABLE: needs EasyOCR and PaddleOCR")

    def test_single_engine_reads_sign(self):
        d = real_service("single_engine", "easyocr", []).recognize(frame("room_204"))
        self.assertEqual(d.text, "Room 204")
        self.assertEqual(d.engines_run, ["easyocr"])

    def test_single_engine_skips_unavailable_tesseract(self):
        d = real_service("single_engine", "tesseract", ["easyocr"]).recognize(frame("room_204"))
        self.assertEqual(d.winner.result.engine, "easyocr")

    def test_fallback_mode_accepts_primary_when_confident(self):
        d = real_service("fallback", "easyocr", ["paddle", "trocr"]).recognize(frame("sentence"))
        self.assertEqual(d.engines_run, ["easyocr"])
        self.assertLessEqual(cer(MANIFEST["sentence"]["text"], d.text), 0.05)

    def test_ensemble_agreement(self):
        d = real_service("ensemble", "easyocr", ["paddle", "trocr"]).recognize(frame("chapter_numbers"))
        self.assertEqual(sorted(d.engines_run), ["easyocr", "paddle", "trocr"])
        self.assertLessEqual(cer(MANIFEST["chapter_numbers"]["text"], d.text), 0.05)
        self.assertIn("agreement", d.winner.components)

    def test_ensemble_blank_frame_says_nothing(self):
        d = real_service("ensemble", "easyocr", ["paddle", "trocr"]).recognize(frame("blank"))
        self.assertIsNone(d.winner)

    def test_every_printed_fixture_in_fallback_mode(self):
        svc = real_service("fallback", "easyocr", ["paddle", "trocr"])
        for fid in ("room_204", "exit_inverted", "sentence", "chapter_numbers", "low_contrast", "blurred",
                    "greenboard", "whiteboard"):
            with self.subTest(fixture=fid):
                d = svc.recognize(frame(fid))
                self.assertLessEqual(cer(MANIFEST[fid]["text"], d.text), 0.1, f"{fid}: {d.text!r}")

    def test_poor_primary_triggers_real_fallback(self):
        """TEST 2 (OCR side): garbage from the primary -> a real engine is consulted and wins."""
        cfg = default_config()
        ocr = cfg["ocr"]
        ocr.update(mode="fallback", engine="tesseract", fallback_order=["easyocr"])
        garbage = FakeOCRAdapter("tesseract", "R§§m ¤¤4 ~~", 0.55)
        svc = OCRService(ocr, cfg["text"], adapters={"tesseract": garbage, "easyocr": load_adapter("easyocr")})
        svc.initialize()
        d = svc.recognize(frame("room_204"))
        self.assertEqual(d.engines_run, ["tesseract", "easyocr"])
        self.assertEqual(d.winner.result.engine, "easyocr")
        self.assertEqual(d.text, "Room 204")

    def test_handwritten_mode_uses_trocr(self):
        if not load_adapter("trocr").is_available:
            self.skipTest("NOT_AVAILABLE: TrOCR")
        d = real_service("fallback", "trocr", ["easyocr"], text_type="handwritten").recognize(frame("hand_meet"))
        self.assertLessEqual(cer(MANIFEST["hand_meet"]["text"], d.text), 0.25, d.text)

    def test_hindi_without_models_is_controlled(self):
        cfg = default_config()
        cfg["ocr"].update(language="hi", mode="fallback", engine="easyocr", fallback_order=["paddle", "trocr"])
        with self.assertLogs("ocr.service", level="ERROR"):
            svc = OCRService(cfg["ocr"], cfg["text"])
            statuses = svc.initialize()
        self.assertTrue(all(s != "READY" for s in statuses.values()), statuses)
        self.assertEqual(svc.recognize(frame("hindi_room")).reason, "no_engine_available")


if __name__ == "__main__":
    unittest.main()
