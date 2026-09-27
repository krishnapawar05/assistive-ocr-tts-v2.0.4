# ADR 0003 — Replace "longest text wins" with scored selection and engine modes

- Status: Accepted
- Date: 2026-09-26
- Deviates from baseline: yes (intentional)

## Context

v2.0.4 ran every loaded engine sequentially on every frame and picked
`max(candidates, key=(len(text), confidence))`. The baseline benchmark
(`docs/baseline/ocr-baseline.json`) showed the cost of that rule. EasyOCR alone was exact on 7
of 7 synthetic frames, yet whole-frame TrOCR output won 4 of 7 because it was longer. That
included reading `'0 0'` from a blank frame, which would have been spoken. Latency was 4.5–49 s
per frame because every engine ran.

## Decision

1. **Modes** (`ocr.mode`):
   - `single_engine` runs the first available engine of `[engine] + fallback_order`.
   - `fallback` runs engines in that order and stops as soon as a valid candidate scores
     `>= accept_score`. **This is the default.**
   - `ensemble` runs all available engines and fuses the results.
2. **Scoring** (`ocr.scoring`, all weights in config) combines confidence, engine
   reliability (separate tables for printed and handwritten text), cross-engine agreement
   (RapidFuzz), character validity, script/language consistency, length plausibility,
   optional bbox agreement and speed, minus garbage and repetition penalties. Length never
   rewards longer text. Nothing below `min_final_score` is spoken.
3. **TrOCR** only sees line crops. Its confidence is the mean token probability, and lines
   below `line_min_confidence` are dropped. *Superseded in part by ADR 0007:* inside
   OCRService the crops come from text regions found by EasyOCR/PaddleOCR, not from the OpenCV
   localizer.
4. Each engine runs on its own worker with `timeout_s`. A hung engine is skipped as `BUSY`
   instead of stalling the frame loop.

## Consequences

- Default latency is roughly one engine per frame instead of all of them (see
  `docs/benchmarks/ocr-tts-baseline.md`).
- The winner and rejected candidates are explained in DEBUG logs.
- Reliability weights are initial values from synthetic fixtures. They must be re-tuned on
  real classroom captures.
