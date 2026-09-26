"""Real-engine tests for tesseract (see engine_case.py for the A-I checks)."""
import unittest

from tests.ocr import engine_case


class TesseractEngineTest(engine_case.EngineTestBase):
    engine = "tesseract"
    must_read = {"room_204": 0.1, "sentence": 0.1, "chapter_numbers": 0.1}


if __name__ == "__main__":
    unittest.main()
