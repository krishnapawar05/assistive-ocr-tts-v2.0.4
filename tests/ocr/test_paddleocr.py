"""Real-engine tests for paddleocr (see engine_case.py for the A-I checks)."""
import unittest

from tests.ocr import engine_case


class PaddleOCREngineTest(engine_case.EngineTestBase):
    engine = "paddle"
    must_read = {"room_204": 0.1, "sentence": 0.1, "chapter_numbers": 0.1, "greenboard": 0.15,
                 "low_contrast": 0.15, "exit_inverted": 0.2}


if __name__ == "__main__":
    unittest.main()
