# ADR 0006 — One OCR engine at a time; load fallback engines lazily

- Status: Accepted
- Date: 2026-09-26

## Context

These decisions come from profiling the dev machine (Windows, low-power 12-thread Intel CPU at
1.3 GHz, 7.7 GB RAM with only 0.6–1 GB free while the IDE is open):

- EasyOCR takes about 2.8 s per 720p frame and is stable. PaddleOCR (`PP-OCRv5_server_det`)
  takes about 11 s at best and 45–100 s when the machine pages. Shrinking Paddle's detector
  input (`det_limit_side_len` 736) did not help (11.4 s against 11.8 s at default).
- In a benchmark run, EasyOCR hit its 60 s timeout under memory pressure. The service then
  started PaddleOCR while the EasyOCR call was still running, and the process **segfaulted**
  in native code. Concurrent EasyOCR+Paddle runs without memory pressure did not crash, which
  points to memory exhaustion rather than a thread-safety bug. On an 8 GB device that
  distinction does not matter: two engines at once is not safe.
- Loading every engine at startup cost 41.5 s and 643 MB, although the primary engine alone
  handles most frames.

## Decision

- `ocr.serialize_engines: true` (default): no OCR engine starts while any engine call is
  still running. This is process-wide and also covers a timed-out call left over from a
  service replaced after a config change. Blocked engines report `BUSY` and the frame yields
  no text; the pipeline keeps running and the next frame is tried.
- `ocr.preload: "primary"` (default): at startup, engines load in order until one is `READY`.
  Later fallback engines load the first time the fallback loop reaches them. `"all"` restores
  eager loading; `ensemble` mode always loads everything.

## Consequences

- OCR startup: 22.5 s / 249 MB (EasyOCR only) against 41.5 s / 643 MB.
- The first fallback to PaddleOCR pays its load time (about 17 s) once.
- A hung engine stops OCR until it returns, which is logged (`TIMEOUT`, then `BUSY`). This is
  preferred to crashing the process. A future process-isolated engine runner could allow
  killing a hung engine.

## Addendum (2026-09-26): one thread per PaddleOCR engine

Measured: one PaddleOCR engine called from a **new short-lived thread for each call** grew by
about 0.1 GB per thread (1.42 → 1.52 → 1.63 GB) and crashed natively on the 10th call (segfault).
The same engine called from **one long-lived thread** stayed at 0.99 GB for 12 of 12 calls.
PaddlePaddle keeps per-thread native state (oneDNN), and its predictors are not thread-safe.

- The app already meets this constraint: each `OCRService` drives each engine from one
  long-lived worker thread (`ThreadPoolExecutor(1)`), and a config reload builds new engine
  instances instead of sharing old ones. **Never share one adapter instance between
  services or call it from ad-hoc threads.**
- The test suite shares cached engines across many services, so `tests/ocr/engine_case.py`
  pins each cached engine to its own worker thread. Before that change, test modules crashed
  with an access violation.
- The benchmark's `_call` runs every call on one worker thread per child process. The earlier
  "PaddleOCR `RuntimeError: Unknown exception` after ~10 calls" came from its thread-per-call
  harness, not from the engine itself.
