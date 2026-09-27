# Dead File Audit — Smart Vision Assist v2.0.4

**Date:** 2026-09-27  
**Scope:** Repository-wide audit of source, scripts, test files, assets, and documentation.  
**Objective:** Identify, verify, and safely clean up dead, redundant, or obsolete files without breaking the verified OCR/TTS system.

---

## 1. Audit Summary Table

| File | Status | Evidence / Reference Check | Action |
| :--- | :--- | :--- | :--- |
| `app.py` | Active | Primary FastAPI application entry point, serves API and dashboard | Keep |
| `config.json` | Active | Active runtime configuration file loaded by `app.py` and test suite | Keep |
| `config.example.json` | Active | Reference configuration template documented in README | Keep |
| `requirements.txt` | Active | Python package dependencies for `.venv` | Keep |
| `CLAUDE.md` | Active | Project operating instructions and engineering principles | Keep |
| `README.md` | Active | Primary user and developer documentation | Keep |
| `.gitignore` | Active | Git ignore rules for virtualenvs, caches, artifacts, outputs | Keep |
| `.gitattributes` | Active | Line-ending normalization rules | Keep |
| `verify_ocr_dependencies.py` | Active | Standalone health-check utility for PaddleOCR and Transformers | Keep |
| `install_ocr_dependencies.bat` | Active | Windows automated setup helper for PaddleOCR / TrOCR | Keep |
| `install_ocr_dependencies.sh` | Active | Linux automated setup helper for PaddleOCR / TrOCR | Keep |
| `fix_dependencies.ps1` | Active | Windows dependency troubleshooting script for numpy / TTS | Keep |
| `fix_dependencies.sh` | Active | Linux dependency troubleshooting script for numpy / TTS | Keep |
| `scripts/run_tests.py` | Active | Core isolated-process regression runner with memory guard | Keep |
| `scripts/generate_ocr_fixtures.py` | Active | Generates synthetic OCR test images in `tests/fixtures/` | Keep |
| `test_camera.py` | Redundant / Consolidated | Consolidated in previous phases into `tests/integration/test_app_api.py` and `tests/unit/test_freshness_and_motion.py`. Not present in git tree. | Verified absent |
| `test_ocr.py` | Redundant / Consolidated | Consolidated in previous phases into `tests/ocr/` suite. Not present in git tree. | Verified absent |
| `test_live_ocr.py` | Redundant / Consolidated | Consolidated in previous phases into `tests/integration/test_ocr_pipeline.py`. Not present in git tree. | Verified absent |
| `yolov8n.pt` | Redundant / Obsolete | 6.5 MB YOLO weights in root. Ultralytics is not installed; `use_yolo` is in `_DEAD_OCR_KEYS` (`core/config.py`); YOLO is deferred in roadmap. | Delete |
| `static/dashboard.js` | Active | Frontend logic, polling, API interaction, pure test formatter | Keep (refine) |
| `static/style.css` | Active | Frontend styling, high contrast, typography, layout | Keep (refine) |
| `templates/base.html` | Active | Base layout template with accessibility toggles | Keep (refine) |
| `templates/dashboard.html` | Active | Main dashboard template with student UI & collapsible diagnostics | Keep (refine) |
| `core/*` (all 36 modules) | Active | Production pipeline, camera, frame, OCR, TTS, audio, text components | Keep |
| `tests/*` (all 21 test files + helpers) | Active | Complete regression and benchmark suite (228 tests + 4 UI accessibility tests) | Keep |
| `tests/fixtures/*` (all 16 images + manifest) | Active | Real and synthetic image test fixtures required by test suite | Keep |
| `scripts/validate_real_world.py` | Active | Empirical live webcam, OCR, handwriting, and audio benchmark runner | Keep |
| `docs/*` (all ADRs, architecture, baselines, validation) | Active | Architectural decision records, deployment plans, and validation evidence | Keep |

---

## 2. Detailed Findings & Actions

### 2.1 Legacy Root Tests (`test_camera.py`, `test_ocr.py`, `test_live_ocr.py`)
- **Inspection:** Checked `git ls-files` and file system. None of these files exist in the repository root.
- **Verification:** Their functionality has been fully absorbed by `tests/integration/test_app_api.py`, `tests/ocr/`, and `tests/unit/test_freshness_and_motion.py`.
- **Action:** No action needed; confirmed already removed and consolidated.

### 2.2 Prototype YOLO Model (`yolov8n.pt`)
- **Inspection:** A 6.5 MB file located directly in the workspace root.
- **Reference Check:**
  - `grep` across entire codebase found occurrences only in `docs/baseline/dependency-matrix.md` (which explicitly states: `"yolov8n.pt present but unused | Deferred to object-awareness milestone"`), `core/config.py` (`"use_yolo"` in `_DEAD_OCR_KEYS`), and `CLAUDE.md` (`"Do not start YOLO, context, priority, or transport work until it is signed off."`).
  - No Python module imports `ultralytics` or opens `yolov8n.pt`.
- **Risk Assessment:** Zero risk to OCR/TTS pipeline, zero risk to test suite.
- **Action:** Removed from workspace and git tracking.

### 2.3 Setup & Diagnostic Utilities
- `install_ocr_dependencies.*` and `fix_dependencies.*` serve as setup assistance for engineers deploying the system on fresh Windows or Linux environments.
- `verify_ocr_dependencies.py` is a convenient non-pytest smoke test for model libraries.
- **Action:** Retained.

### 2.4 Test Suite & Fixtures
- All files in `tests/` are actively executed by `scripts/run_tests.py` or used as benchmarks/fixtures.
- None are dead or candidates for deletion.
