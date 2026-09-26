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
