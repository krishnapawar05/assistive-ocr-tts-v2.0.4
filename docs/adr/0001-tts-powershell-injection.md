# ADR 0001 — Pass TTS text to PowerShell via environment, not string interpolation

- Status: Accepted
- Date: 2026-09-26
- Deviates from baseline: `v2.0.4-baseline` (intentional, security fix)

## Context

`TTSEngine._espeak` falls back to Windows `System.Speech` when Coqui TTS is unavailable
(which is the case on the current dev machine: Coqui `TTS` is not installed). v2.0.4 built the
PowerShell script with an f-string:

```python
f'$s.Speak("{text}");'
```

`text` is OCR output from the camera, so it is untrusted input. Text containing `"` breaks the
string literal, and `$(...)` inside a double-quoted PowerShell string is evaluated. Any printed
or handwritten text in front of the camera could therefore execute arbitrary commands as the
user running the app. The `voice` value was interpolated the same way.

## Decision

The script passed to `powershell -Command` is now a fixed string. Text and voice travel in
environment variables `SVA_TTS_TEXT` and `SVA_TTS_VOICE` and are read as `$env:...`, which
PowerShell treats as data. `-NoProfile` was added so user profile scripts do not run on every
utterance.

## Consequences

- Spoken output is unchanged for ordinary text. Text containing quotes is now spoken
  instead of breaking the command.
- Unchanged, and still to fix later: the default config voice `p335` is a Coqui speaker name,
  so on Windows `SelectVoice` fails and the default system voice is used. This matches v2.0.4.
- The POSIX `espeak-ng` branch already used an argv list and was not affected. Its volume
  argument (`-a{int(100*volume*100)}` → 9000, valid range 0–200) is a separate known bug, not
  changed here.

## Verification

`tests/unit/test_tts_fallback_injection.py` asserts the text is absent from the script and
present in the env. It includes a live PowerShell check that an injection payload is not
executed. These tests fail against `v2.0.4-baseline` and pass with this change.
