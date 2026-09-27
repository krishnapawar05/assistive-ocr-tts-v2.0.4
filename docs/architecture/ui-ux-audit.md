# UI/UX & Accessibility Audit — Smart Vision Assist v2.0.4

**Date:** 2026-09-27  
**Status:** Audit & Implementation Plan  
**Target:** Assistive OCR-to-Speech System for Visually Impaired Students  

---

## 1. Executive Summary

Smart Vision Assist v2.0.4 has a thoroughly verified, hardened OCR and TTS backend (228 total tests, 216 passed, 0 failed, 0 errors, 12 skipped). The system successfully integrates EasyOCR, PaddleOCR, TrOCR, Coqui TTS, Windows Speech, and eSpeak with robust camera lifecycle management, motion gating, stale-frame rejection, and duplicate speech suppression.

However, the existing web frontend was designed as a developer/engineering dashboard rather than an assistive tool for visually impaired students. It presents dense parameter sliders, engine selectors, and raw technical metrics directly on the main screen, lacks dedicated screen-reader transition announcements, lacks essential keyboard shortcuts (`Space`, `R`, `Esc`), and has no mechanism to halt speech without shutting down the entire camera pipeline.

This audit details the current UI structure, interaction flow, accessibility shortcomings, candidate dead files, and the proposed audio-first, accessible interface design that preserves all developer diagnostics and test compatibility.

---

## 2. Current UI Structure & User Flow

### 2.1 File Map
- **Templates:**
  - `templates/base.html`: Bootstrap 5.3.2 shell with navbar containing dummy anchor tags (`#dashboard`, `#ocr`, `#tts`, `#camera`, `#settings`) and basic `#contrastToggle`, `#increaseFont` buttons.
  - `templates/dashboard.html`: 2-column layout. Left column holds Camera Viewfinder (`#cameraPreview`, `#targetOverlay`), Live OCR Output card (`#ocrOutput`, Start/Stop/Replay/Test Camera/Test OCR buttons), and Text History card. Right column holds 3 configuration forms (OCR settings, TTS settings, Camera settings) with 5 range sliders.
- **Static Assets:**
  - `static/style.css`: Purple-blue gradient background, glowing green-on-black monospace OCR terminal box, badge pulse animations, custom range styling.
  - `static/dashboard.js`: Polling loop (1s for status, 3s for history), form submission handlers, snapshot refresher, and `Dashboard.formatOcrTest(data)` pure rendering method.
- **Backend API Endpoints (`app.py`):**
  - `GET /` — Serves dashboard HTML with pre-filled config and engine status.
  - `POST /api/start` — Starts capture controller and processing thread.
  - `POST /api/stop` — Stops capture controller, processing thread, and clears audio.
  - `GET /api/status` — Returns pipeline state, motion, OCR/TTS engine status, audio statistics.
  - `GET /api/history` — Returns recognized text history log.
  - `GET /api/config` / `POST /api/config` — Reads/updates runtime configuration with atomic pipeline reload.
  - `POST /api/speak` — Queues explicit text to TTS.
  - `GET /api/replay` — Returns latest synthesized WAV audio (Coqui).
  - `GET /api/camera/snapshot` — Returns latest JPEG frame thumbnail.
  - `GET /api/test-camera` — Verifies camera frame acquisition.
  - `GET /api/test-ocr` — Runs single-frame OCR test with detailed diagnostics.

