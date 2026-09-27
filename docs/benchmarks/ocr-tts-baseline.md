# OCR → TTS benchmark (Milestone A)

**Run:** 2026-09-26T22:38:06 → 2026-09-26T22:46:58 (wall time 532 s). Total limit 25 min; outcome: **completed within limits**.

> These are measurements of **synthetic fixtures on a memory-constrained development laptop**. They validate that the stages work and bound their cost. They are not accuracy results, not Jetson numbers, and not evidence of production readiness.

Status legend: **MEASURED** (ran, statistics from completed samples only) · **MEASURED_WITH_FAILURES** (some calls failed; statistics exclude them) · **NOT_AVAILABLE** (engine/runtime/model missing) · **FAILED** · **TIMED_OUT** · **KILLED_LOW_MEMORY** · **SKIPPED_LOW_MEMORY** / **SKIPPED_TOTAL_TIMEOUT** (not started).

## 1. Environment

- OS: Windows-10-10.0.26200-SP0
- Python: 3.10.0
- CPU: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel — 10 cores / 12 threads, max clock 1300 MHz
- GPU/NPU: none used (CPU inference only)
- RAM: 8.3 GB total

## 2. Hardware/resource constraints

- Available RAM at benchmark start: **1.3 GB** (84.3% in use by other applications before the benchmark started).
- Stage minimum available RAM before start: engine:tesseract ≥ 0.3 GB, engine:easyocr ≥ 0.6 GB, engine:paddle ≥ 0.8 GB, engine:trocr ≥ 0.6 GB, mode:single_engine ≥ 0.6 GB, mode:fallback ≥ 0.8 GB, mode:trocr_regions ≥ 0.8 GB, tts:coqui ≥ 0.6 GB, tts:espeak ≥ 0.3 GB, tts:windows ≥ 0.3 GB, mode:ensemble ≥ 1.5 GB.
- Runtime memory floor: a child is killed if available RAM stays below 0.3 GB for 1 s.

## 3. OCR engine results (each engine alone, in its own process)

| Engine | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % (1 core=100) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tesseract | NOT_AVAILABLE | 0.73 | 0 | 0 | 0 | — | — | — | — | 77.3 | 53.1 |
| easyocr | MEASURED | 6.58 | 12 | 0 | 0 | 2.823 | 2.952 | 2.603 | 2.962 | 1417.6 | 946.4 |
| paddle | MEASURED_WITH_FAILURES | 11.71 | 11 | 1 | 0 | 11.399 | 12.524 | 11.124 | 12.524 | 1690.5 | 978.8 |
| trocr | MEASURED | 9.8 | 15 | 0 | 0 | 1.478 | 2.606 | 0.007 | 3.404 | 1479.7 | 831.4 |

Per-fixture reads (median latency, text, character error rate vs. the rendered text):

- **tesseract**: NOT_AVAILABLE — tesseract executable not found (set ocr.engines.tesseract.executable or add it to PATH; see README 'Tesseract')
- **easyocr**: room_204 2.85s `Room 204` (CER 0.0); sentence 2.77s `The quick brown fox jumps ov` (CER 0.0); greenboard 2.89s `Photosynthesis Light energy ` (CER 0.0); blank 2.71s `` (CER 0.0)
- **paddle**: room_204 11.86s `Room 204` (CER 0.0); sentence 11.29s `The quick brown fox jumps ov` (CER 0.0); greenboard 11.75s `Photosynthesis Light energy ` (CER 0.0); blank 11.47s `` (CER 0.0)
- **trocr**: room_204 0.86s `Room 204` (CER 0.0); sentence 2.22s `The quick brown fox jumps ov` (CER 0.0); greenboard 2.61s `Photosynthesis Light energy ` (CER 0.0); blank 0.01s `` (CER 0.0); hand_meet 1.48s `Meet me at noon` (CER 0.0)

## 4. OCR mode results (quality gate + preprocessing + OCRService, per frame)

| Mode | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % | Engines loaded at end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single_engine | MEASURED | 6.52 | 15 | 0 | 0 | 2.797 | 3.379 | 0.007 | 3.484 | 1594.7 | 951.6 | easyocr |
| fallback | MEASURED | 5.46 | 15 | 0 | 0 | 2.93 | 14.848 | 0.008 | 29.865 | 2089.3 | 950.8 | easyocr, paddle |
| trocr_regions | KILLED_LOW_MEMORY | 9.87 | 6 | 0 | 0 | 7.212 | 25.209 | 4.339 | 25.209 | 2591.5 | 439.1 | — |
| ensemble | SKIPPED_LOW_MEMORY | — | 0 | 0 | 0 | — | — | — | — | — | — | — |

