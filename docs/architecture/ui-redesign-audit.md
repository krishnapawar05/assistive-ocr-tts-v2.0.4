# UI Redesign Audit — Smart Vision Assist v2.0.4
**Date:** 2026-09-27  
**Auditor:** Antigravity AI  
**Status:** Pre-implementation audit

---

## Executive Summary

The current UI is architecturally correct but aesthetically and experientially wrong for its audience. It presents as a **developer monitoring dashboard** when it needs to be a **calm, focused assistive reading tool** for visually impaired students.

---

## File Inventory

| File | Size | Role |
|---|---|---|
| `templates/base.html` | 3.1 KB | Shell: header, skip link, accessibility toggles, Bootstrap CDN |
| `templates/dashboard.html` | 16.6 KB | Main content: status, controls, OCR panel, camera, settings |
| `static/style.css` | 8.5 KB | Design tokens + component styles (Bootstrap override layer) |
| `static/dashboard.js` | 33 KB | All interactivity: polling, API calls, keyboard, forms |

---

## Critical Problems Found

### 1. Visual Hierarchy — BROKEN
- All 4 primary action buttons have **equal visual weight** — same size, same padding. No primary/secondary distinction.
- The status strip (System / Camera / Speech badges) sits ABOVE the controls — the first thing a user sees is system internals, not a welcome.
- The detected text panel uses `background: #0f172a` (near-black) with `color: #38bdf8` (cyan) — terminal aesthetics, not reading tool aesthetics.
- The camera view is **smaller** than the text panel (col-lg-5 vs col-lg-7) — inverted priority for a camera-first tool.

### 2. Information Architecture — DEVELOPER-FIRST
- The diagnostics section (`⚙️ Diagnostics, Engine Controls & Settings`) is **rendered open by default** via `<details>` without the `open` attribute — good. BUT it dominates 60% of page scroll height.
- Technical labels exposed to students: "EasyOCR (NOT_AVAILABLE)", "Windows Speech (Native SAPI)", "Min Confidence: 0.56", "Capture Interval: 0.2", "OpenCV (USB/Webcam)", "Camera ID: 0".
- History panel is buried inside the diagnostics drawer — correct placement, but styled as a debug log.

### 3. Typography — INCONSISTENT
- App title: 1.4rem / 700 weight — too small for a header.
- OCR output text: 1.6rem in the box but on a `#0f172a` background that looks like a terminal.
- Form labels: 0.9rem / 600 weight — tiny, not accessible.
- Status badges: 0.85rem UPPERCASE — aggressive styling for passive status.
- No Google Font loaded — using system stack (fine but inconsistent across OS).

### 4. Color System — OVERLOADED
- Using raw Bootstrap colors: `btn-success` (green), `btn-primary` (blue), `btn-danger` (red), `btn-secondary` (grey) — all full saturated Bootstrap defaults.
- Status badges: `bg-success`, `bg-warning`, `bg-info`, `bg-secondary`, `bg-dark` — 5 different badge colors in one strip.
- OCR box cyan-on-dark feels neon/terminal.
- No semantic calm palette for an accessibility product.

### 5. Camera UX — WRONG PROPORTIONS
- Camera is `col-lg-5` (5/12 columns) — text gets 7 columns. Should be equal or camera-primary.
- Camera area has black background with a `max-height: 380px` cap.
- Viewfinder overlay uses `3px dashed #00ffff` (neon cyan dashes) + `box-shadow: 0 0 0 9999px rgba(0,0,0,0.3)` — creates a "police spotlight" dark surround effect that's visually harsh.
- No camera offline/reconnecting state shown in the camera area itself.

### 6. Action Controls — ALL EQUAL WEIGHT
- Start System, Pause, Replay Text, Stop Speech — all `btn-action` with `min-height: 52px`.
- All get `transform: translateY(-2px)` on hover — every button feels equally important.
- `btn-danger` red Stop Speech competes with `btn-success` green Start — both bold primary-feeling.

