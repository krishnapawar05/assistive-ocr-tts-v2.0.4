"""Baseline benchmark for the unmodified v2.0.4 OCREngine.

Measures engine init time, per-image end-to-end latency, per-engine latency, which
engine wins the length-first selection, RSS memory, and character error rate against
synthetic ground truth. Does not modify or monkeypatch the engine's behavior; per-engine
timings call the engine's own private methods on the same preprocessed inputs.

Run from repo root:
    .venv/Scripts/python.exe tests/benchmarks/baseline_ocr.py
Writes docs/baseline/ocr-baseline.json. No frames are saved to disk.
"""
import json
import os
import platform
import sys
import time

import cv2
import numpy as np
import psutil
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from core.config import DEFAULT_CONFIG  # noqa: E402
from core import ocr_engine  # noqa: E402
from core.ocr_engine import OCREngine  # noqa: E402

REPEATS = 3

# (id, text, font size, style) — English only; Indic rendering needs raqm shaping.
SAMPLES = [
    ("sign_short", "Room 204", 96, "clean"),
    ("sentence", "The quick brown fox jumps over the lazy dog", 48, "clean"),
    ("board_lines", "Photosynthesis\nLight energy to chemical energy", 44, "board"),
    ("numbers", "Chapter 7 Page 132", 56, "clean"),
    ("low_contrast", "Exit on the left", 60, "low_contrast"),
    ("blurred", "Library closes at 5 PM", 52, "blur"),
    ("blank", "", 40, "clean"),
]


def render(text: str, size: int, style: str) -> np.ndarray:
    """Render a 1280x720 BGR frame, matching the pipeline's 720p capture size."""
    w, h = 1280, 720
    if style == "board":
        bg, fg = (30, 60, 30), (235, 235, 235)
    elif style == "low_contrast":
        bg, fg = (170, 170, 170), (120, 120, 120)
    else:
        bg, fg = (255, 255, 255), (0, 0, 0)
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    if text:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=12)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.multiline_text(((w - tw) // 2, (h - th) // 2), text, font=font, fill=fg, spacing=12, align="center")
    frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    if style == "blur":
        frame = cv2.GaussianBlur(frame, (9, 9), 3)
    return frame


def cer(ref: str, hyp: str) -> float:
    """Character error rate (Levenshtein / len(ref)), whitespace-normalized, case-insensitive."""
    ref = " ".join(ref.lower().split())
    hyp = " ".join(hyp.lower().split())
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1e6


def run() -> dict:
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        saved_cfg = json.load(f)
    ocr_cfg = dict(DEFAULT_CONFIG["ocr"])
    ocr_cfg.update(saved_cfg.get("ocr", {}))

    rss_before = rss_mb()
    t0 = time.perf_counter()
    engine = OCREngine(ocr_cfg)
    init_s = time.perf_counter() - t0
    rss_after_init = rss_mb()

    loaded = {
        "tesseract": ocr_engine.TESSER_AVAILABLE,
        "paddle": engine.paddle is not None,
        "easyocr": engine.easyocr is not None,
        "trocr": engine.trocr_model is not None,
    }

    results = []
    for sid, text, size, style in SAMPLES:
        frame = render(text, size, style)
        # Same preprocessing extract_text applies for a 1280x720 frame: grayscale, no crop/resize.
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        e2e = []
        out = None
        for _ in range(REPEATS):
            t = time.perf_counter()
            out = engine.extract_text(frame)
            e2e.append(time.perf_counter() - t)

        per_engine = {}
        for name, fn, arg in (
            ("tesseract", engine._ocr_tesseract, gray),
            ("paddle", engine._ocr_paddle, frame),
            ("easyocr", engine._ocr_easy, frame),
            ("trocr", engine._ocr_trocr, gray),
        ):
            if not loaded[name]:
                continue
            t = time.perf_counter()
            res, conf = fn(arg)
            per_engine[name] = {
                "latency_s": round(time.perf_counter() - t, 3),
                "text": res.text,
                "confidence": round(conf, 3),
                "cer": round(cer(text, res.text), 3),
            }

        results.append({
            "id": sid,
            "style": style,
            "ground_truth": text,
            "output_text": out.text,
            "winning_engine": out.engine,
            "confidence": round(out.confidence, 3),
            "cer": round(cer(text, out.text), 3),
            "e2e_latency_s": {
                "min": round(min(e2e), 3),
                "median": round(sorted(e2e)[len(e2e) // 2], 3),
                "max": round(max(e2e), 3),
            },
            "per_engine": per_engine,
        })
        print(f"{sid:14s} winner={out.engine or '-':9s} cer={results[-1]['cer']:.2f} "
              f"median={results[-1]['e2e_latency_s']['median']:.2f}s text={out.text[:50]!r}", flush=True)

    return {
        "note": "Synthetic English frames only. Accuracy here is NOT representative of real "
                "classroom captures; Hindi/Kannada not measured.",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(logical=True),
            "total_ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        },
        "ocr_config": ocr_cfg,
        "engines_loaded": loaded,
        "init_time_s": round(init_s, 2),
        "rss_mb": {
            "before_init": round(rss_before),
            "after_init": round(rss_after_init),
            "after_run": round(rss_mb()),
        },
        "repeats_per_image": REPEATS,
        "results": results,
    }


if __name__ == "__main__":
    report = run()
    out_path = os.path.join(ROOT, "docs", "baseline", "ocr-baseline.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\ninit={report['init_time_s']}s rss={report['rss_mb']} loaded={report['engines_loaded']}")
    print(f"wrote {out_path}")