### 2.2 Current Student Flow & Friction
1. **Starting the System:** A blind student must navigate past navigation links, past the viewfinder card, and through a row of 5 similarly styled buttons to locate "▶️ Start".
2. **Camera Alignment:** The viewfinder has visual overlays ("Align text within this box"), but provides no auditory or screen-reader guidance when the camera is moving or text is out of frame.
3. **Reading Output:** `#ocrOutput` has `aria-live="polite"`, but it repeats "Waiting for OCR output..." or raw text without clear transition context.
4. **Speech Interruption:** If TTS begins reading lengthy text, the student has no "Stop Speech" button. The only option is "Stop", which tears down the camera stream and shuts down the pipeline.
5. **Replay:** Clicking "Replay Audio" calls `/api/replay`. If the active TTS engine is Windows Speech or eSpeak (which don't output WAV blobs to `/api/replay`), the student receives a warning alert rather than hearing the text re-spoken.

---

## 3. Accessibility & Usability Deficiencies

| Category | Issue | Impact on Visually Impaired / Low-Vision Students |
| :--- | :--- | :--- |
| **Keyboard Navigation** | No global shortcut keys (`Space`, `R`, `Esc`). | Students are forced to tab through 20+ controls to execute simple actions. |
| **Screen Reader Behavior** | No dedicated live announcement channel for state transitions. | Frame updates either flood screen readers or leave the user unaware of camera movement or readiness. |
| **Speech Control** | No dedicated "Stop Speech" (silence) control. | Inability to silence audio without stopping the camera. |
| **Visual Hierarchy** | Cluttered with complex settings (Capture Interval, Min Confidence, Engine Mode). | Severe cognitive overload for low-vision students and assistive teachers. |
| **Contrast & Motion** | Low-contrast `.text-muted` subtext; continuous `@keyframes pulse` animation without `@media (prefers-reduced-motion)`. | Eye strain, vestibular discomfort, WCAG 2.1 AA failure. |
| **Touch / Click Targets** | Control buttons are grouped tightly in a horizontal flex layout with minimal padding. | Accidental presses; difficult targeting on touch laptops or tablets. |
| **Error Handling** | Technical messages (e.g. "cannot open camera source 0") exposed in user alerts. | Confusing error UX; causes student anxiety. |

---

## 4. UI Elements Audit: Essential vs. Redundant

### 4.1 Primary (Student-Facing) — Must Be Prominent
- **System Status Badge:** Plain language (`Ready`, `Running`, `Paused`, `Error`).
- **Camera State Indicator:** Clearly communicates stability (`Ready`, `Moving — hold steady`, `Disconnected`).
- **Speech State Indicator:** (`Silent`, `Speaking`, `Paused`).
- **Primary Action Buttons:**
  - `[Start / Pause] (Space)` — Large primary toggle.
  - `[Replay Text] (R)` — Re-reads the latest recognized text.
  - `[Stop Speech] (Esc)` — Silences active TTS and clears pending audio queue.
- **High-Contrast Text Display:** Large, readable typography displaying recognized text with semantic labels.
- **Camera Viewfinder:** Clean preview for sighted teachers/assistants with high-contrast text framing guide.
- **High Contrast & Large Font Toggles:** Quick access in header.

### 4.2 Secondary (Diagnostics & Teacher Settings) — Moved to Collapsible Section
- **Engine Selection & Mode Forms:** OCR engine, mode, language, capture interval, min confidence, min text len.
- **TTS Configuration Forms:** Voice selector, speed, volume.
- **Camera Configuration Forms:** Source, camera ID, resolution.
- **Hardware & OCR Test Tools:** `Test Camera` and `Test OCR` buttons with diagnostic outputs.
- **Text History Log:** Chronological list of recognized snippets.

*Note: All form inputs and element IDs (`ocrMode`, `ocrEngine`, `minConfidence`, etc.) MUST be preserved to ensure zero regressions in API tests (`test_app_api.py`) and config persistence.*

---

## 5. Candidate Files Audit (Phase 0 Review)

| File / Artifact | Category | Status & Evidence | Recommendation |
| :--- | :--- | :--- | :--- |
| `test_camera.py` | Legacy Test | Not present in repo (previously consolidated into `test_app_api.py` / `test_freshness_and_motion.py`). | Verified removed. |
| `test_ocr.py` | Legacy Test | Not present in repo (previously consolidated into `tests/ocr/`). | Verified removed. |
| `test_live_ocr.py` | Legacy Test | Not present in repo (previously consolidated into `tests/integration/`). | Verified removed. |
| `yolov8n.pt` | Prototype Model | 6.5 MB YOLO weights in root. Ultralytics is not installed; `use_yolo` is in `_DEAD_OCR_KEYS` (`core/config.py`); YOLO is deferred in roadmap. | Candidate for removal from tracked repo. |
| `fix_dependencies.ps1` | Setup Script | Hardcodes global Python 3.10 paths outside `.venv`. Repo operates in `.venv` with verified dependencies. | Keep as legacy utility or archive. |
| `fix_dependencies.sh` | Setup Script | Shell script for unix dependency fix. | Keep for Linux environments. |
| `install_ocr_dependencies.bat` | Setup Script | Batch script installing paddleocr / transformers. | Keep for initial setup automation. |
| `install_ocr_dependencies.sh` | Setup Script | Shell script installing paddleocr / transformers. | Keep for initial setup automation. |
| `verify_ocr_dependencies.py` | Diagnostic | Standalone verification script for paddle and transformers. | Keep as lightweight diagnostic utility. |
| `tests/benchmarks/output/*` | Benchmark Output | Git-ignored test logs and json outputs. | Retained locally, excluded from git. |

---

## 6. Proposed Redesign & Accessibility Architecture

### 6.1 Semantic Layout
```html
<header role="banner">
  <!-- Brand, Accessibility Toggles (High Contrast, Large Text), Audio Status Indicator -->
</header>

<main id="mainContent" role="main">
  <!-- STUDENT SECTION (Default View) -->
  <section id="statusPanel" aria-labelledby="statusHeading">
    <!-- System Status, Camera Status, Speech Status -->
  </section>

  <section id="controlsPanel" aria-labelledby="controlsHeading">
    <!-- Primary Buttons: Start/Pause (Space), Replay (R), Stop Speech (Esc) -->
  </section>

  <section id="textPanel" aria-labelledby="textHeading">
    <!-- Big readable recognized text container -->
  </section>

  <section id="cameraPanel" aria-labelledby="cameraHeading">
    <!-- Viewfinder with framing guide and accessible text description -->
  </section>

  <!-- SCREEN READER LIVE REGION (Polite, Deduped) -->
  <div id="srLiveAnnouncements" class="visually-hidden" aria-live="polite" aria-atomic="true"></div>

  <!-- DIAGNOSTICS & SETTINGS SECTION (Collapsible for Teachers/Devs) -->
  <details id="diagnosticsSection">
    <summary>⚙️ Diagnostics & Teacher Settings</summary>
    <!-- Test buttons, Engine status, Configuration forms, Text History -->
  </details>
</main>
```

### 6.2 Keyboard Shortcuts Map
- `Space`: Toggle Start / Pause (Pipeline capture & OCR).
- `KeyR` / `r`: Replay latest recognized text.
- `Escape`: Stop speech immediately and clear pending audio.
- **Safety Rule:** Ignore shortcuts when `event.target.matches('input, select, textarea')`.

### 6.3 Screen Reader Announcement Policy
- Only announce meaningful state changes:
  - System transition: "System started. Camera active." / "System paused."
  - Camera motion: "Camera moving. Hold steady." / "Camera steady."
  - Text recognition: "New text recognized: [Text excerpt]"
  - Speech events: "Speaking text." / "Speech stopped."
- Never announce periodic frame ticks or unchanged values.

---

## 7. Next Implementation Steps
1. Create `docs/architecture/dead-file-audit.md`.
2. Add backend endpoint `POST /api/stop-speech` in `app.py` and `AssistivePipeline.stop_speech()`.
3. Update `templates/base.html` and `templates/dashboard.html` with clean semantic HTML, accessible landmarks, and collapsible diagnostics.
4. Refactor `static/style.css` for high contrast, WCAG 2.1 AA compliance, large touch targets, and `prefers-reduced-motion`.
5. Update `static/dashboard.js` with keyboard shortcuts, state transition announcer, speech stopping, and audio fallback replay.
6. Verify all integration tests and regression suite pass.
