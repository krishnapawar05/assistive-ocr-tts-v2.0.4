# ADR 0002 — Staged pipeline with OCR/TTS/camera adapters

- Status: Accepted
- Date: 2026-09-26
- Replaces: `core/pipeline.py` internals of `v2.0.4-baseline`

## Context

In v2.0.4, `AssistivePipeline` owned the camera, called `OCREngine.extract_text` (all engines,
every frame) and `TTSEngine.speak` directly. Engine libraries were imported inside the OCR/TTS
classes, Jetson GStreamer strings lived in the pipeline, and every exception in the processing
and TTS threads was swallowed with `except Exception: continue`.

## Decision

Split the pipeline into stages with explicit contracts:

```
FrameController → QualityAssessor → ChangeDetector → Preprocessor → OCRService
    → DuplicateFilter → SpeechComposer → AudioManager → TTSService
```

- Hardware and engines sit behind interfaces: `CameraInterface`, `OCRAdapter`
  (tesseract/easyocr/paddle/trocr), `TTSAdapter` (coqui/windows/espeak). No module outside
  `core/ocr`, `core/tts`, `core/camera` imports an engine or camera library.
- Adapters never raise from `initialize()`; they report an `EngineStatus` with a reason.
  `INIT_FAILED` (installed but broken) is kept distinct from `NOT_AVAILABLE` so tests never
  pass off a defect as a missing dependency.
- `process_frame()` returns a typed outcome for every frame. Unexpected exceptions in the
  loop are logged with a traceback (`logger.exception`), never silently dropped.
- The `app.py` API and the `AssistivePipeline` methods it uses (`start`, `stop`,
  `get_status`, `get_history`) keep their v2.0.4 shape. `get_status` only gains keys.

## Consequences

- `core/ocr_engine.py` and `core/tts_engine.py` are no longer used by the app. They are kept
  unchanged (apart from the ADR 0001 fix) for baseline comparison
  (`tests/benchmarks/baseline_ocr.py`) and should be deleted once a real-image regression set
  exists.
- The v2.0.4 behaviors changed on purpose are listed in ADRs 0003 and 0004.
- On shutdown every worker thread is joined (`pipeline.shutdown()`, app lifespan hook).
