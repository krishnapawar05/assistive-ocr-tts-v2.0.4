# CLAUDE.md — Smart Vision Assist (from assistive-ocr-tts v2.0.4)

Permanent engineering constraints for this repository. They override any plan step that
conflicts with them.

## Current state

- Entry point: `app.py` (FastAPI dashboard, port 8000). Core: `core/pipeline.py`
  (capture → OCR → TTS threads), `core/ocr_engine.py`, `core/tts_engine.py`, `core/config.py`.
- Protected baseline: git tag `v2.0.4-baseline`. Baseline measurements: `docs/baseline/`.
- Current milestone: **Milestone A — baseline-preserving modularization**
  (CameraInterface → OCRAdapter → TextProcessor → TTSAdapter → AudioManager).
  Do not start YOLO, context, priority, or transport work until Milestone A is done.
- Dev machine is Windows / Python 3.10 (`.venv`); target is Jetson Orin Nano. Code must run on both.

## Project rules

1. **Audit before editing.** Never rewrite, delete, rename, or replace a module until its
   behavior is inspected and documented.
2. **Preserve working v2.0.4.** OCR→TTS is a protected baseline. Every change either preserves
   it, replaces it with a documented reason (ADR), or improves it with regression coverage.
3. **Hardware-independent core.** Business logic must not import Jetson/RPi/STM32/GPIO/camera-driver
   APIs. Hardware is reached only through interfaces/adapters.
4. **Pluggable models.** OCR and detection engines are replaceable without touching decision logic.
5. **Offline first.** Core OCR, detection, decisions, and TTS work without Internet.
   Models must be loadable from local paths.
6. **Event driven.** Do not continuously run expensive perception unless a mode explicitly requires it.
7. **No unvalidated safety claims.** Basic spatial awareness is fine. Never describe the system as
   collision avoidance, autonomous navigation, or safety-critical.
8. **No cloud dependency.** Cloud APIs only as optional extensions, never required.
9. **No magic numbers.** Thresholds, cooldowns, confidences, intervals, model choices live in config.
10. **Profile before optimizing.** Measure latency/CPU/RAM/NPU/network/TTS first.
11. **Fail gracefully.** Sensor, model, network, TTS, and audio failures produce controlled
    behavior, never a crash of the whole system. Never swallow exceptions silently: log them.
12. **Privacy.** Do not persist camera frames by default. No raw frames in logs. Do not log
    recognized text/speech above DEBUG.
13. **Document decisions.** Architecture changes get an ADR: `docs/adr/NNNN-description.md`.
14. **Test every graph edge.** Each major pipeline transition has a unit or integration test.
15. **Don't overengineer V1.** No LLMs, VLMs, GPS, cloud inference, stereo vision, or autonomous
    navigation unless explicitly approved.

## Do not

- Rewrite the repository from scratch, or delete the OCR pipeline before reproducing it.
- Hard-code Raspberry Pi/Jetson APIs or hardware paths in business logic.
- Run OCR or detection continuously at max frequency by default.
- Speak every detection, or repeat the same object/text inside its cooldown.
- Claim depth from a 2D bounding box.
- Store camera frames, commit secrets, or add an LLM "because it's available".
- Run all OCR engines simultaneously in production without benchmark justification.
- Remove v2.0.4 features without regression evidence.
- Pass recognized text into a shell/PowerShell command string (use argv lists or stdin).

## Working conventions

- Run with `.venv/Scripts/python.exe` on Windows.
- Match existing style: module-level `logger = logging.getLogger(...)`, type hints on new code.
- Line endings: `.py` and `.sh` are LF (see `.gitattributes`).
- Commit in small steps; each step keeps `v2.0.4` behavior unless an ADR says otherwise.
