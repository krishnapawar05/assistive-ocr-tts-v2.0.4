"""TrOCR is region-only (ADR 0007): real engines on no-text scenes and handwriting.

Split from test_ocr_pipeline.py so that each test process holds fewer models on 8 GB machines.
"""
import os
import tempfile
import unittest

import cv2

from core.pipeline import AssistivePipeline
from core.tts.service import TTSService
from tests.helpers import RecordingTTS, default_config, make_config
from tests.integration.test_ocr_pipeline import (NO_TEXT_SCENES, _OPEN_SERVICES, frame, real_service,
                                                 recognize_once)
from tests.ocr.engine_case import FIXTURES, MANIFEST, cer, load_adapter


class TrOCRRegionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not load_adapter("easyocr").is_available or not load_adapter("trocr").is_available:
            raise unittest.SkipTest("NOT_AVAILABLE: needs EasyOCR and TrOCR")

    def tearDown(self):
        while _OPEN_SERVICES:
            _OPEN_SERVICES.pop().shutdown()

    def test_handwriting_read_by_trocr_from_detected_regions(self):
        for fid in ("hand_meet", "hand_notes"):
            with self.subTest(fixture=fid):
                d = recognize_once(fid, "single_engine", "trocr", ["easyocr"], text_type="handwritten")
                self.assertEqual((d.engines_run, d.region_source), (["trocr"], "easyocr"))
                self.assertLessEqual(cer(MANIFEST[fid]["text"], d.text), 0.25, d.text)

    # ----- TrOCR false positives on scenes without text (ADR 0007) -------------------------------
    def test_no_text_scenes_make_full_frame_trocr_invent_text(self):
        """Precondition: the fixtures reproduce the runtime bug when TrOCR looks at a whole frame."""
        trocr = load_adapter("trocr")
        if not trocr.is_available:
            self.skipTest("NOT_AVAILABLE: TrOCR")
        for fid in NO_TEXT_SCENES:
            with self.subTest(scene=fid):
                self.assertTrue(trocr.recognize(frame(fid).gray).text)  # standalone full-frame path
        res = trocr.recognize(frame("scene_room").gray)
        self.assertGreaterEqual(res.confidence, default_config()["ocr"]["min_confidence"], res.text)

    def test_no_text_scene_yields_no_text_and_trocr_is_not_run(self):
        cases = [("scene_room", "fallback", "easyocr", ["paddle", "tesseract", "trocr"]),  # runtime default order
                 ("scene_room", "ensemble", "easyocr", ["paddle", "trocr"]),
                 ("scene_room", "fallback", "trocr", ["easyocr", "paddle"]),
                 ("scene_room", "single_engine", "trocr", ["easyocr"]),
                 ("scene_clock_switch", "fallback", "easyocr", ["paddle", "tesseract", "trocr"])]
        for fid, mode, engine, order in cases:
            with self.subTest(scene=fid, mode=mode, primary=engine):
                d = recognize_once(fid, mode, engine, order)
                self.assertEqual(d.text, "", [(c.result.engine, c.cleaned_text) for c in d.candidates])
                self.assertNotIn("trocr", d.engines_run)
                self.assertEqual(d.skipped.get("trocr"), "no_text_region")

    def test_no_text_scene_is_never_spoken(self):
        """Whole pipeline, runtime fallback order, real OCR engines: nothing reaches the speaker."""
        cfg = default_config()
        cfg["frame"]["change_detection"]["enabled"] = False
        cfg["tts"].update(engine="coqui", fallback_engines=[])
        tts = TTSService(cfg["tts"], adapters={"coqui": RecordingTTS("coqui")})
        with tempfile.TemporaryDirectory() as tmp:
            p = AssistivePipeline(make_config(tmp, cfg), camera_factory=lambda _c: None,
                                  ocr_service=real_service("fallback", "easyocr", ["paddle", "tesseract", "trocr"]),
                                  tts_service=tts)
            try:
                for fid in NO_TEXT_SCENES:
                    with self.subTest(scene=fid):
                        self.assertEqual(p.process_frame(cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"]))).status,
                                         "no_text")
                self.assertTrue(p.audio.wait_idle(10))
                self.assertEqual(tts.adapters["coqui"].spoken, [])
            finally:
                p.shutdown()


if __name__ == "__main__":
    unittest.main()