### 7. Microcopy — DEVELOPER LANGUAGE
- "Waiting for text... Press 'Start System' or Space to begin." — Developer placeholder.
- "Status: Idle. Point camera at document and hold steady." — Status prefix is developer-speak.
- "Camera: Reconnecting..." — OK but buried in a status strip.
- "High Confidence Text" — label visible to student, meaningless to them.
- "Run OCR Frame Diagnostics" — inside the drawer, OK.

### 8. Responsiveness — MINIMAL
- Uses Bootstrap grid (col-lg-7/5) but no specific mobile layout.
- On mobile: buttons stack but camera/text panels also stack with camera below text — wrong order.
- No tablet-specific consideration.

### 9. Accessibility — GOOD BONES, NEEDS POLISH
- ✅ Skip link present
- ✅ Keyboard shortcuts implemented (Space, R, Esc)
- ✅ `aria-live="polite"` on OCR output
- ✅ `aria-live="assertive"` on alert container
- ✅ High contrast mode implemented
- ✅ Large font mode implemented
- ✅ Reduced motion media query
- ❌ Focus states use `#ffbf47` (yellow outline) — contrast fine but styling is Bootstrap default-ish
- ❌ No `aria-disabled` on buttons when pipeline not running
- ❌ Status badges use color alone in some states
- ❌ Settings forms have no field descriptions

### 10. Performance
- Bootstrap 5.3 CDN (CSS + JS): ~350KB — acceptable but avoidable
- 1-second status polling interval — fine
- 3-second history polling — fine
- Camera snapshot refreshed every poll when running — could be 2s separate interval
- No memory leak risks detected in JS

---

## What Must Be Preserved (Zero Change)

- All `Dashboard` class methods: `startPipeline`, `stopPipeline`, `replayAudio`, `stopSpeech`, `testCamera`, `testOCR`
- All API endpoint calls: `/api/start`, `/api/stop`, `/api/status`, `/api/history`, `/api/camera/snapshot`, `/api/config`, `/api/test-camera`, `/api/test-ocr`, `/api/replay`, `/api/replay-latest`, `/api/stop-speech`
- All keyboard shortcuts: Space, R, Esc
- `static formatOcrTest()` — unit tested
- `announce()` — screen reader live region
- `escapeHtml()` — security-critical
- Config form logic: `saveOCRConfig`, `saveTTSConfig`, `saveCameraConfig`
- `startPolling` / `updateStatus` / `updateHistory`
- High contrast toggle
- Large font toggle
- All aria attributes and landmark structure

---

## Redesign Plan

### Layout Change
```
OLD:
[Status Strip - 3 badges]
[Start][Pause][Replay][Stop]  <- equal weight
[Detected Text (7col)] [Camera (5col)]
[Diagnostics Drawer - huge]

NEW:
[Header: Logo + Status Dot + Accessibility Controls]
[Camera (6col)] [Detected Text (6col)]  <- equal, camera left
[Action Bar: PRIMARY[Start] secondary[Pause Replay] interrupt[Stop]]
[Hint: "Point camera at text to begin reading"]
[Settings Drawer - collapsed, clean]
```

### Design Token Changes
- Remove Bootstrap CDN dependency — use vanilla CSS only
- Inter font from Google Fonts
- Background: `#F8F9FB` (very light neutral grey)
- Surface: `#FFFFFF`
- Primary: `#2563EB` (accessible blue, WCAG AA)
- Text: `#1A1A2E`
- Muted: `#6B7280`
- OCR text background: `#FFFFFF` with dark text
- Success: `#059669`
- Danger: `#DC2626`
- Warning: `#D97706`

### Component Changes
- Camera: larger, equal to text, left-first on desktop
- OCR text: white background, dark text, large readable font
- Buttons: distinct hierarchy (filled/outlined/ghost)
- Status: single pill in header, not a 3-badge strip
- Settings: collapsed drawer with organized sections
