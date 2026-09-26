import json
import os
import tempfile
import unittest

from core.config import DEFAULT_CONFIG, Config, ConfigError, migrate, validate


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_defaults_are_valid(self):
        self.assertEqual(validate(DEFAULT_CONFIG), [])

    def test_missing_file_creates_defaults(self):
        cfg = Config(self.path)
        self.assertEqual(cfg.data, DEFAULT_CONFIG)
        self.assertTrue(os.path.exists(self.path))

    def test_v204_config_migrates(self):
        """The exact config.json shipped with v2.0.4 must load."""
        self.write({
            "camera": {"source_type": "opencv", "camera_id": 0, "resolution": "1080p"},
            "ocr": {"engine": "tesseract", "language": "eng", "capture_interval": 0.2, "min_confidence": 0.5,
                    "min_text_len": 3, "use_yolo": False, "onnx_sr_model": None, "parallel_ocr": True,
                    "use_trocr": True, "handwriting_fallback": False, "easyocr_languages": ["en"]},
            "tts": {"engine": "coqui", "coqui_model": "tts_models/en/vctk/vits", "voice": "p335",
                    "speed": 1, "volume": 0.9},
            "app": {"high_contrast": False, "font_size": "16px", "max_history": 50},
        })
        cfg = Config(self.path)
        ocr = cfg.data["ocr"]
        self.assertEqual(ocr["language"], "en")
        self.assertEqual(ocr["engine"], "tesseract")
        self.assertTrue(ocr["engines"]["trocr"]["enabled"])
        self.assertFalse(ocr["engines"]["easyocr"]["enabled"])
        for dead in ("use_trocr", "handwriting_fallback", "parallel_ocr", "use_yolo", "onnx_sr_model",
                     "easyocr_languages"):
            self.assertNotIn(dead, ocr)
        self.assertEqual(cfg.data["camera"]["resolution"], "1080p")

    def test_invalid_json_raises_and_keeps_file(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        with self.assertRaises(ConfigError):
            Config(self.path)
        with open(self.path) as f:
            self.assertEqual(f.read(), "{not json")  # v2.0.4 silently overwrote it with defaults

    def test_invalid_values_reported_with_paths(self):
        self.write({"ocr": {"mode": "turbo", "min_confidence": 2}, "tts": {"volume": -1, "engine": "siri"},
                    "audio": {"policy": "random"}})
        with self.assertRaises(ConfigError) as ctx:
            Config(self.path)
        msg = str(ctx.exception)
        for path in ("ocr.mode", "ocr.min_confidence", "tts.volume", "tts.engine", "audio.policy"):
            self.assertIn(path, msg)

    def test_wrong_types_reported(self):
        self.write({"ocr": {"min_text_len": "three", "fallback_order": ["paddle", "magic"]},
                    "app": {"offline_mode": "yes"}})
        with self.assertRaises(ConfigError) as ctx:
            Config(self.path)
        msg = str(ctx.exception)
        self.assertIn("ocr.min_text_len", msg)
        self.assertIn("ocr.fallback_order", msg)
        self.assertIn("app.offline_mode", msg)

    def test_update_rejects_invalid_patch_without_changing(self):
        cfg = Config(self.path)
        before = json.dumps(cfg.data, sort_keys=True)
        with self.assertRaises(ConfigError):
            cfg.update({"tts": {"speed": 100}})
        self.assertEqual(json.dumps(cfg.data, sort_keys=True), before)

    def test_update_applies_and_migrates_dashboard_patch(self):
        cfg = Config(self.path)
        cfg.update({"ocr": {"language": "hin", "use_trocr": False, "min_confidence": 0.6}})
        self.assertEqual(cfg.data["ocr"]["language"], "hi")
        self.assertFalse(cfg.data["ocr"]["engines"]["trocr"]["enabled"])
        self.assertEqual(Config(self.path).data["ocr"]["min_confidence"], 0.6)

    def test_migrate_reports_notes(self):
        notes = migrate({"ocr": {"use_trocr": True, "language": "kan"}})
        self.assertTrue(any("use_trocr" in n for n in notes))
        self.assertTrue(any("kan" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
