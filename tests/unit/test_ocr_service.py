"""OCRService modes and failure handling, using fake adapters (no real engines)."""
import unittest

from core.frame.processing import Preprocessor
from core.ocr.service import OCRService
from core.ocr.types import EngineStatus
from tests.helpers import FakeOCRAdapter, default_config, text_frame


def service(adapters, mode="fallback", engine=None, order=None, **ocr_overrides):
    cfg = default_config()
    ocr = cfg["ocr"]
    ocr["mode"] = mode
    ocr["engine"] = engine or list(adapters)[0]
    ocr["fallback_order"] = order if order is not None else list(adapters)[1:]
    ocr.update(ocr_overrides)
    svc = OCRService(ocr, cfg["text"], adapters={a.name: a for a in adapters.values()})
    svc.initialize()
    return svc


class OCRServiceTest(unittest.TestCase):
    def setUp(self):
        self.frame = Preprocessor(default_config()["frame"]["preprocess"]).prepare(text_frame())

    def test_single_engine_uses_only_primary(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.95)
        b = FakeOCRAdapter("paddle", "Room 204", 0.95)
        svc = service({"easyocr": a, "paddle": b}, mode="single_engine")
        d = svc.recognize(self.frame)
        self.assertEqual(d.text, "Room 204")
        self.assertEqual((a.calls, b.calls), (1, 0))
        self.assertEqual(b.status, EngineStatus.UNINITIALIZED)  # not even loaded

    def test_single_engine_skips_unavailable_primary(self):
        a = FakeOCRAdapter("tesseract", load_status=EngineStatus.NOT_AVAILABLE)
        b = FakeOCRAdapter("easyocr", "Room 204", 0.95)
        d = service({"tesseract": a, "easyocr": b}, mode="single_engine").recognize(self.frame)
        self.assertEqual(d.winner.result.engine, "easyocr")

    def test_fallback_stops_when_primary_is_good(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.95)
        b = FakeOCRAdapter("paddle", "Room 204", 0.95)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(d.engines_run, ["easyocr"])
        self.assertEqual(b.calls, 0)

    def test_fallback_runs_secondary_on_poor_primary(self):
        a = FakeOCRAdapter("easyocr", "R§§m ¤¤4", 0.55)
        b = FakeOCRAdapter("paddle", "Room 204", 0.97)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(d.engines_run, ["easyocr", "paddle"])
        self.assertEqual(d.winner.result.engine, "paddle")

    def test_fallback_on_primary_below_min_confidence(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.2)
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(d.winner.result.engine, "paddle")

    def test_low_confidence_everywhere_gives_no_winner(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.2)
        b = FakeOCRAdapter("paddle", "Room 204", 0.3)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertIsNone(d.winner)
        self.assertEqual(d.text, "")
        # Distinguishable from "found nothing": text was read, but not confidently enough.
        self.assertEqual(d.reason, "below_min_confidence")
        self.assertEqual(d.low_confidence, {"easyocr": 0.2, "paddle": 0.3})

    def test_empty_result_is_no_text(self):
        a = FakeOCRAdapter("easyocr", "", 0.0)
        d = service({"easyocr": a}).recognize(self.frame)
        self.assertEqual((d.reason, d.low_confidence), ("no_text", {}))

    def test_rejected_by_score_is_below_threshold(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.9)
        d = service({"easyocr": a}, min_final_score=0.999).recognize(self.frame)
        self.assertEqual(d.reason, "below_threshold")
        self.assertEqual(len(d.candidates), 1)

    def test_ensemble_runs_all_and_fuses(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.9)
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        c = FakeOCRAdapter("trocr", "Roam 2O4 extra long hallucinated words", 0.7)
        d = service({"easyocr": a, "paddle": b, "trocr": c}, mode="ensemble").recognize(self.frame)
        self.assertEqual(sorted(d.engines_run), ["easyocr", "paddle", "trocr"])
        self.assertIn(d.winner.result.engine, ("easyocr", "paddle"))
        self.assertEqual(len(d.candidates), 3)

    def test_engine_exception_is_contained(self):
        a = FakeOCRAdapter("easyocr", raise_exc=RuntimeError("boom"))
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        with self.assertLogs("ocr", level="ERROR"):
            d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(d.errors, {"easyocr": "INFERENCE_FAILED"})
        self.assertEqual(d.winner.result.engine, "paddle")

    def test_engine_timeout_serialized(self):
        """A timed-out engine blocks every other engine until it returns (memory safety)."""
        a = FakeOCRAdapter("easyocr", "Room 204", 0.9, delay_s=1.0, timeout_s=0.1)
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        svc = service({"easyocr": a, "paddle": b})
        d1 = svc.recognize(self.frame)
        self.assertEqual(d1.errors, {"easyocr": "TIMEOUT", "paddle": "BUSY"})
        self.assertEqual(b.calls, 0)
        self.assertIsNone(d1.winner)
        d2 = svc.recognize(self.frame)  # easyocr still running -> skipped, not queued
        self.assertEqual(d2.errors["easyocr"], "BUSY")
        svc._pending["easyocr"].result()  # let the slow call finish
        d3 = svc.recognize(self.frame)
        self.assertEqual(d3.errors, {"easyocr": "TIMEOUT", "paddle": "BUSY"})
        svc._pending["easyocr"].result()
        svc.shutdown()

    def test_engine_timeout_concurrent_when_serialization_off(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.9, delay_s=1.0, timeout_s=0.1)
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        svc = service({"easyocr": a, "paddle": b}, serialize_engines=False)
        d1 = svc.recognize(self.frame)
        self.assertEqual(d1.errors["easyocr"], "TIMEOUT")
        self.assertEqual(d1.winner.result.engine, "paddle")
        svc._pending["easyocr"].result()
        svc.shutdown()

    def test_serialization_spans_service_instances(self):
        """After a config reload the old service's stuck call still blocks the new service."""
        slow = FakeOCRAdapter("easyocr", "Room 204", 0.9, delay_s=1.0, timeout_s=0.1)
        old = service({"easyocr": slow})
        self.assertEqual(old.recognize(self.frame).errors, {"easyocr": "TIMEOUT"})
        old.shutdown()
        new = service({"paddle": FakeOCRAdapter("paddle", "Room 204", 0.9)})
        self.assertEqual(new.recognize(self.frame).errors, {"paddle": "BUSY"})
        old._pending["easyocr"].result()
        self.assertEqual(new.recognize(self.frame).text, "Room 204")
        new.shutdown()

    def test_all_engines_unavailable(self):
        a = FakeOCRAdapter("easyocr", load_status=EngineStatus.MODEL_NOT_AVAILABLE)
        b = FakeOCRAdapter("paddle", load_status=EngineStatus.INIT_FAILED)
        with self.assertLogs("ocr.service", level="ERROR"):
            svc = service({"easyocr": a, "paddle": b})
        d = svc.recognize(self.frame)
        self.assertIsNone(d.winner)
        self.assertEqual(d.reason, "no_engine_available")

    def test_all_engines_fail(self):
        a = FakeOCRAdapter("easyocr", raise_exc=RuntimeError("x"))
        with self.assertLogs("ocr", level="ERROR"):
            d = service({"easyocr": a}).recognize(self.frame)
        self.assertEqual(d.reason, "all_engines_failed")

    def test_disabled_engine_not_used(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.9)
        a.cfg["enabled"] = False
        b = FakeOCRAdapter("paddle", "Room 204", 0.9)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(a.status, EngineStatus.DISABLED)
        self.assertEqual(d.winner.result.engine, "paddle")

    def test_fallback_engines_load_lazily(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.95)
        b = FakeOCRAdapter("paddle", "Room 204", 0.95)
        svc = service({"easyocr": a, "paddle": b})
        self.assertEqual(b.status, EngineStatus.UNINITIALIZED)   # not loaded at startup
        svc.recognize(self.frame)
        self.assertEqual(b.status, EngineStatus.UNINITIALIZED)   # primary was good enough
        a.text, a.confidence = "R§§m ¤¤4", 0.55
        d = svc.recognize(self.frame)
        self.assertEqual(b.status, EngineStatus.READY)           # loaded on first need
        self.assertEqual(d.winner.result.engine, "paddle")

    def test_preload_all(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.95)
        b = FakeOCRAdapter("paddle", "Room 204", 0.95)
        service({"easyocr": a, "paddle": b}, preload="all")
        self.assertEqual(b.status, EngineStatus.READY)

    def test_lazy_engines_all_fail_to_load(self):
        a = FakeOCRAdapter("easyocr", "Room 204", 0.2)  # loads, but below min_confidence
        b = FakeOCRAdapter("paddle", load_status=EngineStatus.MODEL_NOT_AVAILABLE)
        d = service({"easyocr": a, "paddle": b}).recognize(self.frame)
        self.assertEqual(b.status, EngineStatus.MODEL_NOT_AVAILABLE)
        self.assertEqual(d.engines_run, ["easyocr"])
        self.assertEqual(d.reason, "below_min_confidence")  # easyocr read text, just not confidently

    def test_unsupported_language(self):
        a = FakeOCRAdapter("trocr", "Room 204", 0.9, language="hi")
        self.assertEqual(a.initialize(), EngineStatus.LANGUAGE_NOT_SUPPORTED)


