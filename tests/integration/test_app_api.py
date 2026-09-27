"""HTTP API smoke tests against the real app (real engines, silent TTS, no real camera)."""
import copy
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from core.ocr.service import OCRService
from core.ocr.types import EngineStatus
from tests.helpers import FakeOCRAdapter, default_config
from tests.ocr.engine_case import FIXTURES, MANIFEST

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_JS = os.path.join(ROOT, "static", "dashboard.js")


def fixture(fid):
    return cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"]))


class AppAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = default_config()
        cfg["camera"]["camera_id"] = 99            # no such device: never opens a real webcam
        cfg["camera"]["reconnect_initial_delay_s"] = 0.2
        cfg["tts"]["volume"] = 0.0
        # The reported runtime setup: Tesseract selected as primary but not installed. The missing
        # executable makes it NOT_AVAILABLE on every machine; EasyOCR is the configured fallback.
        cfg["ocr"].update(engine="tesseract", mode="single_engine", fallback_order=["easyocr"])
        cfg["ocr"]["engines"]["tesseract"]["executable"] = os.path.join(cls.tmp.name, "missing", "tesseract.exe")
        cls.config_path = os.path.join(cls.tmp.name, "config.json")
        with open(cls.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.environ["SVA_CONFIG"] = cls.config_path
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.client = TestClient(cls.app_module.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)  # runs lifespan shutdown
        os.environ.pop("SVA_CONFIG", None)
        cls.tmp.cleanup()

    def test_dashboard_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="ocrMode"', r.text)

    def test_status(self):
        r = self.client.get("/api/status").json()
        self.assertEqual(r["status"], "ok")
        for key in ("running", "last_text", "history_count", "camera", "ocr", "tts", "audio"):
            self.assertIn(key, r["pipeline"])

    def test_config_validation_errors_returned(self):
        r = self.client.post("/api/config", json={"tts": {"volume": 7}, "ocr": {"mode": "warp"}})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertTrue(any("tts.volume" in e for e in body["errors"]))
        self.assertTrue(any("ocr.mode" in e for e in body["errors"]))
        with open(self.config_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["tts"]["volume"], 0.0)  # file untouched

    def test_speak(self):
        self.assertEqual(self.client.post("/api/speak", json={"text": ""}).status_code, 400)
        r = self.client.post("/api/speak", json={"text": "Room 204"})
        self.assertEqual(r.json()["status"], "speaking")
        self.assertTrue(self.app_module.pipeline.audio.wait_idle(60))
        self.assertEqual(self.app_module.pipeline.audio.stats["failed"], 0)

    def test_replay(self):
        self.client.post("/api/speak", json={"text": "Replay me"})
        self.assertTrue(self.app_module.pipeline.audio.wait_idle(60))
        r = self.client.get("/api/replay")
        if self.app_module.pipeline.tts.last_engine == "coqui":
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers["content-type"], "audio/wav")
            self.assertEqual(r.content[:4], b"RIFF")
        else:
            self.assertEqual(r.status_code, 404)

    def test_camera_missing_reported(self):
        r = self.client.get("/api/test-camera").json()
        self.assertEqual(r["status"], "error")
        self.assertIn("cannot open", r["message"])

    def test_test_ocr_reports_engines(self):
        r = self.client.get("/api/test-ocr").json()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(set(r["ocr_engines"]), {"tesseract", "easyocr", "paddle", "trocr"})
        self.assertEqual(set(r["tts_engines"]), {"coqui", "windows", "espeak"})
        self.assertIn("error", r["ocr_test_on_frame"])

    def test_start_stop_without_camera(self):
        r = self.client.post("/api/start").json()
        self.assertEqual(r["status"], "started")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.client.get("/api/status").json()["pipeline"]["camera"]["state"] == "reconnecting":
                break
            time.sleep(0.1)
        self.assertEqual(self.client.get("/api/status").json()["pipeline"]["camera"]["state"], "reconnecting")
        self.assertEqual(self.client.post("/api/stop").json()["status"], "stopped")
        self.assertEqual(self.app_module.pipeline.threads_alive(), ["audio"])

    def test_requests_during_reload_get_503(self):
        live = self.app_module.pipeline
        self.app_module.pipeline = None  # what a reload looks like from other requests
        try:
            for method, path in (("get", "/api/status"), ("get", "/api/history"), ("post", "/api/start"),
                                 ("get", "/api/test-ocr")):
                with self.subTest(path=path):
                    self.assertEqual(getattr(self.client, method)(path).status_code, 503)
        finally:
            self.app_module.pipeline = live

    def test_concurrent_reload_rejected(self):
        lock = self.app_module._reload_lock
        lock.acquire()
        try:
            r = self.client.post("/api/config", json={"tts": {"speed": 1.1}})
            self.assertEqual(r.status_code, 409)
        finally:
            lock.release()

    def test_zz_valid_config_reload_rebuilds_pipeline(self):
        import gc
        import weakref
        old = self.app_module.pipeline
        old_ref = weakref.ref(old)
        old_threads = [t for t in (old._process_thread, old.audio._thread) if t is not None]
        del old
        r = self.client.post("/api/config", json={"ocr": {"min_confidence": 0.55}})
        self.assertEqual(r.json()["status"], "saved")
        new = self.app_module.pipeline
        self.assertEqual(new.cfg["ocr"]["min_confidence"], 0.55)
        self.assertTrue(all(not t.is_alive() for t in old_threads))
        gc.collect()
        self.assertIsNone(old_ref(), "old pipeline (and its models) still referenced after reload")
        self.assertEqual(self.client.get("/api/status").status_code, 200)

    # ----- Test OCR (/api/test-ocr) regression tests ----------------------------------------
    def ocr_on(self, image):
        """GET /api/test-ocr with the camera replaced by one in-memory image."""
        real = self.app_module._grab_frame
        self.app_module._grab_frame = lambda: image
        try:
            r = self.client.get("/api/test-ocr")
        finally:
            self.app_module._grab_frame = real
        self.assertEqual(r.status_code, 200)
        return r.json()

    def swap_ocr(self, *adapters, **ocr_overrides):
        """Replace the live pipeline's OCR service with the given adapters for one test."""
        p = self.app_module.pipeline
        ocr_cfg = copy.deepcopy(p.ocr.cfg)
        ocr_cfg.update(engine=adapters[0].name, fallback_order=[a.name for a in adapters[1:]], **ocr_overrides)
        svc = OCRService(ocr_cfg, p.cfg["text"], adapters={a.name: a for a in adapters})
        svc.initialize()
        old, p.ocr = p.ocr, svc
        self.addCleanup(svc.shutdown)
        self.addCleanup(setattr, p, "ocr", old)

    def render(self, data):
        """Render a /api/test-ocr response with the real dashboard.js formatter (Node)."""
        node = shutil.which("node")
        if not node:
            self.skipTest("NOT_AVAILABLE: node not installed (only needed to test dashboard.js)")
        js = ("const D=require(process.argv[1]);let s='';process.stdin.setEncoding('utf8');"
              "process.stdin.on('data',c=>s+=c).on('end',()=>process.stdout.write(D.formatOcrTest(JSON.parse(s))));")
        out = subprocess.run([node, "-e", js, DASHBOARD_JS], input=json.dumps(data), capture_output=True,
                             encoding="utf-8", timeout=60, check=True)
        return out.stdout

    def test_test_ocr_known_fixture_returns_text(self):
        r = self.ocr_on(fixture("room_204"))["ocr_test_on_frame"]
        self.assertEqual((r["text"], r["reason"]), ("Room 204", "selected"))
        self.assertGreaterEqual(r["confidence"], 0.5)
        self.assertEqual(r["frame"]["shape"][2], 3)
        self.assertGreater(r["frame"]["max"], r["frame"]["min"])
        self.assertIn("latency_s", r)

    def test_test_ocr_unavailable_primary_uses_available_engine(self):
        data = self.ocr_on(fixture("sentence"))
        self.assertEqual(data["config"]["engine"], "tesseract")
        self.assertEqual(data["ocr_engines"]["tesseract"]["status"], "NOT_AVAILABLE")
        r = data["ocr_test_on_frame"]
        self.assertEqual(r["reason"], "selected")
        self.assertEqual(r["text"], MANIFEST["sentence"]["text"])
        self.assertEqual(r["engine"], "easyocr")          # the engine that actually produced the text
        self.assertEqual(r["engines_run"], ["easyocr"])   # tesseract skipped, never "run"

    def test_test_ocr_distinguishes_outcomes(self):
        with self.subTest("invalid frame"):
            r = self.ocr_on(np.zeros((10, 10, 3), np.float64))["ocr_test_on_frame"]
            self.assertIn("error", r)
            self.assertNotIn("reason", r)
        with self.subTest("OCR found no text"):
            r = self.ocr_on(fixture("blank"))["ocr_test_on_frame"]
            self.assertEqual((r["text"], r["reason"], r["low_confidence"]), ("", "no_text", {}))
            self.assertEqual(r["engines_run"], ["easyocr"])
        with self.subTest("text found but confidence too low"):
            self.swap_ocr(FakeOCRAdapter("easyocr", "Room 204", 0.2))
            r = self.ocr_on(fixture("room_204"))["ocr_test_on_frame"]
            self.assertEqual((r["text"], r["reason"]), ("", "below_min_confidence"))
            self.assertEqual(r["low_confidence"], {"easyocr": 0.2})
        with self.subTest("no engine available"):
            self.swap_ocr(FakeOCRAdapter("tesseract", load_status=EngineStatus.NOT_AVAILABLE),
                          FakeOCRAdapter("easyocr", load_status=EngineStatus.MODEL_NOT_AVAILABLE))
            r = self.ocr_on(fixture("room_204"))["ocr_test_on_frame"]
            self.assertEqual((r["text"], r["reason"], r["engines_run"]), ("", "no_engine_available", []))

    def test_dashboard_renders_actual_test_ocr_result(self):
        html = self.render(self.ocr_on(fixture("room_204")))
        self.assertIn('Detected "Room 204"', html)
        self.assertIn("Engine used: easyocr", html)
        self.assertIn("Primary engine tesseract was skipped (NOT_AVAILABLE)", html)
        self.assertNotIn("No text", html)

        self.assertIn("No usable camera frame", self.render(self.ocr_on(np.zeros((10, 10, 3), np.float64))))
        self.assertIn("OCR ran but found no text", self.render(self.ocr_on(fixture("blank"))))

        self.swap_ocr(FakeOCRAdapter("easyocr", "Room 204", 0.2))
        html = self.render(self.ocr_on(fixture("room_204")))
        self.assertIn("confidence was below Min Confidence", html)
        self.assertIn("easyocr confidence 20.0% &lt; Min Confidence 50.0%", html)

        self.swap_ocr(FakeOCRAdapter("easyocr", "<img src=x onerror=alert(1)> Room", 0.95))
        html = self.render(self.ocr_on(fixture("room_204")))
        self.assertNotIn("<img", html)  # OCR text is escaped

    def test_test_ocr_no_text_scene_trocr_skipped(self):
        """A room with no text: real EasyOCR finds nothing, so TrOCR (which would invent
        '0 2 . 0 0') is never run, and Test OCR says so instead of showing invented text."""
        easyocr = self.app_module.pipeline.ocr.adapters["easyocr"]
        trocr = FakeOCRAdapter("trocr", "0 2 . 0 0", 0.68, needs_text_regions=True)
        self.swap_ocr(easyocr, trocr, mode="fallback")
        data = self.ocr_on(fixture("scene_room"))
        r = data["ocr_test_on_frame"]
        self.assertEqual((r["text"], r["reason"], r["engines_run"]), ("", "no_text", ["easyocr"]))
        self.assertEqual(r["skipped"], {"trocr": "no_text_region"})
        self.assertEqual(trocr.calls, 0)
        html = self.render(data)
        self.assertIn("trocr skipped: no text region was found", html)
        self.assertNotIn("0 2 . 0 0", html)

    def test_dashboard_form_shows_saved_ocr_config(self):
        html = self.client.get("/").text
        self.assertIn('<option value="tesseract" selected>Tesseract (NOT_AVAILABLE)</option>', html)
        self.assertIn('<option value="single_engine" selected>', html)
        self.assertIn('<option value="en" selected>', html)

    def test_static_assets_are_versioned(self):
        html = self.client.get("/").text
        for name, version in self.app_module.ASSET_VERSIONS.items():
            url = f"/static/{name}?v={version}"
            self.assertIn(url, html)
            self.assertEqual(self.client.get(url).status_code, 200)
        with open(DASHBOARD_JS, "rb") as f:
            self.assertEqual(self.app_module.ASSET_VERSIONS["dashboard.js"], hashlib.sha256(f.read()).hexdigest()[:12])

    def test_history(self):
        self.assertIn("history", self.client.get("/api/history").json())

    def test_accessibility_landmarks_and_controls(self):
        """Verify semantic landmarks, screen-reader live regions, and primary buttons."""
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        html = r.text
        # Semantic landmarks
        self.assertIn('class="skip-link"', html)
        self.assertIn('role="banner"', html)
        self.assertIn('role="main"', html)
        # Dedicated polite screen reader announcement channel
        self.assertIn('id="srLiveAnnouncements"', html)
        self.assertIn('aria-live="polite"', html)
        # Primary student controls and accessible labels
        self.assertIn('id="startBtn"', html)
        self.assertIn('id="stopBtn"', html)
        self.assertIn('id="replayBtn"', html)
        self.assertIn('id="stopSpeechBtn"', html)
        self.assertIn('aria-label=', html)
        self.assertIn('<kbd class="shortcut-tag">Space</kbd>', html)
        self.assertIn('<kbd class="shortcut-tag">R</kbd>', html)
        self.assertIn('<kbd class="shortcut-tag">Esc</kbd>', html)
        # High contrast and large font controls
        self.assertIn('id="contrastToggle"', html)
        self.assertIn('id="increaseFont"', html)
        # Diagnostics drawer preserves all settings forms
        self.assertIn('id="diagnosticsSection"', html)
        self.assertIn('id="ocrForm"', html)
        self.assertIn('id="ttsForm"', html)
        self.assertIn('id="cameraForm"', html)

    def test_stop_speech_api(self):
        """Verify POST /api/stop-speech silences audio queue and returns 200."""
        self.client.post("/api/speak", json={"text": "Speaking something long"})
        r = self.client.post("/api/stop-speech")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "stopped")
        self.assertEqual(self.app_module.pipeline.audio.pending(), 0)

    def test_replay_latest_api(self):
        """Verify POST /api/replay-latest replays last recognized text."""
        # When no text recognized yet
        self.app_module.pipeline.last_text = ""
        r_empty = self.client.post("/api/replay-latest")
        self.assertEqual(r_empty.status_code, 404)
        self.assertEqual(r_empty.json()["status"], "no_text")

        # When valid text exists
        self.app_module.pipeline.last_text = "Welcome to Science Class"
        r_valid = self.client.post("/api/replay-latest")
        self.assertEqual(r_valid.status_code, 200)
        self.assertEqual(r_valid.json()["status"], "replaying")
        self.assertEqual(r_valid.json()["text"], "Welcome to Science Class")
        self.assertTrue(self.app_module.pipeline.audio.wait_idle(60))

    def test_dashboard_js_guards_input_shortcuts(self):
        """Ensure dashboard.js contains safety guard against hijacking typing in form inputs."""
        with open(DASHBOARD_JS, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("matches('input, select, textarea')", content)
        self.assertIn("e.code === 'Space'", content)
        self.assertIn("e.key === 'Escape'", content)


if __name__ == "__main__":
    unittest.main()
