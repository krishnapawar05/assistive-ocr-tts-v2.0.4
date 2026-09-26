"""End-to-end acceptance tests (TEST 1-14).

Real OCR engines are used wherever the test is about OCR behavior; real TTS engines run at
volume 0. Recording stand-ins are used only where a test needs to count or force outcomes.
"""
import os
import tempfile
import threading
import time
import unittest

import cv2

from core.camera.mock import FrameSequenceCamera
from core.ocr.service import OCRService
from core.pipeline import AssistivePipeline
from core.status import EngineStatus
from core.tts.base import TTSErrorCode
from core.tts.service import TTSService
from tests.helpers import FakeOCRAdapter, RecordingTTS, default_config, make_config, no_network
from tests.ocr import engine_case  # noqa: F401  (sets offline env)
from core.ocr.service import build_adapters
from tests.ocr.engine_case import FIXTURES, MANIFEST, load_adapter


def img(fid):
    return cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"]))


def base_cfg():
    cfg = default_config()
    cfg["tts"]["volume"] = 0.0                      # silent real TTS
    cfg["frame"]["change_detection"]["enabled"] = False
    cfg["camera"].update(reconnect_initial_delay_s=0.05, reconnect_max_delay_s=0.2,
                         max_consecutive_read_failures=5, read_failure_sleep_s=0.001)
    cfg["ocr"]["capture_interval"] = 0.05
    cfg["pipeline"]["join_timeout_s"] = 5.0
    return cfg


def lazy_adapters(ocr_cfg, **overrides):
    """Real adapters: the cached, already-loaded EasyOCR plus fresh unloaded ones for the other
    engines, which OCRService loads only if a frame reaches them (as the app does with
    ocr.preload="primary"). Loading every engine up front exhausts RAM on 8 GB machines."""
    fresh = build_adapters(ocr_cfg, "en")
    fresh["easyocr"] = load_adapter("easyocr")
    fresh.update(overrides)
    return fresh


def real_ocr(cfg):
    return OCRService(cfg["ocr"], cfg["text"], adapters=lazy_adapters(cfg["ocr"]))


