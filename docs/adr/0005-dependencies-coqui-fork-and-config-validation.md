# ADR 0005 — Dependency set, Coqui fork, and strict configuration

- Status: Accepted
- Date: 2026-09-26

## Context

- `requirements.txt` pinned `numpy==1.22.0` and `TTS==0.22.0`. PaddleOCR 3.x and OpenCV pull
  numpy 2.x, so the pin was never honored. The original `TTS` package was never installed
  either, so Coqui never ran and every utterance fell through to the PowerShell fallback.
- The v2.0.4 PaddleOCR code used the 2.x API (`use_gpu`), which 3.x rejects, so PaddleOCR
  never loaded.
- `Config.load()` silently replaced an unreadable `config.json` with defaults, which destroyed
  the user's settings.

## Decision

- Use the maintained **`coqui-tts` 0.27** fork (import name `TTS`) with `torchaudio`/
  `torchcodec` matching torch 2.9. These were installed additively: a `pip freeze` diff showed
  no existing package changed. Keep PaddleOCR 3.x and adapt the code to it rather than
  downgrading. Keep `torch<2.10`, because EasyOCR 1.7 uses `torch.ao.quantization`, which is
  removed in 2.10.
- Coqui VITS speed is set via `length_scale`, because `tts(speed=)` is ignored for VITS.
- Replay audio is kept in memory. v2.0.4 wrote `last_audio.wav` into the repo and, on
  playback errors, opened it in the default media player.
- Configuration is validated at startup and on every `/api/config` update, with per-path
  error messages. Invalid JSON is an error, not a reset. v2.0.4 keys are migrated
  (`use_trocr`, `handwriting_fallback`, and `language: "eng"` → `"en"`), and dead keys are
  removed.

## Consequences

The verified matrix is in `docs/baseline/dependency-matrix.md`. The app refuses to start with
an invalid config and prints what to fix.
