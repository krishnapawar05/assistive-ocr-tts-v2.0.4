# Smart Vision Assist v2.0.4 — Architecture Audit & System Analysis

> **Document Version:** 2.0.4-audit  
> **Status:** Completed Baseline Audit  
> **Author:** Primary Engineering Agent (Google DeepMind Antigravity)  
> **Target Environment:** Development Laptop (x86_64 CPU, 8 GB RAM, Windows 10/11) & Production Deployment Target (Jetson Orin Nano, 8 GB / 4 GB, Linux/Tegra)  
> **Baseline Benchmark Reference:** [`docs/benchmarks/ocr-tts-baseline.md`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/docs/benchmarks/ocr-tts-baseline.md)  
> **Architectural Decisions Ref:** [`docs/adr/`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/docs/adr/) (ADR 0001 through 0007)

---

## 1. Current Architecture

The existing repository implements a decoupled, staged perception-to-speech pipeline designed for assistive reading. The software architecture replaces monolithic v2.0.4 classes (`core/ocr_engine.py`, `core/tts_engine.py`) with an adapter-driven, event-governed modular design coordinated through [`AssistivePipeline`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/pipeline.py#L50-L223).

```
                      ┌────────────────────────────────────────┐
                      │              Camera Stream             │
                      │  (USB/UVC Index or Jetson GStreamer)   │
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/camera/controller.py           │
                      │    FrameController (Thread: "capture") │
                      │    - Keeps newest frame only           │
                      │    - Rate-limits to capture_interval   │
                      │    - Auto-reconnect with backoff       │
                      └───────────────────┬────────────────────┘
                                          │ (Condition handoff)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/pipeline.py                    │
                      │    AssistivePipeline (Thread: "process")│
                      └───────────────────┬────────────────────┘
                                          │
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/frame/processing.py            │
                      │    1. QualityAssessor                  │
                      │       - blank, dark, overexposed, blur │
                      │    2. ChangeDetector                   │
                      │       - 32x32 thumbnail MAD, max_skip  │
                      │    3. Preprocessor                     │
                      │       - center-crop, grayscale, scale  │
                      └───────────────────┬────────────────────┘
                                          │ PreparedFrame (color, gray)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/ocr/service.py                 │
                      │    OCRService                          │
                      │    - Modes: single, fallback, ensemble │
                      │    - Engine serialization lock         │
                      │    - Dedicated ThreadPoolExecutors     │
                      │    - Lazy fallback engine loading      │
                      │    - TrOCR region gating (ADR 0007)    │
                      ├────────────────────────────────────────┤
                      │  Adapters:                             │
                      │  ├─ EasyOCRAdapter                     │
                      │  ├─ PaddleOCRAdapter (Thread-pinned)   │
                      │  ├─ TrOCRAdapter (Region-only crops)   │
                      │  └─ TesseractOCRAdapter (CLI/Subproc)  │
                      └───────────────────┬────────────────────┘
                                          │ Candidates & Bounding Boxes
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/ocr/scoring.py & text/         │
                      │    1. OCRScorer                        │
                      │       - Confidence, reliability, valid,│
                      │         agreement, language, length    │
                      │       - Garbage & repetition penalty   │
                      │    2. TextProcessor                    │
                      │       - NFC norm, clean, is_valid()    │
                      └───────────────────┬────────────────────┘
                                          │ Scored Winner (OCRDecision)
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/text/duplicates.py             │
                      │    DuplicateFilter                     │
                      │    - Exact, normalized, RapidFuzz      │
                      │    - Digit equality invariance         │
                      │    - Cooldown window & refresh_on_rep  │
                      └───────────────────┬────────────────────┘
                                          │ Fresh Text Utterance
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/tts/composer.py                │
                      │    SpeechComposer                      │
                      │    - Clamps length to max_chars        │
                      └───────────────────┬────────────────────┘
                                          │ SpeechRequest
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/audio/manager.py               │
                      │    AudioManager (Thread: "audio")      │
                      │    - Policy: queue/interrupt/drop_busy │
                      │    - Stale drop (max_age_s)            │
                      │    - Dropping oldest on full           │
                      └───────────────────┬────────────────────┘
                                          │ Audio Playback Dispatch
                                          ▼
                      ┌────────────────────────────────────────┐
                      │    core/tts/service.py                 │
                      │    TTSService                          │
                      │    - Primary + Fallback loop           │
                      ├────────────────────────────────────────┤
                      │  Adapters:                             │
                      │  ├─ CoquiTTSAdapter (VITS / sounddev)  │
                      │  ├─ WindowsSpeechAdapter (PowerShell)  │
                      │  └─ EspeakAdapter (espeak-ng / stdin)  │
                      └────────────────────────────────────────┘
```

### Module Responsibilities
* **`app.py`**: FastAPI ASGI web application. Exposes web dashboard with UI controls, diagnostic endpoints (`/api/status`, `/api/test-camera`, `/api/test-ocr`), text injection (`/api/speak`), and dynamic atomic configuration updates (`/api/config`).
* **`core/camera/`**: Implements hardware abstraction [`CameraInterface`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/camera/base.py#L11-L32) and [`OpenCVCamera`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/camera/opencv_camera.py#L13-L67) supporting standard USB/UVC cameras or Jetson GStreamer CSI pipelines. [`FrameController`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/camera/controller.py#L14-L120) runs the dedicated `capture` thread, continuously draining hardware driver buffers, rate-limiting frame publication, and managing exponential backoff reconnection.
* **`core/frame/`**: [`validate_frame`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/frame/processing.py#L33-L44) guarantees data integrity. [`QualityAssessor`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/frame/processing.py#L79-L107) rejects degenerate scenes (dark, overexposed, blank, blurred). [`ChangeDetector`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/frame/processing.py#L109-L136) performs 32x32 thumbnail mean absolute difference (MAD) comparison to prevent continuous inference on static scenes. [`Preprocessor`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/frame/processing.py#L47-L76) crops margins, upscales tiny images, and produces dual color/grayscale buffers ([`PreparedFrame`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/frame/processing.py#L17-L24)).
* **`core/ocr/`**: Multi-engine management via [`OCRService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L63-L272) supporting `single_engine`, `fallback`, and `ensemble`. Houses adapters for EasyOCR, PaddleOCR 3.x, TrOCR, and Tesseract. Governed by ADR 0006 (engine serialization and thread affinity) and ADR 0007 (TrOCR region gating). Multi-criteria decision engine in [`OCRScorer`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/scoring.py#L36-L100).
* **`core/text/`**: [`TextProcessor`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/text/processor.py#L20-L80) performs non-destructive cleaning (Unicode NFC normalization, control character stripping, symbol run collapse, script consistency checking). [`DuplicateFilter`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/text/duplicates.py#L14-L66) enforces exact, normalized, and fuzzy suppression with strict digit preservation and cooldown extension.
* **`core/tts/` and `core/audio/`**: [`AudioManager`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/audio/manager.py#L27-L151) serializes speech requests on a dedicated worker thread with stale speech dropping (`max_age_s`) and configurable queuing/interruption policies. [`TTSService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/tts/service.py#L20-L93) coordinates engine fallback across Coqui VITS, Windows System.Speech, and eSpeak NG.

---

## 2. Current Data Flow

The runtime execution follows a strict pipeline from sensor capture to audio actuation:

```
[Photons] 
   │
   ▼
1. OpenCV Camera Capture:
   OpenCVCamera.read() inside FrameController._run() on Thread "capture".
   Hardware buffers are drained continuously at 30 FPS.
   Frames arriving sooner than `capture_interval` (0.2s) are dropped.
   Valid frame stored into `self._latest` under Condition lock notify.
   │
   ▼
2. Frame Handoff to Pipeline:
   AssistivePipeline._process_loop() on Thread "process" waits on Condition (timeout=0.3s).
   Invokes `controller.get_frame()` -> takes `self._latest`, resets buffer to None.
   │
   ▼
3. Input Validation & Quality Gating:
   `validate_frame(frame)`: confirms np.ndarray, dtype uint8, converts BGRA to BGR.
   `QualityAssessor.assess(frame)`: evaluates brightness mean, contrast std dev, resolution, sharpness.
   If unusable -> returns ProcessOutcome("unusable_frame", reasons=...). (Latency: ~1-8 ms).
   │
   ▼
4. Change Detection:
   `ChangeDetector.is_unchanged(frame, now)`: downsamples frame to 32x32 thumbnail, computes MAD against previous processed frame.
   If MAD < 2.0 and elapsed time < 10.0s -> returns ProcessOutcome("unchanged"). (Latency: ~1 ms).
   │
   ▼
5. Preprocessing:
   `Preprocessor.prepare(frame)`: center-crops if max(H, W) > 1920 (margin 10%), converts to grayscale, upscales if max side < 400px.
   Produces PreparedFrame(color, gray). (Latency: ~2-10 ms).
   │
   ▼
6. OCR Service Dispatch:
   `OCRService.recognize(prepared)`:
   - Check engine schedule: order = [primary] + fallback_order.
   - Enforce Engine Serialization: Acquires process-wide `_INFLIGHT_LOCK`. Rejects concurrent execution with BUSY.
   - TrOCR Region Gating: TrOCR has `needs_text_regions=True`. If scheduled before region detector, it is deferred.
   - Engine 1 (e.g. EasyOCR) executes on dedicated ThreadPoolExecutor(1) `ocr-easyocr`.
   - Engine 1 yields OCRResult (text, confidence, bounding_boxes, text_regions).
   - Plausible text regions (`is_valid() == True`) are extracted as fractional bounding box hints.
   - Fallback evaluation: Scorer evaluates Engine 1 result. If final_score >= accept_score (0.75), stops!
   - If below accept_score, Engine 2 (e.g. PaddleOCR) is loaded lazily and executed on `ocr-paddle`.
   - If handwriting mode or TrOCR scheduled, TrOCR receives line crops corresponding to normalized region hints.
   (Latency: ~2.8s EasyOCR, ~11.4s PaddleOCR, ~1.5s TrOCR regions).
   │
   ▼
7. Multi-Criteria Scoring & Selection:
   `OCRScorer.score(results)`: computes weighted score:
     Score = 0.35*conf + 0.20*reliability + 0.15*validity + 0.15*agreement + 0.10*lang + 0.05*len + 0*speed - 0.50*garbage - 0.30*repeat.
   `OCRService._best()` selects top candidate having final_score >= 0.50 and `TextProcessor.is_valid() == True`.
   If winner found -> OCRDecision(winner=winner, reason="selected"). (Latency: <1 ms).
   │
   ▼
8. Text Duplicate Suppression:
   `DuplicateFilter.check(text, now)`:
   - Computes normalized alphanumeric key `duplicate_key(text)` (e.g. "Room 204." -> "room204").
   - Checks exact match against LRU history.
   - Checks fuzzy match (RapidFuzz ratio >= 90.0) with strict regex digit identity (`\d+` must match exactly).
   - If duplicate detected -> returns ProcessOutcome("duplicate"). If `refresh_on_repeat=True`, updates timestamp. (Latency: <1 ms).
   │
   ▼
9. Utterance Composition & History:
   Winner text appended to `AssistivePipeline.history` (retaining last 50).
   `SpeechComposer.compose(text)` clamps string to `max_chars` (300).
   │
   ▼
10. Audio Queue Dispatch:
    `AudioManager.submit(utterance, source="ocr")`:
    - Wraps utterance in `SpeechRequest(text, created=now)`.
    - If policy == "drop_if_busy" and speaking -> returns "dropped_busy".
    - If policy == "interrupt" -> clears queue, stops current speech (`_stop()`), queues new request.
    - If policy == "queue" -> appends to bounded queue (drops oldest if len >= max_queue_size 5).
    Condition variable notifies worker thread "audio".
    │
    ▼
11. TTS Synthesis & Playback:
    Worker thread "audio" executes `AudioManager._worker()`:
    - Pops request; checks `now - created > max_age_s` (30s). If stale, drops request (`dropped_stale`).
    - Invokes `TTSService.speak(req.text)`:
      - Tries primary engine (CoquiTTSAdapter): acquires internal model lock, synthesizes float32 audio, plays through `sounddevice.play()`, buffers WAV in memory for replay.
      - Fallback 1: WindowsSpeechAdapter (PowerShell System.Speech with environment variables).
      - Fallback 2: EspeakAdapter (espeak-ng subprocess via stdin pipe).
[Sound Output]
```

---

## 3. Current Lifecycle

```
[Application Startup]
  │
  ├─ 1. Load config: Config(CONFIG_PATH) validates schema, migrates legacy keys (ADR 0005)
  ├─ 2. Setup logging: logging.basicConfig(level=cfg.log_level)
  ├─ 3. Enforce offline mode: apply_offline_env() sets HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
  ├─ 4. Construct pipeline: AssistivePipeline(cfg)
  │      ├─ QualityAssessor, ChangeDetector, Preprocessor
  │      ├─ OCRService: binds adapters, initializes primary engine (preload: "primary")
  │      ├─ DuplicateFilter, SpeechComposer
  │      ├─ TTSService: binds TTS adapters, initializes primary & fallback engines
  │      └─ AudioManager: starts worker thread "audio"
  └─ 5. Start ASGI server: uvicorn.run(app) passes app instance directly (prevents double initialization)

[Runtime Operational Loop]
  │
  ├─ User / Client calls POST /api/start
  │      ├─ FrameController starts thread "capture" (opens camera, continuously polls frames)
  │      └─ AssistivePipeline starts thread "process" (loops get_frame -> process_frame)
  ├─ Continuous frame processing:
  │      └─ Capture -> Quality -> Change -> Preprocess -> OCR -> Decision -> DupFilter -> TTS
  └─ User / Client calls POST /api/stop
         ├─ FrameController stops capture thread and closes camera
         ├─ AssistivePipeline joins process thread (timeout=3.0s)
         └─ AudioManager.clear() drops pending queue and silences ongoing utterance

[Configuration Reload]
  │
  ├─ User / Client calls POST /api/config
  ├─ _reload_lock.acquire(blocking=False): rejects concurrent reloads with HTTP 409
  ├─ Config.update(payload): validates schema; returns HTTP 400 on error
  ├─ Pipeline lifecycle cycle:
  │      ├─ was_running = pipeline.running
  │      ├─ pipeline.shutdown() joins all threads, closes camera, stops executors
  │      ├─ pipeline = None (temporary state; endpoints return HTTP 503)
  │      ├─ gc.collect() forces immediate cleanup of unreferenced Python wrappers
  │      ├─ pipeline = AssistivePipeline(cfg) builds fresh service graph
  │      └─ if was_running: pipeline.start() restarts capture & process threads
  └─ _reload_lock.release()

[Application Shutdown]
  │
  ├─ FastAPI @asynccontextmanager lifespan hook catches server termination
  └─ pipeline.shutdown():
         ├─ pipeline.stop() (capture thread joined, camera closed, process thread joined)
         ├─ audio.shutdown() (audio thread joined, sounddevice/process stopped)
         └─ ocr.shutdown() (ThreadPoolExecutors canceled and stopped)
```

---

## 4. Concurrency Model

The application operates a multi-threaded architecture with explicit isolation boundaries:

### Thread Inventory
| Thread Name | Owner Component | Lifecycle | Concurrency Role |
|---|---|---|---|
| `MainThread` | Uvicorn / FastAPI | Server lifespan | Handles HTTP requests, API routing, dashboard rendering |
| `capture` | [`FrameController`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/camera/controller.py#L35) | `pipeline.start()` → `pipeline.stop()` | Dedicated camera polling; continuously drains OpenCV video buffer; publishes newest frame |
| `process` | [`AssistivePipeline`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/pipeline.py#L93) | `pipeline.start()` → `pipeline.stop()` | Pipeline consumer; waits on Condition; runs quality, change, preprocessing, OCR, duplicate check |
| `audio` | [`AudioManager`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/audio/manager.py#L52) | `AudioManager.start()` → `shutdown()` | Consumer worker for speech queue; executes TTS synthesis and sound playback sequentially |
| `ocr-easyocr` | [`OCRService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L81) | `OCRService` lifespan | Dedicated single-worker ThreadPoolExecutor for EasyOCR inference |
| `ocr-paddle` | [`OCRService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L81) | `OCRService` lifespan | Dedicated single-worker ThreadPoolExecutor for PaddleOCR inference (Thread affinity enforced) |
| `ocr-trocr` | [`OCRService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L81) | `OCRService` lifespan | Dedicated single-worker ThreadPoolExecutor for TrOCR inference |
| `ocr-tesseract`| [`OCRService`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L81) | `OCRService` lifespan | Dedicated single-worker ThreadPoolExecutor for Tesseract CLI execution |

### Synchronization Primitives & Locks
1. **`FrameController._cond` (`threading.Condition`)**: Synchronizes frame handoff between `capture` thread and `process` thread without queue accumulation.
2. **`AudioManager._cond` (`threading.Condition`)**: Synchronizes speech requests submitted by `process` thread or `/api/speak` with the `audio` worker thread.
3. **`_INFLIGHT_LOCK` (`threading.Lock` in `core/ocr/service.py:40`)**: Process-wide registry lock governing `_INFLIGHT` dictionary. When `serialize_engines=True`, ensures no OCR engine starts while any other OCR engine call is active anywhere in the process.
4. **`CoquiTTSAdapter._lock` (`threading.Lock` in `core/tts/coqui.py:30`)**: Guards `self._tts.tts()` synthesis calls. PyTorch VITS model inference is not thread-safe.
5. **`DuplicateFilter._lock` (`threading.Lock` in `core/text/duplicates.py:28`)**: Synchronizes access to `_seen` LRU OrderedDict.
6. **`AssistivePipeline.lock` (`threading.Lock` in `core/pipeline.py:75`)**: Synchronizes `history` modifications with web endpoint reads.
7. **`_reload_lock` (`threading.Lock` in `app.py:69`)**: Non-blocking lock preventing overlapping configuration updates.

### PaddleOCR Thread Affinity Constraint (ADR 0006)
PaddlePaddle's underlying C++ prediction library maintains per-thread native runtime state (oneDNN / MKLDNN context). Benchmarks revealed that invoking a PaddleOCR predictor across successive transient threads leaks ~100 MB per thread, triggering a native segmentation fault around call 10. By binding PaddleOCR to a dedicated single-threaded executor (`ocr-paddle`), memory remains completely flat across repeated calls.

---

## 5. Resource Model

### Memory Footprint Breakdown
The system was benchmarked on a Windows 10/11 x86_64 host with 8.3 GB total RAM and ~1.3 GB free memory at test launch ([`ocr-tts-baseline.md`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/docs/benchmarks/ocr-tts-baseline.md)):

| Component / Mode | Peak RSS (MB) | Resident Load Time (s) | Memory Behavior & Coexistence Notes |
|---|---|---|---|
| **EasyOCR Engine** | 1,417.6 MB | 6.58 s | PyTorch ResNet backbone + CTC decoder. Stable resident set. |
| **PaddleOCR Engine** | 1,690.5 MB | 11.71 s | PaddlePaddle PP-OCRv5 det + mobile rec. Leaks if threads not pinned. |
| **TrOCR Engine** | 1,479.7 MB | 9.80 s | HuggingFace VisionEncoderDecoderModel. Memory stable on line crops. |
| **Tesseract Engine** | 77.3 MB | 0.73 s | External process CLI execution. Negligible RAM footprint. |
| **Coqui VITS TTS** | 880.6 MB | 20.66 s | VITS PyTorch neural vocoder. Stable once loaded. |
| **eSpeak NG TTS** | 61.5 MB | 0.07 s | External process CLI execution. Ultra-low resource. |
| **Windows Speech TTS** | 146.0 MB | 0.74 s | Subprocess PowerShell host. Ephemeral memory usage. |
| **Single Engine Mode** | 1,594.7 MB | 6.52 s | EasyOCR alone + pipeline overhead. Stable. |
| **Fallback Mode (Easy+Paddle)** | 2,089.3 MB | 5.46 s | EasyOCR resident + PaddleOCR loaded on first fallback. High memory pressure. |
| **TrOCR on Regions Mode** | 2,591.5 MB | 9.87 s | EasyOCR detector + TrOCR recognizer co-resident. Triggered low-memory watchdog. |
| **Ensemble Mode** | > 2,600 MB | 17.50 s | All engines loaded simultaneously. Skipped/killed due to RAM exhaustion. |

### Model Loading & Unloading Lifecycle
* **Startup Preload**: Configured via `ocr.preload: "primary"`. At boot, only the primary engine (default `easyocr`) and primary TTS (`coqui`) are loaded into RAM.
* **Lazy Fallback Loading**: Secondary fallback engines (`paddle`, `trocr`) remain uninitialized in RAM until a frame actually requires fallback. This saves ~600-1,200 MB of RAM during standard operation.
* **Unload Limitation**: In standard Python runtimes, C-extensions (PyTorch, PaddlePaddle, oneDNN) allocate memory through native heaps that are **never returned to the OS** upon Python object deletion. Calling `gc.collect()` clears Python references but leaves native heap allocations mapped in virtual memory. Therefore, once an engine is loaded in-process, its memory is permanently consumed until application restart.

---

## 6. Latency Model

Detailed latency profiling across all pipeline stages:

```
[Camera Acquisition]  ──► [Quality & Change Gating] ──► [Preprocessing] ──► [OCR Inference] ──► [Scoring & Dup] ──► [TTS Synthesis] ──► [Audio Playback]
     10 - 33 ms                   1 - 8 ms                   2 - 10 ms          2.8s - 25s+           < 1 ms             1.0s - 4.5s           2.0s - 5.0s
```

### Component Latency Breakdown
1. **Camera Capture**: 10 to 33 ms (30 FPS capture rate). Rate-limited by `capture_interval = 0.2s` (5 Hz frame ingestion rate).
2. **Quality Assessment**: 1.0 to 8.0 ms (Laplacian variance, contrast standard deviation, mean brightness).
3. **Change Detection**: 0.5 to 2.0 ms (32x32 thumbnail downsampling + MAD computation).
4. **Preprocessing**: 2.0 to 10.0 ms (center cropping, interpolation, grayscale conversion).
5. **OCR Inference (Measured Median per Frame)**:
   * EasyOCR: **2.82 s** (p95: 2.95 s)
   * PaddleOCR: **11.40 s** (p95: 12.52 s)
   * TrOCR (line crops): **1.48 s** (p95: 2.61 s)
   * Tesseract: **~0.5 - 1.5 s** (estimated when binary available)
   * Fallback Mode (EasyOCR success): **2.93 s**
   * Fallback Mode (EasyOCR fails → PaddleOCR runs): **14.85 s to 29.86 s**
   * Ensemble Mode: **> 15 - 25 s** (sum of all serialized engines)
6. **Decision & Scoring Engine**: **< 0.5 ms** (RapidFuzz string comparison, Unicode checks, penalty math).
7. **Duplicate Suppression**: **< 0.2 ms** (LRU dictionary lookup and fuzzy ratio).
8. **Speech Composition**: **< 0.1 ms** (string truncation).
9. **TTS Synthesis**:
   * Coqui VITS: **1.07 s** (Real-Time Factor 0.42 to 0.45; synthesis finishes in less than half the utterance duration).
   * Windows Speech: **4.59 s** (includes PowerShell startup, script parsing, COM initialization).
   * eSpeak NG: **3.60 s** (includes subprocess spawn, synthesis, and audio driver playback).
10. **Audio Playback**: Typically **2.0 to 5.0 s** depending on text length.

### Critical Latency Analysis
The system latency is overwhelmingly dominated by OCR inference (95% to 99% of total processing time). In fallback mode, a 15-25 second latency creates severe temporal dislocation: by the time PaddleOCR finishes reading text, the user has likely panned the camera away from the physical target.

---

## 7. Failure Model

The system enforces strict error isolation across every subsystem:

| Failure State | Root Cause | Code Path / Detection | System Response & User Impact |
|---|---|---|---|
| `NO_TEXT` | Camera pointed at blank wall, empty desk, or uniform surface | `QualityAssessor.assess()` (`no_content`, `too_dark`, `overexposed`) or `OCRDecision.reason = "no_text"` | Pipeline emits `unusable_frame` or `no_text`. System remains completely silent. History unchanged. |
| `LOW_CONFIDENCE` | Blurred, distant, or degraded text read below threshold | `OCRDecision.reason = "below_min_confidence"`; logged in `decision.low_confidence` | Text discarded. Pipeline emits `no_text`. No speech emitted. Prevents hallucinated readings. |
| `ENGINE_UNAVAILABLE` | Third-party binary or dependency missing (e.g. Tesseract on Windows) | `adapter.initialize()` returns `EngineStatus.NOT_AVAILABLE` | Engine skipped during initialization or fallback. Logged as WARNING. If all engines missing -> `no_engine_available`. |
| `MODEL_NOT_AVAILABLE` | Local model weights missing from disk cache | `adapter.initialize()` returns `EngineStatus.MODEL_NOT_AVAILABLE` | Engine marked unavailable. System falls back to next available engine without network downloads. |
| `INFERENCE_FAILED` | Engine crashes internally (e.g. CUDA error, native C++ exception) | Wrapped inside `OCRError(OCRErrorCode.INFERENCE_FAILED)` | Recorded in `decision.errors[engine]`. Logged with traceback. Pipeline tries next fallback engine. |
| `TIMEOUT` | Engine hangs or stalls under memory pressure | `Future.result(timeout=timeout_s)` raises `FuturesTimeout` → `OCRError(OCRErrorCode.TIMEOUT)` | Engine invocation abandoned. Engine marked `BUSY`. Pipeline loop continues processing next frame. |
| `CAMERA_FAILURE` | USB camera disconnected or driver returns `None` | `OpenCVCamera.read()` yields `None` for `>= max_consecutive_read_failures` (30) | `FrameController` closes camera, sets state `reconnecting`, initiates exponential backoff (1s→10s). Reconnects automatically when plugged in. |
| `AUDIO_FAILURE` | Sound card disconnected, PortAudio crash, or TTS synth error | `sd.PortAudioError`, `subprocess.TimeoutExpired`, or `TTSError` | Caught by `AudioManager._worker()`. Increments `audio.stats["failed"]`. Logged as ERROR. Audio worker remains alive; pipeline unaffected. |
| `CONFIG_ERROR` | Invalid JSON, out-of-range thresholds, or bad engine names | `Config.update()` raises `ConfigError` with dictionary of invalid paths | Web API returns HTTP 400 with exact error details. Running pipeline remains on previous valid configuration. |
| `RESOURCE_LIMIT` | System RAM depleted; OS begins heavy paging | Monitored in benchmarks via `psutil`; in app via `serialize_engines` | Engine serialization prevents concurrent memory spikes. Fallback engines remain unloaded unless needed. |

---

## 8. Architectural Strengths

1. **Robust Pipeline Staging (ADR 0002)**: The decoupling of `FrameController`, `QualityAssessor`, `ChangeDetector`, `Preprocessor`, `OCRService`, `DuplicateFilter`, `SpeechComposer`, and `AudioManager` prevents monolithic failures.
2. **Hardware Agnostic Core**: Zero vendor-specific camera or hardware imports in business logic. CSI GStreamer pipelines and USB cameras are cleanly encapsulated behind [`CameraInterface`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/camera/base.py#L11).
3. **Strict Offline First Principle (ADR 0005)**: Enforced via environment variables (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`) and local path validation. The system will never stall waiting on external cloud APIs.
4. **Engine Thread Affinity & Concurrency Safety (ADR 0006)**: Dedicated single-worker ThreadPoolExecutors per engine isolate third-party C++ libraries, completely eliminating PaddleOCR oneDNN memory leaks and native segmentation faults.
5. **Effective TrOCR Hallucination Elimination (ADR 0007)**: Gating TrOCR strictly to detected plausible text regions produced by upstream detectors (EasyOCR/PaddleOCR) completely eliminated whole-scene false positives ("0 2 . 0 0" on clocks and switches) without raising global rejection thresholds.
6. **Command Injection Hardening (ADR 0001)**: Passing TTS text to PowerShell via environment variables (`$env:SVA_TTS_TEXT`) and to eSpeak NG via stdin pipe protects against arbitrary code execution from malicious text observed by the camera.
7. **Graceful Degraded Mode Operation**: Every failure condition (`ENGINE_UNAVAILABLE`, `MODEL_NOT_AVAILABLE`, `TIMEOUT`, `CAMERA_FAILURE`) degrades gracefully without terminating the application process.

---

## 9. Architectural Weaknesses & Gaps

### Critical Priority (System Safety & Stability)
* **[CRIT-1] Fallback Latency Accumulation & Spatial Dislocation**:
  * *Code Ref:* [`core/ocr/service.py:211-217`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L211-L217)
  * *Analysis:* If EasyOCR produces a low-confidence reading, the fallback loop invokes PaddleOCR, taking an additional 11–15 seconds (total frame latency: 15–30s). During this extensive delay, the visually impaired student moves the camera or page. When the result is finally accepted, the system speaks an utterance that no longer corresponds to the student's physical field of view.
* **[CRIT-2] Monolithic Process Memory Exhaustion on 8 GB Hosts**:
  * *Code Ref:* [`core/ocr/service.py:76-81`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/service.py#L76-L81), [`docs/benchmarks/ocr-tts-baseline.md:135-149`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/docs/benchmarks/ocr-tts-baseline.md#L135-L149)
  * *Analysis:* All deep learning models (EasyOCR PyTorch, PaddleOCR, TrOCR Transformers, Coqui VITS) are loaded into a single OS process. In fallback or ensemble modes, co-resident models consume > 2.6 GB RSS, causing OS memory thrashing, latency spikes (up to 67s), or out-of-memory process termination on 8 GB systems. Models cannot be released back to the OS without process termination.

### High Priority (Assistive Reading Quality)
* **[HIGH-1] Semantic Repetition Across Heterogeneous OCR Engines**:
  * *Code Ref:* [`core/text/duplicates.py:55-65`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/text/duplicates.py#L55-L65)
  * *Analysis:* Duplicate detection relies on string equality, normalized punctuation keys, and RapidFuzz ratio >= 90%. When different engines read the same physical page across successive frames (e.g. EasyOCR reads `"We proudly present our prolect..."` vs PaddleOCR reads `"We proudly present our project, designed to deliver..."`), the fuzzy string similarity drops below 90%, causing the system to re-announce the entire paragraph.
* **[HIGH-2] Vulnerability to Stray Nonsensical Fragments**:
  * *Code Ref:* [`core/text/processor.py:72-79`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/text/processor.py#L72-L79)
  * *Analysis:* `TextProcessor.is_valid()` only requires text length >= 3 characters, at least one alphanumeric character, and validity >= 0.6. Stray OCR detector fragments such as `"ned"`, `"jl"`, or `"1st"` pass validation and are read aloud, confusing visually impaired users.
* **[HIGH-3] Stale Audio Queuing During Rapid Visual Shift**:
  * *Code Ref:* [`core/audio/manager.py:72-96`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/audio/manager.py#L72-L96)
  * *Analysis:* In default `audio.policy = "queue"`, if OCR produces an utterance after an 8-second delay, and the user has moved the camera, the utterance sits in the queue and is spoken even if a newer, higher-confidence frame has already been processed. Requests lack a generation/frame ID or invalidation token.

### Medium Priority (Decision Robustness & Resource Management)
* **[MED-1] Isolated Single-Frame Decisions Lacking Temporal Consistency**:
  * *Code Ref:* [`core/pipeline.py:122-175`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/pipeline.py#L122-L175)
  * *Analysis:* Each frame is evaluated in total isolation. There is no multi-frame tracking window or consensus mechanism to verify that recognized text persists across consecutive frames before committing to speech.
* **[MED-2] Uncalibrated Multi-Engine Confidence Scales**:
  * *Code Ref:* [`core/ocr/scoring.py:59-60`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/scoring.py#L59-L60)
  * *Analysis:* Confidence metrics from different engines (EasyOCR character softmax mean, PaddleOCR CTC scores, TrOCR token transition probabilities) are treated as directly comparable 0.0–1.0 values. A 0.60 score in TrOCR represents much higher confidence than a 0.60 in EasyOCR.
* **[MED-3] Absence of Hardware-Specific Deployment Profiles**:
  * *Code Ref:* [`config.json:48-66`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/config.json#L48-L66)
  * *Analysis:* Configuration does not provide standardized profiles (e.g. `LOW_RESOURCE`, `BALANCED`, `ACCURACY_FOCUSED`, `HANDWRITING_ONLY`). Users on Jetson Orin Nano or low-spec laptops must manually edit dozens of JSON parameters.

### Low Priority (Observability & Optimization)
* **[LOW-1] Missing Structured Event Tracing for Frame Diagnostics**:
  * *Code Ref:* [`core/pipeline.py:176-179`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/pipeline.py#L176-L179)
  * *Analysis:* While `test-ocr` logs detailed diagnostics, regular pipeline frames only log `status` at DEBUG level. Investigating why a physical frame was dropped requires manually correlating fragmented log lines without a unified `frame_id`.
* **[LOW-2] Tesseract Lacks Text Region Export**:
  * *Code Ref:* [`core/ocr/tesseract.py:77-78`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/core/ocr/tesseract.py#L77-L78)
  * *Analysis:* Tesseract exports word bounding boxes, but does not format them as line/text regions in `metadata["text_regions"]`, precluding Tesseract from acting as a fast region source for TrOCR.

---

## 10. Recommended Target Architecture

To resolve the architectural weaknesses without discarding working baseline components, the system should evolve toward an **Intelligent Frame-Controlled & Decision-Hardened Architecture**:

```
                              ┌────────────────────────────────┐
                              │         Camera Source          │
                              │    (OpenCV / CSI GStreamer)    │
                              └───────────────┬────────────────┘
                                              │
                                              ▼
                              ┌────────────────────────────────┐
                              │     FrameController v2         │
                              │                                │
                              │  - Optical flow / motion gate  │  Skips frames during rapid panning
                              │  - Adaptive cooldown timer     │  Enforces backpressure while OCR busy
                              │  - Newest-frame-only handoff   │  Never queues stale visual frames
                              │  - Frame generation ID tagging │  Tags frame with monotonic seq & time
                              └───────────────┬────────────────┘
                                              │ Frame + Metadata (ID, Timestamp)
                                              ▼
                              ┌────────────────────────────────┐
                              │   QualityAssessor & Detector   │
                              │                                │
                              │  - Usability gate (blur/dark)  │
                              │  - Thumbnail change gate       │
                              │  - Dual-buffer Preprocessor    │
                              └───────────────┬────────────────┘
                                              │ PreparedFrame
                                              ▼
                              ┌────────────────────────────────┐
                              │     OCR Engine Manager         │
                              │  (Profile-Governed Execution)  │
                              │                                │
                              │  Profiles:                     │
                              │  ├─ LOW_RESOURCE (EasyOCR/Tess)│
                              │  ├─ BALANCED (Easy + Fallback) │
                              │  ├─ HIGH_ACCURACY (Paddle/Ens) │
                              │  └─ HANDWRITING (TrOCR-region) │
                              │                                │
                              │  - Max fallback timeout budget │  Aborts fallback if budget > 6.0s
                              │  - Strict engine serialization │
                              │  - Process isolation option    │  Isolates Paddle/TrOCR in worker procs
                              └───────────────┬────────────────┘
                                              │ Multi-Engine Candidates
                                              ▼
                              ┌────────────────────────────────┐
                              │    Decision & Consensus Engine │
                              │                                │
                              │  - Calibrated confidence norm  │
                              │  - Multi-frame temporal window │  Requires consensus before speech
                              │  - Spatial bbox consistency    │  Checks region overlap
                              │  - Semantic duplicate filter   │  Embeddings / token overlap
                              │  - Dictionary / fragment filter│  Rejects "ned", "jl", stray symbols
                              └───────────────┬────────────────┘
                                              │ Verified Utterance + Frame Tag
                                              ▼
                              ┌────────────────────────────────┐
                              │   SpeechComposer & Audio Mgr   │
                              │                                │
                              │  - Sentence chunking & pacing  │  Natural speech flow for students
                              │  - Stale speech invalidation   │  Cancels speech if frame ID expired
                              │  - Prioritized interruption    │  Urgent corrections interrupt stale
                              │  - Resilient TTS fallback      │  Coqui -> System -> eSpeak
                              └────────────────────────────────┘
```

---

## 11. Migration Strategy

The migration must preserve the **working baseline (all 217 tests green, 0 failures, 0 errors)** while introducing hardening measures:

### Phase 1: Zero-Risk Hardening (Non-Breaking Refinements)
1. **Calibration of Confidence Scores**: Introduce engine-specific confidence calibration curves inside `core/ocr/scoring.py` so EasyOCR, PaddleOCR, and TrOCR scores are mapped onto a uniform Bayesian probability distribution.
2. **Enhanced Fragment & Lexicon Filtering**: Add a lightweight vocabulary/dictionary check to `TextProcessor.is_valid()` to eliminate stray isolated tokens (`"ned"`, `"jl"`) without affecting real names or room codes.
3. **Structured Frame Event Logging**: Add a lightweight `frame_id` counter and structured debug payload to `ProcessOutcome` to provide full lifecycle observability without impacting execution speed.

### Phase 2: Frame Intelligence & Stale Invalidation (COMPLETED — ADR 0008)
1. **Adaptive Motion & Stabilization Gating** (✅ COMPLETED): Enhanced `FrameController` and pipeline with `MotionDetector` (32x32 thumbnail MAD) to bypass OCR when camera is in rapid motion, resuming only after stabilization.
2. **Strict Latency Budgeting** (✅ COMPLETED): Implemented `ocr.latency_budget_s` (default 10.0s). If fallback OCR exceeds budget, remaining engines are aborted and stale winner is invalidated without killing threads.
3. **Monotonic Frame Sequence & Timestamp Propagation** (✅ COMPLETED): Every captured frame carries `frame_seq_id` and `capture_timestamp` through Preprocessor, OCRResult, OCRDecision, ProcessOutcome, and SpeechRequest.
4. **Stale Frame & Audio Queue Invalidation** (✅ COMPLETED): Configured `pipeline.stale_frame` (`max_frame_age_s`, `max_seq_distance`, scene token). `AudioManager` drops stale speech requests and flushes obsolete scene speech upon visual shift.

### Phase 3: Semantic Duplicate Detection & Speech Pacing
1. **Semantic Duplicate Filter**: Augment `DuplicateFilter` with word-level Jaccard similarity and character-level Levenshtein distance across varying text lengths, ensuring that OCR engine variations of the same physical paragraph are recognized as duplicates.
2. **Sentence Chunking & Natural Pacing**: Stream early sentence tokens to TTS while remaining sentences synthesize in background.

### Phase 4: Profiles & Process Isolation for High-End Modes
1. **Configuration Profiles**: Add high-level profiles (`LOW_RESOURCE`, `BALANCED`, `HIGH_ACCURACY`, `HANDWRITING`) to `config.json`.
2. **Process-Isolated Runners for Heavy Engines**: Provide optional out-of-process worker wrappers for PaddleOCR and TrOCR so their memory can be fully reclaimed when not in active use.
