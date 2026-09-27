# Smart Vision Assist — Next Engineering Phase Roadmap

> **Target System:** Smart Vision Assist (v2.0.4 Baseline Hardening & Evolution)  
> **Mission:** Assistive OCR-to-Speech system for visually impaired students in real classroom environments.  
> **Core Operating Principle:**  
> Safety of output → Correctness → Predictability → Latency → Resource efficiency → Maintainability.  
> Never trade real-world reliability for synthetic benchmark vanity metrics.

---

## Roadmap Executive Summary

The transition from Milestone A (baseline stabilization) to real-world classroom deployment is organized into six disciplined phases (A through F). Each phase is governed by clear entry criteria, specific engineering tasks, quantitative validation gates, and risk mitigations.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE A — VALIDATION CLOSURE                             │
│  Close validation gaps: real-camera handwriting, repeated lifecycle,       │
│  continuous camera reconnect recovery, 30-min soak test.                    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE B — FRAME INTELLIGENCE                             │
│  Process the most useful frame, not every frame: motion detection, adaptive │
│  cooldown, OCR backpressure, newest-frame prioritization.                   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE C — DECISION QUALITY                               │
│  Multi-engine confidence calibration, temporal consensus window,            │
│  semantic duplicate suppression across engines, stray fragment rejection.   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE D — SPEECH RELIABILITY                             │
│  Speech cancellation on visual shift, frame-tagged invalidation, sentence    │
│  chunking/pacing, robust audio device failure recovery.                     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE E — RESOURCE-AWARE DEPLOYMENT                      │
│  Standardized profiles (LOW_RESOURCE, BALANCED, HIGH_ACCURACY), engine      │
│  process isolation, Jetson Orin Nano hardware optimization (NPU/GPU).       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE F — REAL-WORLD VALIDATION                          │
│  Classroom verification: boards, textbooks, notes, cursive handwriting,     │
│  distance, angled perspective, dynamic lighting, motion jitter.             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase A — Validation Closure

### Objective
Resolve remaining validation ambiguities in the working baseline without modifying core functionality. Address scenarios where unit tests pass on synthetic fixtures but real hardware behavior remains unmeasured.

### Detailed Engineering Tasks
1. **A.1 Real-Camera Handwriting Verification Protocol**:
   * *Problem:* Real-camera handwriting was explicitly skipped in previous runs. TrOCR region gating has only been validated against rendered synthetic fixtures (`hand_meet`, `hand_notes`).
   * *Implementation:* Build an interactive CLI / test harness `tests/validation/validate_real_camera_handwriting.py`. Test live handwritten notebook pages under EasyOCR/PaddleOCR region detection + TrOCR reading.
   * *Acceptance Criteria:* TrOCR receives valid line bounding boxes from camera captures of handwritten notes; CER <= 0.25 on legible handwriting; non-text artifacts produce zero hallucinations.
2. **A.2 Rapid Lifecycle & Start/Stop Stress Testing**:
   * *Problem:* Rapid toggling of `/api/start` and `/api/stop` could cause race conditions in thread joins or camera handle releases.
   * *Implementation:* Add test `tests/integration/test_rapid_lifecycle.py` executing 50 consecutive start/stop cycles with varying intervals (10ms to 500ms).
   * *Acceptance Criteria:* Zero thread leakage (`threads_alive()` empty), camera handle cleanly reacquired on every cycle, no deadlock, RSS remains flat.
3. **A.3 Continuous Stream Camera Disconnection & Hot-Plug Recovery**:
   * *Problem:* Real-world USB camera cables can be bumped or unplugged during class.
   * *Implementation:* Validate continuous streaming recovery in `tests/integration/test_camera_stream_recovery.py` simulating physical disconnection mid-stream and re-attachment after 15 seconds.
   * *Acceptance Criteria:* `FrameController` cleanly transitions `streaming -> reconnecting -> streaming`; no frame corruption; pipeline resumes reading within 1.0s of reconnect.
4. **A.4 Extended 30-Minute Soak & Memory Stability Test**:
   * *Problem:* Memory leaks in long-running PyTorch or PaddlePaddle sessions can exhaust RAM over a 45-minute lecture.
   * *Implementation:* Run `scripts/soak_test.py` for 30 minutes feeding mixed video frames (no-text scenes, text appearing, text disappearing, page turns, dark frames).
   * *Acceptance Criteria:* Peak RSS growth <= 50 MB over 30 minutes; zero unhandled exceptions; no audio queue backlog.

