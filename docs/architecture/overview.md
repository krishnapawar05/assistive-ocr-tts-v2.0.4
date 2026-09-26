# Architecture — OCR → TTS pipeline (Milestone A)

## Data flow

```
             ┌──────────────── core/camera ────────────────┐
 Camera ───► │ CameraInterface ─► FrameController          │  newest frame only, rate-limited,
 (USB/CSI)   │ (OpenCVCamera)      (thread "capture")      │  reconnect with backoff
             └──────────────────────┬──────────────────────┘
                                    ▼  (thread "process")
 core/frame   QualityAssessor ──► ChangeDetector ──► Preprocessor
              blank/dark/over-     skip frames that      center-crop huge frames,
              exposed/tiny/blur    match the last one    grayscale, upscale tiny
                                    ▼
 core/ocr     OCRService (mode: single_engine | fallback | ensemble)
                ├─ TesseractOCRAdapter   ┐ each on its own worker thread with a timeout;
                ├─ EasyOCRAdapter        │ only one engine runs at a time (ADR 0006)
                ├─ PaddleOCRAdapter      │
                └─ TrOCRAdapter ◄─ regions.find_text_lines (line crops)
              OCRScorer + TextProcessor ─► OCRDecision (winner + explained scores)
                                    ▼
 core/text    DuplicateFilter (exact / normalized / fuzzy, cooldown)
                                    ▼
 core/tts     SpeechComposer ─► AudioManager (thread "audio", one utterance at a time,
                                 queue | interrupt | drop_if_busy)
                                    ▼
              TTSService: [engine] + fallback_engines
                ├─ CoquiTTSAdapter (local VITS model, sounddevice playback)
                ├─ WindowsSpeechAdapter (System.Speech via PowerShell, env-var text)
                └─ EspeakAdapter (espeak-ng, text on stdin)
```

## Contracts

| Stage | Input | Output | Failure behavior |
|---|---|---|---|
| `CameraInterface.read` | — | BGR `ndarray` or `None` | `None` → counted; N in a row → reconnect |
| `QualityAssessor.assess` | frame | `QualityReport(usable, reasons, metrics)` | never raises |
| `Preprocessor.prepare` | frame | `PreparedFrame(color, gray)` | `FrameError` for malformed frames |
| `OCRAdapter.initialize` | — | `EngineStatus` + reason | never raises |
| `OCRAdapter.recognize` | image | `OCRResult` | `OCRError(code)` |
| `OCRService.recognize` | `PreparedFrame` | `OCRDecision` | never raises; per-engine errors recorded |
| `DuplicateFilter.check` | text | `(is_dup, kind)` | never raises |
| `TTSAdapter.speak` | text | `True` / `False` if interrupted | `TTSError(code)` |
| `TTSService.speak` | text | engine name | `TTSError(ALL_ENGINES_FAILED)` |
| `AudioManager.submit` | text | `queued` / `interrupting` / `dropped_*` | worker logs and survives TTS errors |
| `AssistivePipeline.process_frame` | anything | `ProcessOutcome(status, …)` | never raises |

`ProcessOutcome.status` is one of `invalid_frame`, `unusable_frame`, `unchanged`,
`no_ocr_engine`, `ocr_failed`, `no_text`, `duplicate`, `spoken`, `speech_dropped`.

## Engine status model

`READY`, `DISABLED`, `NOT_AVAILABLE` (package/runtime missing), `MODEL_NOT_AVAILABLE`
(local model files missing), `LANGUAGE_NOT_SUPPORTED`, `INIT_FAILED` (installed but crashed:
treated as a defect). Status and reason are shown in the dashboard ("Test OCR") and via
`/api/test-ocr`.

## Threads

| Thread | Owner | Stops on |
|---|---|---|
| `capture` | FrameController | `pipeline.stop()` |
| `process` | AssistivePipeline | `pipeline.stop()` (finishes the current OCR call) |
| `audio` | AudioManager | `pipeline.shutdown()` |
| `ocr-<engine>` | OCRService executors | `pipeline.shutdown()` |

## Hardware independence

Only `core/camera/opencv_camera.py` knows about OpenCV capture and the Jetson GStreamer
pipeline. Only `core/tts/*` knows about audio APIs and TTS executables. On the target device
a new `CameraInterface` (e.g. glasses-side transport) plugs in via
`AssistivePipeline(config, camera_factory=...)`.

## Decisions

See `docs/adr/`: 0001 PowerShell injection, 0002 staged pipeline, 0003 OCR scoring and modes,
0004 duplicates and speech policy, 0005 dependencies and config, 0006 engine serialization and
lazy loading.