def recording_tts(cfg, *adapters):
    adapters = adapters or (RecordingTTS("coqui"),)
    cfg["tts"]["engine"] = adapters[0].name
    cfg["tts"]["fallback_engines"] = [a.name for a in adapters[1:]]
    return TTSService(cfg["tts"], adapters={a.name: a for a in adapters})


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not load_adapter("easyocr").is_available:
            raise unittest.SkipTest("NOT_AVAILABLE: needs EasyOCR for end-to-end OCR")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pipelines = []

    def tearDown(self):
        for p in self.pipelines:
            p.shutdown()
        # unittest keeps every TestCase alive until the run ends; drop the pipelines (and their
        # models) now so they don't accumulate across tests.
        self.pipelines.clear()
        self.tmp.cleanup()

    def pipeline(self, cfg, frames=None, ocr=None, tts=None, **cam_kw):
        config = make_config(self.tmp.name, cfg)
        camera = FrameSequenceCamera(frames or [img("room_204")], **cam_kw)
        p = AssistivePipeline(config, camera_factory=lambda _c: camera,
                              ocr_service=ocr or real_ocr(config.data), tts_service=tts)
        p.test_camera = camera
        self.pipelines.append(p)
        return p

    def wait_for(self, predicate, timeout=60.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    # TEST 1 ------------------------------------------------------------------------------------
    def test_01_camera_frame_to_ocr_to_tts(self):
        """Threads + camera + real OCR + real (silent) TTS."""
        cfg = base_cfg()
        p = self.pipeline(cfg)
        p.start()
        self.assertTrue(self.wait_for(lambda: p.audio.stats["spoken"] >= 1, 120),
                        f"nothing spoken; status={p.get_status()}")
        self.assertEqual(p.get_history()[0]["text"], "Room 204")
        self.assertIn(p.tts.last_engine, ("coqui", "windows", "espeak"))
        self.assertEqual(p.get_status()["camera"]["state"], "streaming")

    # TEST 2 ------------------------------------------------------------------------------------
    def test_02_poor_primary_falls_back_then_speaks(self):
        cfg = base_cfg()
        cfg["ocr"].update(mode="fallback", engine="tesseract", fallback_order=["easyocr"])
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters={
            "tesseract": FakeOCRAdapter("tesseract", "R§§m ¤¤4 ~~", 0.55), "easyocr": load_adapter("easyocr")})
        tts = recording_tts(cfg)
        p = self.pipeline(cfg, ocr=ocr, tts=tts)
        out = p.process_frame(img("room_204"))
        self.assertEqual((out.status, out.engine, out.text), ("spoken", "easyocr", "Room 204"))
        self.assertTrue(p.audio.wait_idle(10))
        self.assertEqual(tts.adapters["coqui"].spoken, ["Room 204"])

    # TEST 3 ------------------------------------------------------------------------------------
    def test_03_duplicates_not_repeated(self):
        cfg = base_cfg()
        tts = recording_tts(cfg)
        p = self.pipeline(cfg, tts=tts)
        statuses = [p.process_frame(img("room_204")).status for _ in range(3)]
        self.assertEqual(statuses, ["spoken", "duplicate", "duplicate"])
        # "Room204" / "Room 204." variants from another engine are the same reading event.
        for variant in ("Room204", "Room 204."):
            self.assertTrue(p.duplicates.check(variant)[0])
        self.assertTrue(p.audio.wait_idle(10))
        self.assertEqual(tts.adapters["coqui"].spoken, ["Room 204"])

    # TEST 4 ------------------------------------------------------------------------------------
    def test_04_low_confidence_not_spoken(self):
        cfg = base_cfg()
        cfg["ocr"].update(mode="single_engine", engine="easyocr", min_confidence=0.999)
        tts = recording_tts(cfg)
        p = self.pipeline(cfg, tts=tts)
        out = p.process_frame(img("sentence"))  # EasyOCR reads it at ~0.8 confidence
        self.assertEqual(out.status, "no_text")
        self.assertTrue(p.audio.wait_idle(5))
        self.assertEqual(tts.adapters["coqui"].spoken, [])

    def test_04b_low_confidence_primary_falls_back(self):
        cfg = base_cfg()
        cfg["ocr"].update(mode="fallback", engine="trocr", fallback_order=["easyocr"])
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters={
            "trocr": FakeOCRAdapter("trocr", "Room 204", 0.2), "easyocr": load_adapter("easyocr")})
        p = self.pipeline(cfg, ocr=ocr, tts=recording_tts(cfg))
        out = p.process_frame(img("room_204"))
        self.assertEqual((out.status, out.engine), ("spoken", "easyocr"))

    # TEST 5-8 ------------------------------------------------------------------------------------
    def _engine_unavailable(self, broken: str, breaker):
        cfg = base_cfg()
        cfg["ocr"].update(mode="fallback", engine=broken,
                          fallback_order=[e for e in ("easyocr", "paddle") if e != broken])
        breaker(cfg["ocr"]["engines"][broken])
        adapters = lazy_adapters(cfg["ocr"], **{broken: build_adapters(cfg["ocr"], "en")[broken]})
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters=adapters)
        tts = recording_tts(cfg)
        p = self.pipeline(cfg, ocr=ocr, tts=tts)
        self.assertIn(p.ocr.adapters[broken].status, (EngineStatus.NOT_AVAILABLE, EngineStatus.MODEL_NOT_AVAILABLE))
        out = p.process_frame(img("room_204"))
        self.assertEqual(out.status, "spoken")
        self.assertNotEqual(out.engine, broken)
        self.assertEqual(out.text, "Room 204")

    def test_05_tesseract_unavailable(self):
        self._engine_unavailable("tesseract", lambda c: c.update(executable="C:\\missing\\tesseract.exe"))

    def test_06_paddle_unavailable(self):
        self._engine_unavailable("paddle", lambda c: c.update(model_root=os.path.join(self.tmp.name, "none")))

    def test_07_easyocr_unavailable(self):
        self._engine_unavailable("easyocr", lambda c: c.update(model_dir=os.path.join(self.tmp.name, "none")))

    def test_08_trocr_unavailable(self):
        self._engine_unavailable("trocr", lambda c: c.update(model="local-only/does-not-exist"))

    # TEST 9 ------------------------------------------------------------------------------------
    def test_09_coqui_unavailable_falls_back(self):
        cfg = base_cfg()
        cfg["tts"]["engines"]["coqui"]["model_dir"] = os.path.join(self.tmp.name, "no-model")
        tts = TTSService(cfg["tts"])  # real engines
        p = self.pipeline(cfg, tts=tts)
        self.assertEqual(tts.adapters["coqui"].status, EngineStatus.MODEL_NOT_AVAILABLE)
        if not tts.available_engines():
            self.skipTest("NOT_AVAILABLE: no fallback TTS engine installed")
        self.assertEqual(p.process_frame(img("room_204")).status, "spoken")
        self.assertTrue(p.audio.wait_idle(60))
        self.assertEqual(p.audio.stats["spoken"], 1)
        self.assertIn(tts.last_engine, ("windows", "espeak"))

    # TEST 10 -----------------------------------------------------------------------------------
    def test_10_all_tts_unavailable_is_controlled(self):
        cfg = base_cfg()
        tts = recording_tts(cfg, RecordingTTS("coqui", status=EngineStatus.MODEL_NOT_AVAILABLE),
                            RecordingTTS("windows", fail=TTSErrorCode.AUDIO_DEVICE_UNAVAILABLE),
                            RecordingTTS("espeak", status=EngineStatus.NOT_AVAILABLE))
        p = self.pipeline(cfg, tts=tts)
        with self.assertLogs("audio", level="ERROR") as logs:
            self.assertEqual(p.process_frame(img("room_204")).status, "spoken")
            self.assertTrue(p.audio.wait_idle(10))
        self.assertIn("ALL_ENGINES_FAILED", "\n".join(logs.output))
        self.assertEqual(p.audio.stats["failed"], 1)
        # The pipeline is still alive and keeps processing frames.
        self.assertEqual(p.process_frame(img("sentence")).status, "spoken")
        self.assertTrue(p.audio._thread.is_alive())

    # TEST 11 -----------------------------------------------------------------------------------
    def test_11_camera_disconnect_recovers(self):
        cfg = base_cfg()
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters={"easyocr": FakeOCRAdapter("easyocr", "Room 204", 0.9)})
        cfg["ocr"].update(engine="easyocr", fallback_order=[])
        p = self.pipeline(cfg, ocr=ocr, tts=recording_tts(cfg), fail_opens=3, disconnect_after=4)
        p.start()
        self.assertTrue(self.wait_for(lambda: p.controller.reconnects >= 2, 20), p.get_status()["camera"])
        cam = p.test_camera
        self.assertGreater(cam.open_calls, 3)  # failed opens were retried
        frames_before = p.controller.frames_delivered
        self.assertTrue(self.wait_for(lambda: p.controller.frames_delivered > frames_before, 10))
        self.assertTrue(p._process_thread.is_alive())

    def test_11b_camera_never_available(self):
        cfg = base_cfg()
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters={"easyocr": FakeOCRAdapter("easyocr", "x", 0.9)})
        p = self.pipeline(cfg, ocr=ocr, tts=recording_tts(cfg), fail_opens=10 ** 6)
        with self.assertLogs("camera", level="WARNING"):
            p.start()
            self.assertTrue(self.wait_for(lambda: p.get_status()["camera"]["state"] == "reconnecting", 5))
        self.assertIn("not connected", p.get_status()["camera"]["last_error"])

    def test_11c_bad_frames_do_not_crash(self):
        import numpy as np
        cfg = base_cfg()
        p = self.pipeline(cfg, tts=recording_tts(cfg))
        cases = {"none": None, "empty": np.zeros((0, 0, 3), np.uint8), "float": np.zeros((10, 10, 3)),
                 "tiny": np.full((5, 5, 3), 128, np.uint8), "dark": img("dark"), "blank": img("blank"),
                 "overexposed": np.full((720, 1280, 3), 255, np.uint8)}
        expected = {"none": "invalid_frame", "empty": "invalid_frame", "float": "invalid_frame",
                    "tiny": "unusable_frame", "dark": "unusable_frame", "blank": "unusable_frame",
                    "overexposed": "unusable_frame"}
        for name, frame in cases.items():
            with self.subTest(case=name):
                self.assertEqual(p.process_frame(frame).status, expected[name])

    # TEST 12 -----------------------------------------------------------------------------------
    def test_12_malicious_text_never_executes(self):
        cfg = base_cfg()
        marker = os.path.join(self.tmp.name, "pwned.txt")
        payload = f'Room "204" $(New-Item -Path \'{marker}\' -ItemType File); `whoami` & echo hacked'
        cfg["ocr"].update(engine="easyocr", fallback_order=[])
        ocr = OCRService(cfg["ocr"], cfg["text"], adapters={"easyocr": FakeOCRAdapter("easyocr", payload, 0.95)})
        for engine in ("windows", "espeak"):
            with self.subTest(tts=engine):
                c = base_cfg()
                c["tts"].update(engine=engine, fallback_engines=[])
                tts = TTSService(c["tts"])
                p = self.pipeline(cfg, ocr=ocr, tts=tts)
                if not tts.available_engines():
                    continue
                out = p.process_frame(img("room_204"))
                self.assertEqual(out.status, "spoken")
                self.assertTrue(p.audio.wait_idle(60))
                self.assertEqual(p.audio.stats["failed"], 0, p.audio.last_error)
                self.assertFalse(os.path.exists(marker))

    # TEST 13 -----------------------------------------------------------------------------------
    def test_13_offline_full_pipeline_from_cached_models(self):
        """Fresh model loads + inference + speech with every outbound connection blocked."""
        cfg = base_cfg()
        cfg["ocr"].update(mode="fallback", engine="easyocr", fallback_order=["paddle"])
        config = make_config(self.tmp.name, cfg)
        camera = FrameSequenceCamera([img("room_204")])
        with no_network() as guard:
            p = AssistivePipeline(config, camera_factory=lambda _c: camera)
            self.pipelines.append(p)
            out = p.process_frame(img("room_204"))
            self.assertTrue(p.audio.wait_idle(60))
        self.assertEqual(guard.attempts, [])
        self.assertEqual((out.status, out.text), ("spoken", "Room 204"))
        self.assertEqual(p.audio.stats["spoken"], 1, p.audio.last_error)
        if p.tts.adapters["coqui"].is_available():
            self.assertEqual(p.tts.last_engine, "coqui")  # local neural TTS worked offline
        else:
            self.assertIn(p.tts.last_engine, ("windows", "espeak"))

    # TEST 14 -----------------------------------------------------------------------------------
    def test_14_shutdown_terminates_threads(self):
        cfg = base_cfg()
        tts = recording_tts(cfg, RecordingTTS("coqui", delay_s=5.0))
        p = self.pipeline(cfg, tts=tts)
        p.start()
        self.assertTrue(self.wait_for(lambda: p.audio.is_speaking, 120))
        t0 = time.monotonic()
        p.shutdown()
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(p.threads_alive(), [])
        time.sleep(0.2)
        leftovers = [t.name for t in threading.enumerate()
                     if t.name in ("capture", "process", "audio") and t.is_alive()]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