---

## Phase B — Frame Intelligence & Flow Control (IMPLEMENTED — ADR 0008)

### Objective
Shift from naive frame ingestion to intelligent, perception-driven frame control: **Process the most useful frame, not every frame.**

### Detailed Engineering Tasks
1. **B.1 Motion Detection & Jitter Suppression** (✅ COMPLETED):
   * *Problem:* When a student moves the camera across a desk or classroom, frames are severely motion-blurred. Feeding these blurred frames to OCR wastes 3 to 15 seconds of CPU time and produces garbage fragments.
   * *Implementation:* Added `MotionDetector` in `core/frame/processing.py` using fast downsampled (32x32) thumbnail Mean Absolute Difference (MAD) between consecutive frames.
   * *Mechanism:* When thumbnail MAD >= `motion_threshold` (default 25.0), the frame is tagged `is_moving=True` and OCR is bypassed (`ProcessOutcome("camera_moving")`). Once MAD drops below threshold, the camera must remain calm for `stabilization_frames` (default 2) consecutive frames before OCR resumes.
2. **B.2 Adaptive OCR Latency Budgeting & Fallback Flow Control** (✅ COMPLETED):
   * *Problem:* If primary OCR fails and fallback takes 4–12+ seconds, obsolete results are spoken long after the camera moved.
   * *Implementation:* Added `ocr.latency_budget_s` (default 10.0s). In `OCRService.recognize()`, if elapsed time exceeds the budget during fallback, remaining engines are aborted. If total duration exceeds budget, the candidate winner is invalidated (`reason = "latency_budget_exceeded"`), producing `ProcessOutcome("ocr_timeout")` without killing engine threads unsafely.
3. **B.3 Dynamic Scene-Change Gate Tuning**:
   * *Problem:* `ChangeDetector` uses fixed thumbnail MAD threshold (2.0) and fixed `max_skip_s` (10s).
   * *Implementation:* Make threshold adaptive to ambient lighting. If a scene is static, extend skip timeout up to 30s unless deliberate motion is detected.
4. **B.4 Frame Sequence Tagging & Age Validation** (✅ COMPLETED):
   * *Problem:* Frames lacked explicit generation sequence IDs and acquisition timestamps.
   * *Implementation:* Wrapped frames in `CapturedFrame(image, seq_id, timestamp, is_moving, motion_score)`. Sequence metadata propagates through `PreparedFrame` -> `OCRResult` -> `OCRDecision` -> `ProcessOutcome` -> `SpeechRequest`. Added `pipeline.stale_frame` policy (`max_frame_age_s`, `max_seq_distance`, scene token).
5. **D.1 Frame-Tagged Speech Invalidation & Scene Shifting** (✅ COMPLETED):
   * *Problem:* Stale utterances queued while OCR was running were spoken even if the user panned the camera away.
   * *Implementation:* Tagged `SpeechRequest` with `frame_seq_id`, `capture_timestamp`, and `scene_token`. In `AudioManager._worker()`, before dispatching to TTS, requests exceeding `max_frame_age_s` are discarded. `invalidate_scene()` purges obsolete queued OCR utterances upon visual scene changes while preserving `source="api"` speech. Verified in `tests/unit/test_freshness_and_motion.py`.

---

## Phase C — Decision Quality & Multi-Engine Fusion

### Objective
Eliminate false speech, eliminate semantic duplicate repetition across different OCR engines, and reject meaningless short text fragments.

### Detailed Engineering Tasks
1. **C.1 Multi-Engine Confidence Calibration**:
   * *Problem:* EasyOCR softmax confidences, PaddleOCR CTC scores, and TrOCR token probabilities have completely different statistical distributions. Treating them as identical 0.0–1.0 values distorts scoring.
   * *Implementation:* Create `core/ocr/calibration.py` implementing isotonic calibration curves per engine derived from validation corpora. Map raw engine confidences to true calibrated empirical probabilities $P(\text{correct} | \text{score})$.
