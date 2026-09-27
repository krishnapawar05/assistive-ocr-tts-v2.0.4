"""Loading PaddleOCR must not silence the app's INFO logs.

The first PaddleOCR engine created in a process sets the ROOT logger to WARNING. PaddleOCR is
loaded lazily on the first fallback, so from then on every INFO log of the app (Test OCR
diagnostics, engine status, pipeline events) disappeared (found in runtime validation).
Runs in its own module so scripts/run_tests.py gives it a fresh process.
"""
import logging
import sys
import unittest

from core.ocr.service import build_adapters
from core.status import UNAVAILABLE_STATUSES
from tests.helpers import default_config
from tests.ocr import engine_case  # noqa: F401  (sets offline env)


class PaddleRootLoggerTest(unittest.TestCase):
    def test_loading_paddle_keeps_root_logger(self):
        if "paddlex" in sys.modules:
            self.skipTest("PaddleX already loaded in this process; run via scripts/run_tests.py")
        root = logging.getLogger()
        marker = logging.NullHandler()
        saved_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(marker)
        try:
            adapter = build_adapters(default_config()["ocr"], "en")["paddle"]
            adapter.initialize()
            if adapter.status in UNAVAILABLE_STATUSES:
                self.skipTest(f"NOT_AVAILABLE: {adapter.status.value}: {adapter.status_detail}")
            self.assertEqual(logging.getLevelName(root.level), "INFO")
            self.assertIn(marker, root.handlers)
            self.assertTrue(logging.getLogger("assistive_app").isEnabledFor(logging.INFO))
        finally:
            root.removeHandler(marker)
            root.setLevel(saved_level)


if __name__ == "__main__":
    unittest.main()
