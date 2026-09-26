# ADR 0004 — Duplicate suppression, change detection and speech policy

- Status: Accepted
- Date: 2026-09-26
- Deviates from baseline: yes (intentional)

## Context

v2.0.4 suppressed only the *exact* previous string for 1.5 s. OCR on one frame took several
seconds, so the same sign in view was re-read and re-spoken on every cycle. "Room 204",
"Room204" and "Room 204." counted as different texts. TTS calls could also queue without
limit, and `/api/speak` played audio directly from the web request.

## Decision

- **DuplicateFilter** (`ocr.duplicates`) matches exact, normalized (case, spacing and
  punctuation) and fuzzy text (RapidFuzz ratio ≥ `fuzzy_threshold`). Numbers must match
  exactly, so "Room 204" and "Room 1204" stay distinct. The cooldown defaults to **20 s**, and
  `refresh_on_repeat` keeps text that stays in view suppressed. Text is spoken again only
  after it has been absent for the whole cooldown.
- **ChangeDetector** (`frame.change_detection`) skips OCR on frames that look like the last
  processed one, re-checking at least every `max_skip_s`. This makes the continuous mode
  event-driven in practice (CLAUDE.md rule 6).
- **QualityAssessor** skips blank, dark, overexposed, tiny and (optionally) blurred frames
  before OCR. The blur gate is off by default (`min_sharpness: 0`) because EasyOCR still read
  the blurred fixture correctly. It should be enabled only after tuning on real captures.
- **AudioManager** allows one utterance at a time. `audio.policy` is `queue` (default,
  bounded, drops the oldest item), `interrupt` or `drop_if_busy`, and stale requests are
  dropped after `max_age_s`. All speech, including `/api/speak`, goes through it.

## Consequences

- A sign that stays in view is announced once, not every few seconds.
- A reading changed by one digit is announced, which is intended.
- The cooldown and policies are user-tunable in config.