LINE = (0.25, 0.40, 0.50, 0.20)   # a text line, as fractions of the image
CLOCK = (0.60, 0.02, 0.04, 0.08)
SWITCH = (0.46, 0.30, 0.05, 0.07)


def hallucinating_trocr(text="0 2 . 0 0", conf=0.68):
    """TrOCR as observed on a camera frame of a room with no text: it reads *something* anywhere."""
    return FakeOCRAdapter("trocr", text, conf, needs_text_regions=True)


class TrOCRRegionGatingTest(unittest.TestCase):
    """TrOCR is recognition-only: it runs only on plausible text regions found by another engine."""

    def setUp(self):
        self.frame = Preprocessor(default_config()["frame"]["preprocess"]).prepare(text_frame())

    def test_room_without_text_trocr_not_run(self):
        """The runtime case: EasyOCR finds nothing, PaddleOCR boxes a clock and a light switch with
        junk readings, and TrOCR would have invented '0 2 . 0 0' and had it spoken."""
        easy = FakeOCRAdapter("easyocr", "", 0.0)
        paddle = FakeOCRAdapter("paddle", "� E", 0.41, text_regions=[(CLOCK, "�"), (SWITCH, "E")])
        trocr = hallucinating_trocr()
        d = service({"easyocr": easy, "paddle": paddle, "trocr": trocr}).recognize(self.frame)
        self.assertEqual(trocr.calls, 0)
        self.assertEqual(d.skipped, {"trocr": "no_text_region"})
        self.assertNotIn("trocr", d.engines_run)
        self.assertIsNone(d.winner)
        self.assertEqual(d.text, "")

    def test_no_text_scene_in_every_mode(self):
        for mode, engine in (("fallback", "easyocr"), ("ensemble", "easyocr"), ("single_engine", "trocr"),
                             ("fallback", "trocr")):
            with self.subTest(mode=mode, primary=engine):
                easy = FakeOCRAdapter("easyocr", "", 0.0)
                trocr = hallucinating_trocr()
                adapters = {"easyocr": easy, "trocr": trocr}
                d = service(adapters, mode=mode, engine=engine,
                            order=[n for n in adapters if n != engine]).recognize(self.frame)
                self.assertEqual(trocr.calls, 0)
                self.assertEqual(d.skipped, {"trocr": "no_text_region"})
                self.assertEqual((d.text, d.reason), ("", "no_text"))

    def test_trocr_reads_only_the_detected_text_regions(self):
        easy = FakeOCRAdapter("easyocr", "Weet me at Moon", 0.45, text_regions=[(LINE, "Weet me at Moon")])
        trocr = FakeOCRAdapter("trocr", "Meet me at noon", 0.9, needs_text_regions=True)
        d = service({"easyocr": easy, "trocr": trocr}, text_type="handwritten").recognize(self.frame)
        self.assertEqual(d.winner.result.engine, "trocr")
        self.assertEqual(d.text, "Meet me at noon")
        self.assertEqual(d.region_source, "easyocr")
        h, w = self.frame.gray.shape[:2]
        self.assertEqual(trocr.regions_seen, [[(int(0.25 * w), int(0.40 * h), int(0.50 * w), int(0.20 * h))]])

    def test_junk_region_readings_are_not_text_regions(self):
        easy = FakeOCRAdapter("easyocr", "3 E", 0.45, text_regions=[(CLOCK, "3"), (SWITCH, "E"), (LINE, "~~")])
        trocr = hallucinating_trocr()
        d = service({"easyocr": easy, "trocr": trocr}).recognize(self.frame)
        self.assertEqual(trocr.calls, 0)
        self.assertEqual(d.region_source, "")

    def test_trocr_primary_runs_after_a_region_finder(self):
        # A good EasyOCR reading is accepted before TrOCR is needed (fallback semantics).
        easy = FakeOCRAdapter("easyocr", "Room 204", 0.95, text_regions=[(LINE, "Room 204")])
        trocr = FakeOCRAdapter("trocr", "Room 204", 0.9, needs_text_regions=True)
        d = service({"trocr": trocr, "easyocr": easy}).recognize(self.frame)
        self.assertEqual(d.engines_run, ["easyocr"])
        self.assertEqual(trocr.calls, 0)
        # A poor EasyOCR reading of real text: TrOCR re-reads EasyOCR's regions.
        easy = FakeOCRAdapter("easyocr", "Weet me at Moon", 0.45, text_regions=[(LINE, "Weet me at Moon")])
        trocr = FakeOCRAdapter("trocr", "Meet me at noon", 0.9, needs_text_regions=True)
        d = service({"trocr": trocr, "easyocr": easy}, text_type="handwritten").recognize(self.frame)
        self.assertEqual(d.engines_run, ["easyocr", "trocr"])
        self.assertEqual(d.text, "Meet me at noon")

    def test_single_engine_trocr_uses_region_finder_for_regions_only(self):
        easy = FakeOCRAdapter("easyocr", "Weet me at Moon", 0.95, text_regions=[(LINE, "Weet me at Moon")])
        trocr = FakeOCRAdapter("trocr", "Meet me at noon", 0.9, needs_text_regions=True)
        d = service({"trocr": trocr, "easyocr": easy}, mode="single_engine").recognize(self.frame)
        self.assertEqual(d.engines_run, ["trocr"])
        self.assertEqual([c.result.engine for c in d.candidates], ["trocr"])  # EasyOCR's text is not a candidate
        self.assertEqual((d.text, d.region_source), ("Meet me at noon", "easyocr"))

    def test_ensemble_runs_trocr_after_region_finders(self):
        easy = FakeOCRAdapter("easyocr", "Room 204", 0.9, text_regions=[(LINE, "Room 204")])
        paddle = FakeOCRAdapter("paddle", "Room 204", 0.9, text_regions=[(LINE, "Room 204")])
        trocr = FakeOCRAdapter("trocr", "Room 204", 0.9, needs_text_regions=True)
        d = service({"trocr": trocr, "easyocr": easy, "paddle": paddle}, mode="ensemble").recognize(self.frame)
        self.assertEqual(d.engines_run, ["easyocr", "paddle", "trocr"])
        self.assertEqual(len(trocr.regions_seen), 1)

    def test_trocr_without_any_region_finder_is_not_run(self):
        trocr = hallucinating_trocr()
        easy = FakeOCRAdapter("easyocr", load_status=EngineStatus.MODEL_NOT_AVAILABLE)
        d = service({"trocr": trocr, "easyocr": easy}).recognize(self.frame)
        self.assertEqual(trocr.calls, 0)
        self.assertEqual(d.skipped, {"trocr": "no_region_source"})
        self.assertEqual(d.reason, "no_engine_available")


if __name__ == "__main__":
    unittest.main()