2. **C.2 Semantic Duplicate Detection Across Varying Engine Outputs**:
   * *Problem:* Exact/fuzzy duplicate filters fail when EasyOCR and PaddleOCR produce slightly different readings of the same physical paragraph (e.g. `"prolect"` vs `"project"`).
   * *Implementation:* Upgrade `DuplicateFilter` in `core/text/duplicates.py` with multi-tier matching:
     - Tier 1: Alphanumeric key identity (exact).
     - Tier 2: Number sequence identity (strict regex `\d+`).
     - Tier 3: Token-level Jaccard similarity and character-level Levenshtein ratio across sliding windows. If Jaccard token overlap > 80% and digit sequences match, classify as duplicate.
3. **C.3 Robust Stray Fragment & Garbage Rejection**:
   * *Problem:* Stray 3-letter fragments (`"ned"`, `"jl"`, `"1st"`) pass `is_valid()` and are read aloud.
   * *Implementation:* Implement a fast local dictionary / n-gram frequency lookup in `TextProcessor`. For short words (< 5 characters) that are not recognized numbers or common abbreviations, require higher confidence (e.g. >= 0.85) or require corroboration across multiple words.
4. **C.4 Multi-Frame Temporal Consensus**:
   * *Problem:* Single-frame decisions are sensitive to momentary optical glares or shadows.
   * *Implementation:* Add `TemporalConsensusBuffer` in `core/ocr/consensus.py`. Require candidate text from moving scenes to be detected across at least 2 consecutive processed frames before triggering speech.

---

## Phase D — Speech Reliability & Audio Management

### Objective
Ensure speech is timely, natural, interruptible, and never temporally dislocated from what the user is currently looking at.

### Detailed Engineering Tasks
1. **D.1 Frame-Tagged Speech Invalidation**:
   * *Problem:* Stale utterances queued while OCR was running are spoken even if the user panned the camera away.
   * *Implementation:* Tag `SpeechRequest` with `frame_id` and `timestamp`. In `AudioManager._worker()`, before synthesizing or playing, verify with `FrameController`: has the camera scene shifted significantly since `timestamp`? If yes, drop utterance as `stale_scene_shifted`.
2. **D.2 Intelligent Priority & Speech Cancellation**:
   * *Problem:* In default `queue` policy, speech can pile up.
   * *Implementation:* Establish priority levels:
     - `PRIORITY_URGENT`: System alerts (e.g., camera disconnected). Always interrupts immediately.
     - `PRIORITY_NEW_TEXT`: Fresh classroom text. Interrupts previous repetitive reading if semantic shift detected.
     - `PRIORITY_NORMAL`: Standard reading queue.
3. **D.3 Natural Sentence Chunking & Pacing**:
   * *Problem:* Long paragraphs (up to 300 chars) are synthesized as monolithic blocks, leading to robotic cadence and delayed first-word speech.
   * *Implementation:* Add sentence boundary splitting in `SpeechComposer` (splitting on `.`, `!`, `?`, `;`). Synthesize and stream the first sentence immediately while subsequent sentences synthesize in the background.
4. **D.4 Non-Blocking TTS Device Recovery**:
   * *Problem:* Audio device disconnection (e.g. Bluetooth earphones running out of battery) must never block OCR or cause process lockups.
   * *Implementation:* Enhance `AudioManager` with async audio device polling. If PortAudio fails, seamlessly switch to fallback TTS or mute without dropping pipeline frames.

---

## Phase E — Resource-Aware Deployment & Jetson Optimization

### Objective
Enable stable operation across divergent hardware profiles: low-memory laptops (8 GB RAM) and edge hardware (Jetson Orin Nano).

### Detailed Engineering Tasks
1. **E.1 Standardized Configuration Profiles**:
   * *Problem:* Monolithic configuration requires manual tweaking of dozens of parameters.
   * *Implementation:* Add profile templates into `core/config.py`:
     * `LOW_RESOURCE`: EasyOCR or Tesseract single-engine; eSpeak NG; lightweight change detection. Peak RAM < 1.0 GB. Target: Low-end PCs / 4 GB Jetson.
     * `BALANCED` (Default): EasyOCR primary with PaddleOCR lazy fallback; Coqui VITS speech. Peak RAM ~ 1.8 GB. Target: 8 GB PCs.
     * `HIGH_ACCURACY`: PaddleOCR det+rec; Coqui VITS speech; ensemble evaluation. Target: High-end workstations.
     * `HANDWRITING`: EasyOCR region localizer + TrOCR handwritten model. Target: Notebook reading.
