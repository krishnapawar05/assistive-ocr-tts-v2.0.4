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
        self.assertEqual(d.reason, "no_text")

    def test_unsupported_language(self):
        a = FakeOCRAdapter("trocr", "Room 204", 0.9, language="hi")
        self.assertEqual(a.initialize(), EngineStatus.LANGUAGE_NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
