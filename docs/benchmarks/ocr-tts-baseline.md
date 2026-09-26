# OCR → TTS benchmark (Milestone A)

**Run:** 2026-09-26T19:46:47 → 2026-09-26T19:52:58 (wall time 371 s). Total limit 25 min; outcome: **completed within limits**.

> These are measurements of **synthetic fixtures on a memory-constrained development laptop**. They validate that the stages work and bound their cost. They are not accuracy results, not Jetson numbers, and not evidence of production readiness.

Status legend: **MEASURED** (ran, statistics from completed samples only) · **MEASURED_WITH_FAILURES** (some calls failed; statistics exclude them) · **NOT_AVAILABLE** (engine/runtime/model missing) · **FAILED** · **TIMED_OUT** · **KILLED_LOW_MEMORY** · **SKIPPED_LOW_MEMORY** / **SKIPPED_TOTAL_TIMEOUT** (not started).

## 1. Environment

- OS: Windows-10-10.0.26200-SP0
- Python: 3.10.0
- CPU: Intel64 Family 6 Model 154 Stepping 4, GenuineIntel — 10 cores / 12 threads, max clock 1300 MHz
- GPU/NPU: none used (CPU inference only)
- RAM: 8.3 GB total

## 2. Hardware/resource constraints

- Available RAM at benchmark start: **1.36 GB** (83.5% in use by other applications before the benchmark started).
- Stage minimum available RAM before start: engine:tesseract ≥ 0.3 GB, engine:easyocr ≥ 0.6 GB, engine:paddle ≥ 0.8 GB, engine:trocr ≥ 0.6 GB, mode:single_engine ≥ 0.6 GB, mode:fallback ≥ 0.8 GB, tts:coqui ≥ 0.6 GB, tts:espeak ≥ 0.3 GB, tts:windows ≥ 0.3 GB, mode:ensemble ≥ 1.5 GB.
- Runtime memory floor: a child is killed if available RAM stays below 0.3 GB for 1 s.

## 3. OCR engine results (each engine alone, in its own process)

| Engine | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % (1 core=100) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tesseract | NOT_AVAILABLE | 1.95 | 0 | 0 | 0 | — | — | — | — | 77.2 | 35.2 |
| easyocr | MEASURED | 31.6 | 12 | 0 | 0 | 2.702 | 2.769 | 2.528 | 13.187 | 1356.3 | 0.0 |
| paddle | FAILED | 16.38 | 0 | 0 | 0 | — | — | — | — | 870.3 | 763.6 |
| trocr | KILLED_LOW_MEMORY | 11.8 | 14 | 0 | 0 | 2.532 | 3.559 | 0.011 | 3.658 | 1463.2 | 632.4 |

Per-fixture reads (median latency, text, character error rate vs. the rendered text):

- **tesseract**: NOT_AVAILABLE — tesseract executable not found (set ocr.engines.tesseract.executable or add it to PATH; see README 'Tesseract')
- **easyocr**: room_204 2.70s `Room 204` (CER 0.0); sentence 2.74s `The quick brown fox jumps ov` (CER 0.0); greenboard 2.75s `Photosynthesis Light energy ` (CER 0.0); blank 2.53s `` (CER 0.0)
- **paddle**: FAILED — paddleocr det=PP-OCRv5_server_det rec=en_PP-OCRv5_mobile_rec device=cpu
- **trocr**: room_204 1.40s `Room 204` (CER 0.0); sentence 3.16s `The quick brown fox jumps ov` (CER 0.0); greenboard 3.56s `Photosynthesis Light energy ` (CER 0.0); blank 0.01s `` (CER 0.0); hand_meet 1.76s `Meet me at noon` (CER 0.0)

## 4. OCR mode results (quality gate + preprocessing + OCRService, per frame)

| Mode | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % | Engines loaded at end |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single_engine | MEASURED | 11.63 | 12 | 0 | 0 | 3.896 | 4.087 | 0.01 | 4.179 | 1559.4 | 695.1 | easyocr |
| fallback | MEASURED | 9.82 | 12 | 0 | 0 | 2.761 | 2.982 | 0.006 | 3.273 | 1551.9 | 922.2 | easyocr |
| ensemble | SKIPPED_LOW_MEMORY | — | 0 | 0 | 0 | — | — | — | — | — | — | — |