2. **E.2 Out-of-Process Engine Isolation**:
   * *Problem:* Once loaded in-process, PyTorch and PaddleOCR memory cannot be returned to the OS.
   * *Implementation:* Build an optional `ProcessIsolatedAdapter` running heavy engines in a reusable child process. When switching profiles or during idle periods, terminating the child process immediately reclaims 1.5 GB of RAM to the OS.
3. **E.3 Jetson Orin Nano Hardware Acceleration**:
   * *Problem:* Running deep learning models on Jetson CPU causes 10x latency slowdown.
   * *Implementation:* Add Jetson-specific adapter optimizations:
     - Export EasyOCR / PaddleOCR detection models to ONNX / TensorRT FP16 engines.
     - Configure PyTorch to utilize Tegra unified memory without redundant CPU-GPU copies.
     - Utilize CSI hardware ISP via Jetson GStreamer pipeline `nvarguscamerasrc`.

---

## Phase F — Real-World Classroom Validation

### Objective
Systematic empirical validation under genuine assistive educational scenarios with real visually impaired students.

### Test Scenarios & Protocols
| Scenario ID | Test Environment | Target Input | Primary Stress Factors | Success Metrics |
|---|---|---|---|---|
| **SCEN-01** | Classroom Board | Whiteboard with dry-erase marker (printed text + diagrams) | Distance (2m to 5m), glare from classroom lights, perspective angle | CER <= 0.15; zero diagram hallucination; latency <= 4.0s |
| **SCEN-02** | Classroom Chalkboard | Greenboard with white/colored chalk | Chalk dust, low contrast, smudged characters | CER <= 0.20; greenboard contrast handled correctly |
| **SCEN-03** | Standard Textbook | Printed textbook (glossy paper, multi-column layout) | Page curvature, hand shadows, column reading order | Clean single-column speech flow; zero column interleaving |
| **SCEN-04** | Student Notes | Ruled notebook paper with handwritten blue/black ink | Ruled lines, varying handwriting legibility, cursive style | CER <= 0.25 on legible handwriting; TrOCR line gating stable |
| **SCEN-05** | Mixed Board | Whiteboard containing both printed headings and handwritten notes | Dual script types in single frame | Correct engine selection between printed and handwritten models |
| **SCEN-06** | Dynamic Motion | Student holding wearable/camera turning head across room | Rapid panning, momentary blur, complex background clutter | Zero speech during motion; clean reading within 1.5s of head stop |
| **SCEN-07** | Ambient Lighting | Classroom with sunlight streaming through blinds | High dynamic range, direct sunlight streaks, deep shadows | QualityAssessor does not falsely reject readable regions |
| **SCEN-08** | Repeated Page | Student keeping textbook open on same page for 10 minutes | Extended viewing without moving page | Spoken exactly once; zero repeated speech during the entire 10 minutes |

---

## Architectural Decision Records (ADRs) to Create

1. **ADR 0008: Motion-Gated Frame Control and Backpressure**:
   * Document decision to gate OCR inference on camera motion stability and implement adaptive frame backpressure.
2. **ADR 0009: Calibrated Multi-Engine Confidence and Semantic Deduplication**:
   * Document decision to replace raw engine confidence comparison with calibrated probabilities and introduce token-level semantic duplicate filtering.
3. **ADR 0010: Frame-Tagged Speech Cancellation and Invalidation**:
   * Document decision to link speech requests to visual frame generation sequences and cancel speech upon rapid visual orientation shifts.
4. **ADR 0011: Deployment Profiles and Process-Isolated Model Runners**:
   * Document decision to establish named profiles (`LOW_RESOURCE`, `BALANCED`, `HIGH_ACCURACY`, `HANDWRITING`) and out-of-process engine lifecycle management.

---

## Success Criteria & Definition of Done

Milestone B will be considered complete and validated when:
1. All 217 existing baseline tests continue to pass without regression.
2. Real-camera handwriting is empirically proven on live camera streams with CER <= 0.25.
3. Rapid camera motion produces 0% hallucinated speech and triggers 0 expensive OCR inferences.
4. Semantic repetition across differing OCR engines is reduced to < 2% of frames.
5. Peak RSS memory stays strictly bounded within configured profile limits.
6. A 30-minute continuous classroom simulation completes with zero unhandled exceptions, zero thread leaks, and zero memory growth.
