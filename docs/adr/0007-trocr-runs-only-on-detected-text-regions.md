# ADR 0007 — TrOCR runs only on text regions found by another engine

- Status: Accepted
- Date: 2026-09-26

## Context

TrOCR (`microsoft/trocr-base-handwritten`) is a recognizer: it turns a crop into text. It has
no detector and no notion of "there is no text here", so it produces *some* text for almost any
crop it is given.

v2.0.4 ran TrOCR on the whole frame. The first refactor (ADR 0003) fed it line crops from a
classical OpenCV localizer (`regions.find_text_lines`). That removed blank-frame output, but the
localizer also boxes text-like shapes. At runtime, a camera frame of a room with no text went
through fallback mode: EasyOCR and PaddleOCR found nothing, then TrOCR read `"0 2 . 0 0"`
(confidence 0.68, score 0.61, above `min_final_score` 0.5). That text was **selected** and
would have been spoken. The same happens on the synthetic fixture `scenes/scene_room.png`
(clock, light switch, chair, window grille): TrOCR reads `"0 0000"` at 0.65.

Raising a global threshold would not fix this: the invented text's scores (0.61–0.72) overlap
real handwriting read by TrOCR. It would also suppress real text from every engine.

A detector box alone is not enough evidence either. On the same scenes, PaddleOCR's detector
boxes the clock, switch and grille, and reads them as `"�"`, `"E"`, `"D"`, `"jl"`. EasyOCR
finds nothing on them. On handwriting, both detectors box the line even when their own
recognition is poor (EasyOCR: `"Weet me at Moon"`, confidence 0.50).

## Decision

- Adapters declare `needs_text_regions`. TrOCR does. EasyOCR and PaddleOCR report each region
  they read in `OCRResult.metadata["text_regions"]` (box + text). Their text, confidence and
  boxes are unchanged.
- `OCRService` runs a region-only engine **only** on the regions of the first engine in this
  frame whose own reading of a region is plausible text. "Plausible" uses the rule that already
  gates speech: `TextProcessor.is_valid` (`min_text_len`, has letters or digits, validity).
  PaddleOCR's `"E"` or `"�"` on a light switch or clock is not a text region.
- Without such a region the engine is not run, and `OCRDecision.skipped[engine]` records why:
  - `no_text_region`: an engine ran and found no plausible text.
  - `no_region_source`: no engine that finds regions could run.
- Ordering, so every mode keeps its meaning:
  - fallback: a region-only engine reached before any region-finding engine is retried right
    after the next one. Fallback still stops as soon as a candidate reaches `accept_score`.
  - ensemble: region-only engines run last.
  - single_engine with TrOCR selected: the first available region-finding engine in the order
    runs only to supply regions. Its own text is not a candidate.
- The region-finding engine's regions are mapped via image fractions, merged into lines
  (`ocr.regions.merge_*`) and padded (`ocr.regions.padding_px`). `TrOCRAdapter.recognize(image)`
  without regions keeps the classical localizer for standalone adapter tests and benchmarks.
  The service never uses that path.
- No thresholds changed.

## Consequences

- On a frame with no text, TrOCR costs nothing and can no longer invent speech. Regression
  tests: `tests/unit/test_ocr_service.py::TrOCRRegionGatingTest`,
  `tests/integration/test_ocr_pipeline.py` (no-text scenes in every mode, pipeline speaks
  nothing), `tests/integration/test_app_api.py` (Test OCR reports `skipped`).
- Handwriting still reaches TrOCR when EasyOCR or PaddleOCR boxes it with a plausible (even
  low-confidence) reading, and TrOCR then re-reads that line.
- TrOCR alone, without EasyOCR or PaddleOCR installed, reads nothing (`no_engine_available`).
  Single-engine TrOCR also loads the region-finding engine.
- Residual risk: if a detector's reading of a non-text object passes `is_valid` (3+
  plausible characters), TrOCR re-reads that region and can still produce text. The detector
  then already produced a candidate itself, so this is no worse than the detector alone.
- Tesseract returns word-level boxes and is not installed on the dev machine, so it is not a
  region source yet.
