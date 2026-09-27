"""Text-line localization used by TrOCR (no model needed)."""
import json
import os
import unittest

import cv2
import numpy as np

from core.frame.processing import Preprocessor
from core.ocr.regions import find_text_lines, lines_from_regions
from tests.helpers import default_config

FIX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "ocr")
EXPECTED_LINES = {"room_204": 1, "sentence": 1, "greenboard": 2, "whiteboard": 2, "hand_meet": 1,
                  "hand_notes": 1, "exit_inverted": 1, "hindi_room": 1, "kannada_room": 1,
                  "blank": 0, "dark": 0}


class RegionsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = default_config()
        self.pre = Preprocessor(self.cfg["frame"]["preprocess"])
        with open(os.path.join(FIX, "manifest.json"), encoding="utf-8") as f:
            self.manifest = {m["id"]: m for m in json.load(f)["fixtures"]}

    def test_one_region_per_line(self):
        for fid, n in EXPECTED_LINES.items():
            with self.subTest(fixture=fid):
                gray = self.pre.prepare(cv2.imread(os.path.join(FIX, self.manifest[fid]["path"]))).gray
                self.assertEqual(len(find_text_lines(gray, self.cfg["ocr"]["regions"])), n)

    def test_lines_in_reading_order(self):
        gray = self.pre.prepare(cv2.imread(os.path.join(FIX, self.manifest["greenboard"]["path"]))).gray
        boxes = find_text_lines(gray, self.cfg["ocr"]["regions"])
        self.assertLess(boxes[0][1], boxes[1][1])

    def test_noise_frame_has_few_regions(self):
        rng = np.random.default_rng(0)
        noise = (128 + rng.normal(0, 2, (720, 1280))).clip(0, 255).astype(np.uint8)
        self.assertEqual(find_text_lines(noise, self.cfg["ocr"]["regions"]), [])

    def test_boxes_inside_image(self):
        gray = self.pre.prepare(cv2.imread(os.path.join(FIX, self.manifest["sentence"]["path"]))).gray
        for x, y, w, h in find_text_lines(gray, self.cfg["ocr"]["regions"]):
            self.assertTrue(0 <= x and 0 <= y and x + w <= gray.shape[1] and y + h <= gray.shape[0])

    def test_lines_from_detector_regions(self):
        """Detector word boxes -> padded line crops in reading order, clipped to the image."""
        cfg = dict(self.cfg["ocr"]["regions"], padding_px=6)
        words = [(280, 100, 80, 40), (100, 100, 150, 40), (100, 200, 120, 40), (0, 0, 0, 10)]
        lines = lines_from_regions(words, (240, 400), cfg)
        self.assertEqual(lines, [(94, 94, 272, 52), (94, 194, 132, 46)])  # 2nd line clipped at the bottom


if __name__ == "__main__":
    unittest.main()