Per-fixture outcome (engines run → text):

- **single_engine**: room_204: selected easyocr → `Room 204` (3 OK); sentence: selected easyocr → `The quick brown fox jump` (3 OK); greenboard: selected easyocr → `Photosynthesis Light ene` (3 OK); blank: unusable_frame (quality gate) → `` (3 OK)
- **fallback**: room_204: selected easyocr → `Room 204` (3 OK); sentence: selected easyocr → `The quick brown fox jump` (3 OK); greenboard: selected easyocr → `Photosynthesis Light ene` (3 OK); blank: unusable_frame (quality gate) → `` (3 OK)
- **ensemble**: SKIPPED_LOW_MEMORY — available RAM 1.46 GB < required 1.5 GB

## 5. TTS results (no repeated audible playback)

| Engine | Status | Load s | Measured | Done | Median s | Min s | Max s | Peak RSS MB | Notes |
|---|---|---|---|---|---|---|---|---|---|
| coqui | MEASURED | 16.59 | synthesis only ×3 | 3 | 1.4 | 1.375 | 1.46 | 887.3 | audio length 2.334 s, real-time factor 0.60 |
| espeak | MEASURED | 0.09 | one utterance at volume 0 (process start + synthesis + silent playback) | 1 | 2.916 | 2.916 | 2.916 | 61.2 |  |
| windows | MEASURED | 0.81 | one utterance at volume 0 (process start + synthesis + silent playback) | 1 | 4.061 | 4.061 | 4.061 | 145.7 |  |

## 6. Timeout / failure / skip results

| Stage | Child result | Exit | Wall s | Abort reason / skip reason |
|---|---|---|---|---|
| engine:tesseract | COMPLETED | 0 | 2.7 |  |
| engine:easyocr | COMPLETED | 0 | 112.2 |  |
| engine:paddle | ABORTED | 3 | 77.4 | warm-up timed out |
| engine:trocr | KILLED_LOW_MEMORY | 15 | 49.2 |  |
| mode:single_engine | COMPLETED | 0 | 54.0 |  |
| mode:fallback | COMPLETED | 0 | 40.9 |  |
| tts:coqui | COMPLETED | 0 | 25.0 |  |
| tts:espeak | COMPLETED | 0 | 3.6 |  |
| tts:windows | COMPLETED | 0 | 5.5 |  |
| mode:ensemble | SKIPPED_LOW_MEMORY | — | — | available RAM 1.46 GB < required 1.5 GB |

## 7. Memory measurements

| Stage | Available RAM before (GB) | Lowest available during (GB) | Peak RSS of child (MB) |
|---|---|---|---|
| engine:tesseract | 1.36 | 1.22 | 77.2 |
| engine:easyocr | 1.29 | 0.38 | 1356.3 |
| engine:paddle | 1.89 | 0.88 | 870.3 |
| engine:trocr | 1.75 | 0.03 | 1463.2 |
| mode:single_engine | 1.42 | 0.27 | 1559.4 |
| mode:fallback | 1.84 | 0.24 | 1551.9 |
| tts:coqui | 2.29 | 0.86 | 887.3 |
| tts:espeak | 1.71 | 1.57 | 61.2 |
| tts:windows | 1.62 | 1.34 | 145.7 |
| mode:ensemble | 1.46 | — | — |

## 8. End-to-end observations

- Fastest measured OCR engine: trocr (2.532 s median); slowest: easyocr (2.702 s median).
- engine:paddle: FAILED (warm-up timed out).
- engine:trocr: KILLED_LOW_MEMORY (KILLED_LOW_MEMORY).
- mode:ensemble: SKIPPED_LOW_MEMORY (available RAM 1.46 GB < required 1.5 GB).
- Fallback mode loaded only easyocr for these fixtures (lazy loading of fallback engines).
- single_engine: the blank frame was rejected by the quality gate before OCR (10.0 ms).
- fallback: the blank frame was rejected by the quality gate before OCR (7.0 ms).

