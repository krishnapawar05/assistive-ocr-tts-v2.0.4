"""HTTP API smoke tests against the real app (real engines, silent TTS, no real camera)."""
import importlib
import json
import os
import sys
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from tests.helpers import default_config


class AppAPITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = default_config()
        cfg["camera"]["camera_id"] = 99            # no such device: never opens a real webcam
        cfg["camera"]["reconnect_initial_delay_s"] = 0.2
        cfg["tts"]["volume"] = 0.0
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

    def test_history(self):
        self.assertIn("history", self.client.get("/api/history").json())


if __name__ == "__main__":
    unittest.main()
