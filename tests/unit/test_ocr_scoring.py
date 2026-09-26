import unittest

from core.ocr.scoring import OCRScorer
from core.ocr.types import OCRResult
from core.text.processor import TextProcessor
from tests.helpers import default_config


def res(engine, text, conf, t=1.0, boxes=None):
    return OCRResult(text=text, confidence=conf, engine=engine, processing_time=t,
                     bounding_boxes=boxes or [(10, 10, 100, 30)])


class OCRScoringTest(unittest.TestCase):
    def setUp(self):
        self.cfg = default_config()
        self.proc = TextProcessor(self.cfg["text"], 3)

    def scorer(self, text_type="printed", cfg=None):
        cfg = cfg or self.cfg
        return OCRScorer(cfg["ocr"]["scoring"], text_type, self.proc, "en")

    def test_longer_garbage_does_not_win(self):
        """Baseline regression: TrOCR's longer, worse text used to win on length."""
        scored = self.scorer().score([
            res("easyocr", "The quick brown fox jumps over the lazy dog", 0.81),
            res("trocr", "# the quick brown toxtumps over the lazy dod and more words", 0.45),
        ])
        self.assertEqual(scored[0].result.engine, "easyocr")

    def test_blank_frame_hallucination_scores_low(self):
        scored = self.scorer().score([res("trocr", "0 0", 0.33)])
        self.assertLess(scored[0].final_score, self.cfg["ocr"]["min_final_score"])

    def test_agreement_raises_score(self):
        s = self.scorer()
        alone = s.score([res("easyocr", "Room 204", 0.8), res("paddle", "Kitchen", 0.8)])
        agree = s.score([res("easyocr", "Room 204", 0.8), res("paddle", "Room 204", 0.8)])
        a = next(c for c in alone if c.result.engine == "easyocr")
        b = next(c for c in agree if c.result.engine == "easyocr")
        self.assertGreater(b.final_score, a.final_score)
        self.assertEqual(b.components["agreement"], 1.0)

    def test_single_candidate_has_no_agreement_component(self):
        c = self.scorer().score([res("easyocr", "Room 204", 0.9)])[0]
        self.assertNotIn("agreement", c.components)

    def test_text_type_changes_engine_preference(self):
        results = [res("easyocr", "Meet me at noon", 0.7), res("trocr", "Meet me at moon", 0.7)]
        self.assertEqual(self.scorer("printed").score(results)[0].result.engine, "easyocr")
        self.assertEqual(self.scorer("handwritten").score(results)[0].result.engine, "trocr")

    def test_garbage_and_repetition_penalized(self):
        s = self.scorer()
        clean = s.score([res("easyocr", "Room 204", 0.9)])[0]
        garbage = s.score([res("easyocr", "R§§m 2¤4", 0.9)])[0]
        rep = s.score([res("easyocr", "Room 204 Room 204 Room 204", 0.9)])[0]
        self.assertGreater(clean.final_score, garbage.final_score)
        self.assertGreater(clean.final_score, rep.final_score)

    def test_wrong_script_penalized(self):
        s = self.scorer()
        en = s.score([res("easyocr", "Room 204", 0.9)])[0]
        hi = s.score([res("easyocr", "कमरा 204", 0.9)])[0]
        self.assertGreater(en.final_score, hi.final_score)

    def test_weights_are_configurable(self):
        cfg = default_config()
        cfg["ocr"]["scoring"]["weights"] = {k: 0.0 for k in cfg["ocr"]["scoring"]["weights"]}
        cfg["ocr"]["scoring"]["weights"]["reliability"] = 1.0
        s = self.scorer(cfg=cfg)
        # Only engine reliability counts: paddle (0.9) beats easyocr (0.85) regardless of confidence.
        top = s.score([res("easyocr", "Room 204", 0.99), res("paddle", "Room 204", 0.1)])[0]
        self.assertEqual(top.result.engine, "paddle")

    def test_empty_results_ignored(self):
        self.assertEqual(self.scorer().score([res("easyocr", "   ", 0.9), res("paddle", "|~", 0.9)]), [])

    def test_explain_mentions_engine_and_score(self):
        c = self.scorer().score([res("easyocr", "Room 204", 0.9)])[0]
        text = OCRScorer.explain(c)
        self.assertIn("easyocr", text)
        self.assertIn("final_score=", text)


if __name__ == "__main__":
    unittest.main()