## 9. Known limitations

- Synthetic, rendered fixtures (4 images + 1 handwriting image): they verify function and bound latency; they say nothing about accuracy on real classroom captures.
- Measured on a Windows laptop with little free RAM; other applications affect latency. No Jetson numbers. No camera capture timing (the camera is not opened by the benchmark).
- 3 repeats × 4 fixtures = 12 samples per stage, so p95 is effectively the slowest sample.
- Mode latency covers quality gate + preprocessing + OCR; duplicate filtering and speech are measured separately (text processing and scoring are sub-millisecond and not timed here).
- Windows speech and eSpeak are timed once each including process start and silent playback; they are not synthesis-only numbers.
- CPU % is the child's summed per-process CPU (100 = one full logical core), sampled every 0.25 s.

## 10. Exact benchmark configuration

- Script: `tests/benchmarks/isolated_benchmark.py` (commit c027864)
- Config: `core.config.DEFAULT_CONFIG` (not the local `config.json`); TTS volume forced to 0.
- Fixtures: room_204, sentence, greenboard, blank (+ hand_meet for TrOCR); 3 timed repeats; 1 untimed warm-up call per stage after loading.
- Timeouts: 60 s per OCR/TTS call, 6 min per child process, 25 min total.
- Stage order: engine:tesseract → engine:easyocr → engine:paddle → engine:trocr → mode:single_engine → mode:fallback → tts:coqui → tts:espeak → tts:windows → mode:ensemble (ensemble last).
- Offline: HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True.
- Raw data: `tests/benchmarks/output/milestone-a-2.json` and `.jsonl` (not committed).

## 11. Timestamp

2026-09-26T19:46:47 (local time).
## 12. Run-to-run variation (earlier run, same evening — added manually)

An earlier run at 2026-09-26T19:35:50 (label `milestone-a`, 558 s) used the same stages and fixtures,
with two instrumentation defects that were fixed before the run above: its CPU column read 0 for
every stage, and its memory guard (0.25 GB for 3 s) let available RAM fall to **0.05 GB** during the
ensemble stage without killing it. Its latency and outcome data are valid and show how much the
results on this machine depend on free memory:

| Stage | Run 19:35 | Run 19:46 (report above) |
|---|---|---|
| engine:easyocr | MEASURED, median 3.05 s, max 18.2 s (room_204 8.5–18.2 s while RAM fell to 0.20 GB) | MEASURED, median 2.70 s, max 13.2 s |
| engine:paddle | MEASURED_WITH_FAILURES: 11 OK, median 11.70 s, p95 12.55 s; 1 call raised `RuntimeError: Unknown exception` (blank frame), contained as INFERENCE_FAILED | FAILED: warm-up call exceeded 60 s |
| engine:trocr | MEASURED, 15/15, median 1.12 s, p95 2.29 s | KILLED_LOW_MEMORY after 14/15 (available RAM 0.03 GB) |
| mode:single_engine | MEASURED, median 2.64 s | MEASURED, median 3.90 s |
| mode:fallback | MEASURED, median 3.02 s | MEASURED, median 2.76 s |
| mode:ensemble | TIMED_OUT: 2 OK (20.0 s, 18.7 s), 3rd call > 60 s; peak RSS 2.75 GB; available RAM fell to 0.05 GB | SKIPPED_LOW_MEMORY (1.46 GB < 1.5 GB) |
| tts:coqui synthesis | median 0.99 s (RTF 0.37) | median 1.40 s (RTF 0.60) |

Notes:
- The CPU % median covers the child's whole lifetime including model loading; a stage that spent
  most of its time loading while paging (EasyOCR: 31.6 s load) shows a low median.
- The memory guard samples every 0.25 s and requires 1 s below 0.3 GB before killing, so short
  dips below the floor (0.24–0.27 GB in the mode stages, 0.03 GB in TrOCR before its kill) can
  still happen. The guard prevents sustained exhaustion; it cannot prevent a spike that happens
  between samples.
