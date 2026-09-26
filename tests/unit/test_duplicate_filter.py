import unittest

from core.text.duplicates import DuplicateFilter


def make(cooldown=10.0, refresh=True, threshold=90.0):
    return DuplicateFilter({"cooldown_s": cooldown, "fuzzy_threshold": threshold,
                            "refresh_on_repeat": refresh, "max_entries": 50})


class DuplicateFilterTest(unittest.TestCase):
    def test_first_sighting_is_new(self):
        self.assertEqual(make().check("Room 204", now=0), (False, "new"))

    def test_exact_and_normalized_duplicates(self):
        f = make()
        f.check("Room 204", now=0)
        self.assertEqual(f.check("Room 204", now=1), (True, "exact"))
        self.assertEqual(f.check("Room204", now=2), (True, "exact"))
        self.assertEqual(f.check("Room 204.", now=3), (True, "exact"))
        self.assertEqual(f.check("ROOM 204", now=4), (True, "exact"))

    def test_fuzzy_duplicate(self):
        f = make()
        f.check("The quick brown fox jumps over the lazy dog", now=0)
        self.assertEqual(f.check("The quick brown fox jumps over the lazy dcg", now=1), (True, "fuzzy"))

    def test_different_text_not_duplicate(self):
        f = make()
        f.check("Room 204", now=0)
        self.assertFalse(f.check("Exit on the left", now=1)[0])
        self.assertFalse(f.check("Room 205", now=2)[0])  # short numeric difference must not be merged
        self.assertFalse(f.check("Room 1204", now=3)[0])
        self.assertFalse(f.check("Platform 12", now=4)[0])
        self.assertFalse(f.check("Platform 13", now=5)[0])

    def test_cooldown_expiry(self):
        f = make(cooldown=10, refresh=False)
        f.check("Room 204", now=0)
        self.assertTrue(f.check("Room 204", now=5)[0])
        self.assertFalse(f.check("Room 204", now=10.5)[0])

    def test_refresh_on_repeat_keeps_suppressing_while_in_view(self):
        f = make(cooldown=10, refresh=True)
        for t in range(0, 60, 5):  # seen every 5 s for a minute
            is_dup, _ = f.check("Room 204", now=t)
            self.assertEqual(is_dup, t != 0)
        self.assertFalse(f.check("Room 204", now=55 + 10.5)[0])  # absent > cooldown -> new again


if __name__ == "__main__":
    unittest.main()
