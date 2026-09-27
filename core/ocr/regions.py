"""Text-line boxes for line-level recognizers such as TrOCR, which hallucinate on non-text.

``lines_from_regions`` turns text regions found by a detector engine (EasyOCR/PaddleOCR) into
line crops; this is what OCRService uses. ``find_text_lines`` is the classical (OpenCV)
localizer, used only when the TrOCR adapter runs standalone: it also boxes non-text shapes
(clocks, switches), on which TrOCR invents text (ADR 0007).
"""
from typing import Any, Dict, List

import cv2
import numpy as np

from .types import BBox


def _merge_same_line(boxes: List[BBox], gap_ratio: float, min_overlap: float) -> List[BBox]:
    """Merge boxes that sit on the same line with a word-sized gap, independent of font size."""
    merged = True
    boxes = list(boxes)
    while merged:
        merged = False
        boxes.sort(key=lambda b: b[0])
        out: List[BBox] = []
        for b in boxes:
            for i, a in enumerate(out):
                top, bottom = max(a[1], b[1]), min(a[1] + a[3], b[1] + b[3])
                overlap = max(0, bottom - top) / float(min(a[3], b[3]))
                gap = max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2])
                if overlap >= min_overlap and gap <= gap_ratio * max(a[3], b[3]):
                    x1, y1 = min(a[0], b[0]), min(a[1], b[1])
                    x2, y2 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
                    out[i] = (x1, y1, x2 - x1, y2 - y1)
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def lines_from_regions(regions: List[BBox], shape, cfg: Dict[str, Any]) -> List[BBox]:
    """Merge detector regions (x, y, w, h) into padded lines in reading order, clipped to shape."""
    h, w = shape[:2]
    boxes = [b for b in regions if b[2] > 0 and b[3] > 0]
    boxes = _merge_same_line(boxes, float(cfg["merge_gap_height_ratio"]), float(cfg["merge_min_vertical_overlap"]))
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    boxes = boxes[: int(cfg["max_regions"])]
    boxes.sort(key=lambda b: (b[1], b[0]))
    pad = int(cfg["padding_px"])
    out = []
    for x, y, bw_, bh in boxes:
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(w, x + bw_ + pad), min(h, y + bh + pad)
        if x2 > x1 and y2 > y1:
            out.append((x1, y1, x2 - x1, y2 - y1))
    return out


def find_text_lines(gray: np.ndarray, cfg: Dict[str, Any]) -> List[BBox]:
    """Return line bounding boxes (x, y, w, h) sorted top-to-bottom, then left-to-right."""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if float(gray.std()) < float(cfg["min_contrast_std"]):
        return []

    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    otsu, _ = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    thresh = max(float(otsu), float(cfg["min_gradient"]))
    _, bw = cv2.threshold(grad, thresh, 255, cv2.THRESH_BINARY)

    # Join characters of one line horizontally without merging neighbouring lines.
    kw = max(3, int(w * float(cfg["join_width_fraction"])))
    kh = max(1, int(cfg["join_height_px"]))
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, kh)))

    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_h = int(cfg["min_line_height_px"])
    max_h = int(h * float(cfg["max_line_height_fraction"]))
    boxes: List[BBox] = []
    for c in contours:
        x, y, bw_, bh = cv2.boundingRect(c)
        if bh > max_h or (bh < min_h and bw_ < min_h):
            continue  # specks and oversized blobs; short-but-wide marks survive to merge into lines
        boxes.append((x, y, bw_, bh))
    boxes = [b for b in _merge_same_line(boxes, float(cfg["merge_gap_height_ratio"]),
                                         float(cfg["merge_min_vertical_overlap"]))
             if b[2] / float(b[3]) >= float(cfg["min_aspect_ratio"])]
    if boxes:
        # Detached diacritics/specks: much shorter than the typical line.
        median_h = float(np.median([b[3] for b in boxes]))
        boxes = [b for b in boxes if b[3] >= float(cfg["min_height_vs_median"]) * median_h]

    # Keep the largest regions if there are too many, then restore reading order.
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
    boxes = boxes[: int(cfg["max_regions"])]
    boxes.sort(key=lambda b: (b[1], b[0]))

    pad = int(cfg["padding_px"])
    return [(max(0, x - pad), max(0, y - pad), min(w, x + bw_ + pad) - max(0, x - pad),
             min(h, y + bh + pad) - max(0, y - pad)) for x, y, bw_, bh in boxes]