Per-fixture outcome (engines run → text):

- **single_engine**: room_204: selected easyocr → `Room 204` (3 OK, regions from easyocr); sentence: selected easyocr → `The quick brown fox jump` (3 OK, regions from easyocr); greenboard: selected easyocr → `Photosynthesis Light ene` (3 OK, regions from easyocr); blank: unusable_frame (quality gate) → `` (3 OK); scene_room: no_text easyocr → `` (3 OK)
- **fallback**: room_204: selected easyocr → `Room 204` (3 OK, regions from easyocr); sentence: selected easyocr → `The quick brown fox jump` (3 OK, regions from easyocr); greenboard: selected easyocr → `Photosynthesis Light ene` (3 OK, regions from easyocr); blank: unusable_frame (quality gate) → `` (3 OK); scene_room: below_min_confidence easyocr+paddle → `` (3 OK; trocr skipped: no_text_region)
- **trocr_regions**: hand_meet: selected trocr → `Meet me at noon` (3 OK, regions from easyocr); hand_notes: selected trocr → `Revise chapter three` (3 OK, regions from easyocr)
- **ensemble**: SKIPPED_LOW_MEMORY — available RAM 1.18 GB < required 1.5 GB

`trocr_regions` = single_engine with TrOCR selected (text_type handwritten): EasyOCR runs only to find text regions and TrOCR reads them (ADR 0007). TrOCR never sees a whole frame.


## 5. TTS results (no repeated audible playback)

| Engine | Status | Load s | Measured | Done | Median s | Min s | Max s | Peak RSS MB | Notes |
|---|---|---|---|---|---|---|---|---|---|
| coqui | MEASURED | 20.66 | synthesis only ×3 | 3 | 1.073 | 1.015 | 1.077 | 880.6 | audio length 2.369 s, real-time factor 0.45 |
| espeak | MEASURED | 0.07 | one utterance at volume 0 (process start + synthesis + silent playback) | 1 | 3.605 | 3.605 | 3.605 | 61.5 |  |
| windows | MEASURED | 0.74 | one utterance at volume 0 (process start + synthesis + silent playback) | 1 | 4.59 | 4.59 | 4.59 | 146.0 |  |

## 6. Timeout / failure / skip results

| Stage | Child result | Exit | Wall s | Abort reason / skip reason |
|---|---|---|---|---|
| engine:tesseract | COMPLETED | 0 | 1.6 |  |
| engine:easyocr | COMPLETED | 0 | 45.8 |  |
| engine:paddle | COMPLETED | 0 | 173.8 |  |
| engine:trocr | COMPLETED | 0 | 40.0 |  |
| mode:single_engine | COMPLETED | 0 | 47.0 |  |
| mode:fallback | COMPLETED | 0 | 96.9 |  |
| mode:trocr_regions | KILLED_LOW_MEMORY | 15 | 87.2 |  |
| tts:coqui | COMPLETED | 0 | 28.7 |  |
| tts:espeak | COMPLETED | 0 | 4.3 |  |
| tts:windows | COMPLETED | 0 | 5.8 |  |
| mode:ensemble | SKIPPED_LOW_MEMORY | — | — | available RAM 1.18 GB < required 1.5 GB |

## 7. Memory measurements

| Stage | Available RAM before (GB) | Lowest available during (GB) | Peak RSS of child (MB) |
|---|---|---|---|
| engine:tesseract | 1.29 | 1.25 | 77.3 |
| engine:easyocr | 1.51 | 0.46 | 1417.6 |
| engine:paddle | 2.23 | 0.34 | 1690.5 |
| engine:trocr | 1.83 | 0.29 | 1479.7 |
| mode:single_engine | 2.0 | 0.38 | 1594.7 |
| mode:fallback | 2.12 | 0.24 | 2089.3 |
| mode:trocr_regions | 2.46 | 0.06 | 2591.5 |
| tts:coqui | 2.32 | 0.7 | 880.6 |
| tts:espeak | 1.57 | 1.3 | 61.5 |
| tts:windows | 1.38 | 1.05 | 146.0 |
| mode:ensemble | 1.18 | — | — |

## 8. End-to-end observations

- Fastest measured OCR engine: trocr (1.478 s median); slowest: paddle (11.399 s median).
- engine:paddle: MEASURED_WITH_FAILURES (OCRError: [paddle] INFERENCE_FAILED: RuntimeError: Unknown exception).
- mode:trocr_regions: KILLED_LOW_MEMORY (KILLED_LOW_MEMORY).
- mode:ensemble: SKIPPED_LOW_MEMORY (available RAM 1.18 GB < required 1.5 GB).
- Fallback mode loaded only easyocr, paddle for these fixtures (lazy loading of fallback engines).
- single_engine: no-text scene → text ['']; TrOCR not run ({}); median 2.82 s.
- fallback: no-text scene → text ['']; TrOCR not run ({'trocr': 'no_text_region'}); median 14.85 s.
- single_engine: the blank frame was rejected by the quality gate before OCR (7.0 ms).
- fallback: the blank frame was rejected by the quality gate before OCR (8.0 ms).

