import unittest

from core.text.processor import TextProcessor, duplicate_key
from tests.helpers import default_config


class TextProcessorTest(unittest.TestCase):
    def setUp(self):
        cfg = default_config()
        self.p = TextProcessor(cfg["text"], min_text_len=3)

    def test_legitimate_text_unchanged(self):
        for t in ("Room 204", "Chapter 7 Page 132", "Exit on the left", "Library closes at 5 PM",
                  "#1 Hospital", "Price: ₹250", "It's 3:30 p.m.", "कमरा 204", "ಕೊಠಡಿ 204"):
            self.assertEqual(self.p.clean(t), t, t)

    def test_whitespace_normalized(self):
        self.assertEqual(self.p.clean("  Room\n\t 204  "), "Room 204")

    def test_control_chars_removed(self):
        self.assertEqual(self.p.clean("Room\x00 2​04"), "Room 204")

    def test_symbol_runs_collapsed(self):
        self.assertEqual(self.p.clean("Wait...... here!!!"), "Wait. here!")

    def test_edge_and_symbol_only_tokens_removed(self):
        self.assertEqual(self.p.clean("| Room 204 ~"), "Room 204")
        self.assertEqual(self.p.clean("Room || 204"), "Room 204")

    def test_unicode_nfc(self):
        self.assertEqual(self.p.clean("Café"), "Café")

    def test_validity(self):
        self.assertEqual(self.p.validity("Room 204"), 1.0)
        self.assertLess(self.p.validity("R§§m ¤¤4"), 0.7)

    def test_is_valid(self):
        self.assertEqual(self.p.is_valid("Room 204"), (True, "ok"))
        self.assertEqual(self.p.is_valid("ab")[1], "too_short")
        self.assertEqual(self.p.is_valid("..."), (False, "no_letters_or_digits"))
        self.assertEqual(self.p.is_valid("a§§§§§§§")[1], "low_validity")

    def test_language_consistency(self):
        self.assertEqual(self.p.language_consistency("Room 204", "en"), 1.0)
        self.assertEqual(self.p.language_consistency("कमरा", "hi"), 1.0)
        self.assertEqual(self.p.language_consistency("कमरा", "en"), 0.0)
        self.assertEqual(self.p.language_consistency("204", "kn"), 1.0)

    def test_repetition(self):
        self.assertEqual(self.p.repetition_fraction("Room 204"), 0.0)
        self.assertAlmostEqual(self.p.repetition_fraction("Room 204 Room 204"), 0.5)

    def test_duplicate_key(self):
        self.assertEqual(duplicate_key("Room 204"), duplicate_key("Room204"))
        self.assertEqual(duplicate_key("Room 204"), duplicate_key("room 204."))
        self.assertNotEqual(duplicate_key("Room 204"), duplicate_key("Room 205"))


if __name__ == "__main__":
    unittest.main()
