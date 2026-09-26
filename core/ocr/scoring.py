"""Configurable scoring/fusion of OCR candidates from one or more engines.

Replaces v2.0.4's "longest text wins". Text length is only a plausibility check and never
rewards longer output.
"""
import logging
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from ..text.processor import TextProcessor, duplicate_key
from .types import BBox, OCRResult, ScoredCandidate

logger = logging.getLogger("ocr.scoring")


def _union_box(boxes: List[BBox]) -> Optional[BBox]:
    if not boxes:
        return None
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[0] + b[2] for b in boxes)
    y2 = max(b[1] + b[3] for b in boxes)
    return x1, y1, x2 - x1, y2 - y1


def _iou(a: BBox, b: BBox) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


class OCRScorer:
    def __init__(self, scoring_cfg: Dict[str, Any], text_type: str, processor: TextProcessor, language: str):
        self.weights = {k: float(v) for k, v in scoring_cfg["weights"].items()}
        self.penalties = {k: float(v) for k, v in scoring_cfg["penalties"].items()}
        self.reliability = scoring_cfg["engine_reliability"][text_type]
        self.max_expected_len = int(scoring_cfg["max_expected_len"])
        self.latency_budget_s = float(scoring_cfg["latency_budget_s"])
        self.processor = processor
        self.language = language

    def score(self, results: List[OCRResult]) -> List[ScoredCandidate]:
        """Score every non-empty result; returns candidates sorted best-first."""
        prepared = []
        for r in results:
            cleaned = self.processor.clean(r.text)
            if cleaned:
                prepared.append((r, cleaned))
        keys = [duplicate_key(c) for _, c in prepared]
        unions = [_union_box(r.bounding_boxes) for r, _ in prepared]

        scored = []
        for i, (r, cleaned) in enumerate(prepared):
            comp: Dict[str, float] = {
                "confidence": r.confidence,
                "reliability": float(self.reliability.get(r.engine, 0.5)),
                "validity": self.processor.validity(cleaned),
                "language": self.processor.language_consistency(cleaned, self.language),
                "length": self._length_score(cleaned),
                "speed": max(0.0, 1.0 - r.processing_time / self.latency_budget_s),
            }
            others = [j for j in range(len(prepared)) if j != i]
            if others:  # agreement is only meaningful with more than one engine
                comp["agreement"] = max(fuzz.ratio(keys[i], keys[j]) for j in others) / 100.0
                box_scores = [_iou(unions[i], unions[j]) for j in others if unions[i] and unions[j]]
                if box_scores:
                    comp["bbox_agreement"] = max(box_scores)
            pen = {
                "garbage": self.processor.garbage_fraction(cleaned),
                "repetition": self.processor.repetition_fraction(cleaned),
            }
            num = sum(self.weights.get(k, 0.0) * v for k, v in comp.items())
            den = sum(self.weights.get(k, 0.0) for k in comp)
            final = num / den if den > 0 else 0.0
            final -= sum(self.penalties.get(k, 0.0) * v for k, v in pen.items())
            scored.append(ScoredCandidate(r, cleaned, max(0.0, min(1.0, final)),
                                          {k: round(v, 3) for k, v in comp.items()},
                                          {k: round(v, 3) for k, v in pen.items()}))
        scored.sort(key=lambda c: c.final_score, reverse=True)
        return scored

    def _length_score(self, text: str) -> float:
        n = len(text)
        if n < self.processor.min_text_len:
            return 0.0
        if n <= self.max_expected_len:
            return 1.0
        return max(0.0, 1.0 - (n - self.max_expected_len) / self.max_expected_len)

    @staticmethod
    def explain(c: ScoredCandidate) -> str:
        parts = ", ".join(f"{k}={v:.2f}" for k, v in c.components.items())
        pens = ", ".join(f"{k}={v:.2f}" for k, v in c.penalties.items() if v)
        return (f"{c.result.engine}: final_score={c.final_score:.2f} ({parts})"
                + (f" penalties({pens})" if pens else ""))