## 9. Known limitations

- Synthetic, rendered fixtures (4 images, 2 handwriting images, 1 no-text room scene): they verify function and bound latency; they say nothing about accuracy on real classroom captures.
- Measured on a Windows laptop with little free RAM; other applications affect latency. No Jetson numbers. No camera capture timing (the camera is not opened by the benchmark).
- 3 repeats × 4 fixtures = 12 samples per stage, so p95 is effectively the slowest sample.
- Mode latency covers quality gate + preprocessing + OCR; duplicate filtering and speech are measured separately (text processing and scoring are sub-millisecond and not timed here).
- Windows speech and eSpeak are timed once each including process start and silent playback; they are not synthesis-only numbers.
- CPU % is the child's summed per-process CPU (100 = one full logical core), sampled every 0.25 s.

## 10. Exact benchmark configuration

- Script: `tests/benchmarks/isolated_benchmark.py` (commit c58fef5)
- Config: `core.config.DEFAULT_CONFIG` (not the local `config.json`); TTS volume forced to 0.
- Fixtures: engines room_204, sentence, greenboard, blank (+ hand_meet for TrOCR); modes room_204, sentence, greenboard, blank, scene_room; trocr_regions hand_meet, hand_notes, scene_room; 3 timed repeats; 1 untimed warm-up call per stage after loading.
- Timeouts: 60 s per OCR/TTS call, 6 min per child process, 25 min total.
- Stage order: engine:tesseract → engine:easyocr → engine:paddle → engine:trocr → mode:single_engine → mode:fallback → mode:trocr_regions → tts:coqui → tts:espeak → tts:windows → mode:ensemble (ensemble last).
- Offline: HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True.
- Raw data: `tests/benchmarks/output/isolated-20260926-223806.json` and `.jsonl` (not committed).

## 11. Timestamp

2026-09-26T22:38:06 (local time).

## 12. Re-run of the incomplete stages (added manually)

`mode:trocr_regions` (killed after 6 of 9 samples) and `mode:ensemble` (skipped: 1.18 GB < 1.5 GB
available) were re-run alone with `--only mode:trocr_regions mode:ensemble` at 2026-09-26 ~22:57
after the dashboard app was stopped (raw data: `tests/benchmarks/output/rerun-trocr-ensemble.*`).

| Stage | Available RAM at start | Load | Warm-up frame (not timed) | Result |
|---|---|---|---|---|
| mode:trocr_regions | 1.65 GB | TrOCR 9.5 s (EasyOCR loads on the first frame) | hand_meet 23.96 s | KILLED_LOW_MEMORY at 36.5 s (available 0.16 GB, child peak 2.16 GB); 0 timed samples |
| mode:ensemble | 2.28 GB | EasyOCR + PaddleOCR + TrOCR 17.5 s | room_204 37.94 s | KILLED_LOW_MEMORY at 67.6 s (available 0.21 GB, child peak 2.02 GB); 0 timed samples |

So on this 8 GB laptop with the usual desktop applications open, **ensemble mode cannot be
benchmarked** and TrOCR-on-regions only partially (section 4: 6 handwriting samples, median 7.2 s,
both handwriting fixtures read exactly). Both need about 2.6 GB for the process; running them
needs more free memory than this machine had, or the target device. The no-text scene result for
`trocr_regions` is covered by the test suite instead (`tests/integration/test_ocr_pipeline.py`:
TrOCR is skipped with `no_text_region` in every mode).

### 12b. PaddleOCR engine stage re-run with a single worker thread

The one failed PaddleOCR sample in section 3 (`RuntimeError: Unknown exception` on the 10th call)
was caused by the benchmark harness: `_call` started a new thread for every call, and a
PaddlePaddle predictor leaks about 0.1 GB per new calling thread and eventually crashes
(ADR 0006 addendum). With `_call` fixed to use one worker thread per child
(`--only engine:paddle`, label `rerun-paddle-onethread`):

| Engine | Status | Load s | Done | Failed | Median s | Min s | Max s | Peak RSS MB |
|---|---|---|---|---|---|---|---|---|
| paddle | MEASURED | 8.3 | 12 | 0 | 11.12 | 10.84 | 11.42 | 1486.4 |

All 12 reads were correct (room_204, sentence, greenboard: CER 0; blank: empty).
