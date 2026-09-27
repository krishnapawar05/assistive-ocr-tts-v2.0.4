# ADR 0008 — Frame Freshness, OCR Latency Budget, Audio Queue Freshness, and Motion Gating

- Status: Accepted
- Date: 2026-09-27

## Context

Smart Vision Assist v2.0.4 provides real-time assistive OCR-to-speech for visually impaired users. In continuous wearable and handheld camera operation, two primary failure modes caused user confusion and disorientation:

1. **Stale Speech from Slow Fallback OCR**: When the primary OCR engine (e.g., EasyOCR) failed or scored below threshold, secondary and tertiary engines (e.g., PaddleOCR, TrOCR) were invoked sequentially. On CPU/edge devices, this multi-engine fallback pipeline could take 4–12+ seconds. Meanwhile, the user moved the camera to a new scene. When the slow fallback OCR completed, the system spoke the obsolete text from the old scene long after the camera had moved away.
2. **Motion-Induced Processing Waste**: During rapid camera movement, pan, tilt, or swing, video frames suffer from heavy motion blur and rapid visual scene shifts. Running expensive deep-learning OCR models on blurred frames repeatedly failed, pegged the CPU at 100%, and delayed capture of stabilized frames once the camera came to rest.
3. **Audio Queue Desynchronization**: Once text was sent to the audio manager, it was queued as raw text without knowledge of when the underlying image was captured or whether the visual scene had changed. If multiple utterances were queued, obsolete descriptions were spoken sequentially even if the visual scene had completely shifted.

Simply lowering OCR thresholds or killing threads with POSIX signals/native cancellation is unacceptable in Python and PaddlePaddle/PyTorch runtimes because killing threads leaves locks held, leaks GPU/CPU memory, and corrupts engine state.

## Decision

We implement a deterministic, lightweight freshness and motion gating architecture spanning frame acquisition, preprocessing, OCR execution, pipeline staging, and audio delivery:

### 1. Frame Identity & Monotonic Sequence Tracking
- `FrameController` tags every frame entering the system with a monotonically increasing integer sequence ID (`frame_seq_id`) and a high-resolution monotonic timestamp (`capture_timestamp`).
- A lightweight wrapper `CapturedFrame` wraps `image`, `frame_seq_id`, `capture_timestamp`, `is_moving`, and `motion_score`, proxying ndarray attributes (`shape`, `dtype`, `ndim`) to preserve backward compatibility.
- Sequence metadata propagates through `PreparedFrame` -> `OCRResult` -> `OCRDecision` -> `ProcessOutcome` -> `SpeechRequest`.

### 2. Motion / Camera-Movement Gating
- A dedicated `MotionDetector` runs during frame capture at `FrameController` or pipeline ingest.
- It computes Mean Absolute Difference (MAD) between consecutive downsampled (32x32) grayscale thumbnails:
  $$\text{MAD} = \frac{1}{N} \sum |T_t - T_{t-1}|$$
- If MAD exceeds `frame.motion_detection.motion_threshold` (default 25.0), the camera is marked as in motion (`is_moving = True`).
- During motion, OCR execution is bypassed, returning `ProcessOutcome("camera_moving")`.
- When MAD drops below the threshold, the camera must remain calm for `stabilization_frames` (default 2) consecutive frames before OCR resumes. This prevents triggering on a single stationary frame during a sweeping motion.
- Discrete synthetic test frames (which lack continuous acquisition context) are supported by checking `is_moving` on `CapturedFrame`.

### 3. OCR Latency Budget
- Configured via `ocr.latency_budget_s` (default 10.0s).
- During multi-engine fallback or ensemble evaluation, `OCRService` monitors elapsed time from the start of the frame pass.
- If elapsed time exceeds `latency_budget_s`, remaining fallback engines are aborted cooperatively without launching further inference.
- If total execution time exceeds `latency_budget_s`, any candidate winner is invalidated (`winner = None`, `reason = "latency_budget_exceeded"`).
- `Pipeline.process_frame` returns `ProcessOutcome("ocr_timeout")` instead of speaking obsolete text.
- Thread pools (`ThreadPoolExecutor`) are never unsafely terminated; running tasks finish cleanly to maintain engine memory and model weight integrity.

### 4. Pipeline Stale-Frame Invalidation
- Configured via `pipeline.stale_frame`:
  - `max_frame_age_s` (default 5.0s): Maximum allowed age between frame capture and speech submission.
  - `max_seq_distance` (default 15 frames): Maximum sequence distance between frame sequence ID and `controller.frames_delivered`.
  - Scene generation token (`scene_token`): Incremented whenever the camera moves or a scene change is detected.
- If a frame completes OCR but exceeds the age or sequence limit, or if the scene token changed during OCR processing, the result is dropped before speech submission, returning `ProcessOutcome("stale_frame")`.

### 5. Audio Stale-Result Protection
- `SpeechRequest` tracks `frame_seq_id`, `capture_timestamp`, and `scene_token`.
- `AudioManager._worker` inspects the request immediately before dispatching to the TTS engine:
  - If `source == "ocr"` and `now - req.capture_timestamp > max_frame_age_s`, the utterance is discarded and `stats["dropped_stale"]` is incremented.
  - If `pipeline.invalidate_scene(token)` is triggered (e.g., due to camera movement or user interaction), all queued OCR speech with obsolete scene tokens is purged from the queue.
  - API speech requests (`source == "api"`) are preserved so user notifications and system alerts are never dropped.

## Consequences

### Positive
- **Zero Obsolete Speech**: Visually impaired users will never hear text from an old scene after pointing the camera somewhere new.
- **Resource Savings**: CPU is not pegged with expensive OCR inference while the user is rapidly panning or walking.
- **Graceful Timeout**: Slow engines do not stall the user experience; timeouts produce deterministic telemetry (`ocr_timeout`, `stale_frame`, `camera_moving`).
- **Clean Concurrency**: No unsafe thread cancellation. PaddleOCR thread affinity (ADR 0006) and TrOCR region gating (ADR 0007) are fully preserved.

### Negative / Trade-offs
- In low-frame-rate or high-latency camera setups, aggressive `max_frame_age_s` or `motion_threshold` values could reject valid frames if misconfigured. Conservative defaults (`motion_threshold: 25.0`, `latency_budget_s: 10.0`, `max_frame_age_s: 5.0`) ensure stable operation across typical hardware.
