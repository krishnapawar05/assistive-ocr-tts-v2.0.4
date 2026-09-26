"""Real-engine tests for trocr (see engine_case.py for the A-I checks)."""
import unittest

from tests.ocr import engine_case


class TrOCREngineTest(engine_case.EngineTestBase):
    engine = "trocr"
    must_read = {"hand_meet": 0.25, "hand_notes": 0.3, "room_204": 0.2}


if __name__ == "__main__":
    unittest.main()
