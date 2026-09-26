# Smart Vision Assist — OCR → TTS (from assistive-ocr-tts v2.0.4)

Offline assistive reader: a camera frame is checked, read by one or more OCR engines, filtered
for duplicates and low confidence, and spoken through a local TTS engine. It is
classroom-oriented (boards, signs, printed and handwritten text). The development machine is
Windows; the target device is a Jetson Orin Nano.

> **Status:** Milestone A (baseline-preserving modularization). OCR accuracy has only been
> checked on **synthetic** images; see [Known limitations](#known-limitations).
> Engineering rules for contributors are in [`CLAUDE.md`](CLAUDE.md).

## Contents
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Engine setup](#engine-setup): Tesseract, EasyOCR, PaddleOCR, TrOCR, Coqui, Windows speech, eSpeak NG
- [Offline model setup](#offline-model-setup)
- [Configuration](#configuration)
- [Testing](#testing)
- [Benchmarking](#benchmarking)
- [Jetson considerations](#jetson-considerations)
- [Known limitations](#known-limitations)

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
# download models once while online (see "Offline model setup"), then:
.venv\Scripts\python.exe app.py        # dashboard at http://localhost:8000
```

Click **Test OCR** to see which OCR/TTS engines are `READY` on this machine and why the others
are not. Then click **Start**. `SVA_CONFIG=path\to\config.json` selects another config file.

## Architecture

```
Camera → FrameController → QualityAssessor → ChangeDetector → Preprocessor
       → OCRService (single_engine | fallback | ensemble, scored selection)
       → DuplicateFilter → SpeechComposer → AudioManager → TTSService (engine fallback)
```

Details, stage contracts and threads: [`docs/architecture/overview.md`](docs/architecture/overview.md).
Decisions: [`docs/adr/`](docs/adr/). Every engine sits behind an adapter and reports one of
`READY`, `DISABLED`, `NOT_AVAILABLE`, `MODEL_NOT_AVAILABLE`, `LANGUAGE_NOT_SUPPORTED` or
`INIT_FAILED`, together with a reason. A missing engine never crashes the app; the next
configured engine is used.

## Engine setup

Verified versions are in [`docs/baseline/dependency-matrix.md`](docs/baseline/dependency-matrix.md).

### Tesseract
`pytesseract` is only a wrapper. The **Tesseract executable** must be installed separately.
- **Windows:** install the UB Mannheim build from
  <https://github.com/UB-Mannheim/tesseract/wiki>. In the installer, under "Additional language
  data", tick **Hindi** and **Kannada** if you need them. The default path
  `C:\Program Files\Tesseract-OCR\tesseract.exe` is found automatically; otherwise set
  `ocr.engines.tesseract.executable`.
- **Linux/Jetson:** `sudo apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-kan`
- Check it: `tesseract --list-langs` must show `eng` (plus `hin`/`kan` for Hindi/Kannada).
  The adapter reports `MODEL_NOT_AVAILABLE` when the traineddata for the configured language
  is missing.

### EasyOCR
`pip install easyocr` (in requirements). It never downloads at runtime
(`download_enabled=False`). Models live in `~/.EasyOCR/model/` or in
`ocr.engines.easyocr.model_dir`:
`craft_mlt_25k.pth` (detector), `english_g2.pth`, `devanagari.pth` (Hindi), `kannada.pth`.

### PaddleOCR (3.x)
`pip install paddleocr paddlepaddle` (in requirements). The adapter uses the **3.x API**. The
2.x `use_gpu` code in v2.0.4 no longer loads. Models are loaded from
`ocr.engines.paddle.model_root` (default `~/.paddlex/official_models/<model name>/`), using the
names in `det_model` and `rec_models`. CPU by default; set `ocr.engines.paddle.device`
(e.g. `gpu:0`) for an accelerator.

### TrOCR
`microsoft/trocr-base-handwritten` from the Hugging Face cache, loaded with
`local_files_only=True`. It is English handwriting only and works on text-line crops found by
`core/ocr/regions.py`, never on whole frames. It is most useful with
`ocr.text_type: "handwritten"`.

### Coqui TTS
`pip install coqui-tts torchaudio torchcodec` (in requirements; this is the maintained fork,
and its import name is still `TTS`). The model is loaded from local files only:
`%LOCALAPPDATA%\tts\tts_models--en--vctk--vits\` (Linux: `~/.local/share/tts/...`), or from
`tts.engines.coqui.model_dir`. The speaker is `tts.voice` (default `p335`). The VITS model needs
**espeak-ng** installed for phonemes.

### Windows speech (development fallback)
Built in (System.Speech via PowerShell). OCR text is passed through environment variables and
is never inserted into the command ([ADR 0001](docs/adr/0001-tts-powershell-injection.md)).
A voice is chosen by `tts.engines.windows.voice` or by language.

### eSpeak NG
- **Windows:** install from <https://github.com/espeak-ng/espeak-ng/releases>
  (`C:\Program Files\eSpeak NG\` is found automatically).
- **Linux/Jetson:** `sudo apt install espeak-ng`

Text is sent on stdin. Volume 0.0–1.0 maps to amplitude 0–200. Voices `en`, `hi` and `kn` are
used for the three app languages.

## Offline model setup

The app runs with `app.offline_mode: true`, which sets `HF_HUB_OFFLINE`,
`TRANSFORMERS_OFFLINE` and `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`. It never downloads models.
Fetch them **once while online**:

```powershell
# EasyOCR (English + optional Hindi/Kannada)
.venv\Scripts\python.exe -c "import easyocr; easyocr.Reader(['en'], gpu=False)"
.venv\Scripts\python.exe -c "import easyocr; easyocr.Reader(['hi','en'], gpu=False); easyocr.Reader(['kn','en'], gpu=False)"
# PaddleOCR 3.x (default det/rec models for English)
.venv\Scripts\python.exe -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en', device='cpu')"
# TrOCR
.venv\Scripts\python.exe -c "from transformers import TrOCRProcessor, VisionEncoderDecoderModel as M; n='microsoft/trocr-base-handwritten'; TrOCRProcessor.from_pretrained(n); M.from_pretrained(n)"
# Coqui VITS (English, multi-speaker)
.venv\Scripts\python.exe -c "from TTS.api import TTS; TTS('tts_models/en/vctk/vits')"
```

| Model | Needed for | Present on the dev machine |
|---|---|---|
| EasyOCR `craft_mlt_25k`, `english_g2` | EasyOCR English | yes |
| EasyOCR `devanagari`, `kannada` | EasyOCR Hindi / Kannada | **no** |
| Paddle `PP-OCRv5_server_det`, `en_PP-OCRv5_mobile_rec` | PaddleOCR English | yes |
| Paddle Devanagari / Kannada rec models | PaddleOCR Hindi / Kannada | **no**. The configured names in `rec_models` are unverified; check them against the PaddleOCR 3.x model list |
| `microsoft/trocr-base-handwritten` | TrOCR | yes |
| Coqui `tts_models/en/vctk/vits` | Coqui TTS | yes |
| Tesseract `eng`/`hin`/`kan` traineddata | Tesseract | **no** (Tesseract itself is not installed) |

A missing model produces `MODEL_NOT_AVAILABLE` with the path it looked in; it never triggers a
download.

## Configuration

`config.json` (full defaults: [`config.example.json`](config.example.json)). It is validated
at startup: the app exits with a list of invalid keys, and `/api/config` returns HTTP 400
with the same list. v2.0.4 keys are migrated automatically. Main settings:

| Key | Meaning |
|---|---|
| `ocr.engine`, `ocr.fallback_order` | primary engine and the order of the rest |
| `ocr.mode` | `single_engine` (fastest), `fallback` (default), `ensemble` (slowest) |
| `ocr.language` | `en`, `hi`, `kn` (legacy `eng`/`hin`/`kan` accepted) |
| `ocr.text_type` | `printed` or `handwritten` (changes engine reliability weights) |
| `ocr.min_confidence`, `ocr.min_final_score`, `ocr.accept_score` | confidence gates |
| `ocr.preload` | `primary` (default: fallback engines load on first use) or `all` |
| `ocr.serialize_engines` | never run two OCR engines at once (default `true`; memory safety) |
| `ocr.scoring.*` | scoring weights, penalties and per-engine reliability |
| `ocr.duplicates.cooldown_s`, `fuzzy_threshold` | repeat suppression |
| `ocr.engines.<engine>.*` | per-engine enable, timeout, model paths |
| `frame.quality.*`, `frame.change_detection.*`, `frame.preprocess.*` | frame gates, preprocessing |
| `tts.engine`, `tts.fallback_engines`, `tts.language`, `tts.voice`, `tts.speed`, `tts.volume` | speech |
| `audio.policy` | `queue`, `interrupt`, `drop_if_busy`; plus `max_queue_size`, `max_age_s` |
| `app.log_level`, `app.offline_mode` | logging and offline switches |

Recognized text is only logged at DEBUG level. Camera frames are never written to disk.

## Testing

```powershell
.venv\Scripts\python.exe scripts\run_tests.py                      # everything + engine PASS/FAIL/NOT_AVAILABLE matrix (~12 min)
.venv\Scripts\python.exe scripts\run_tests.py --fast               # unit tests only
.venv\Scripts\python.exe -m unittest discover -s tests/unit -t .   # unit tests, single process
```

`run_tests.py` runs each test module in its own process, so the models one module loads are
freed before the next starts, and prints each module's peak RSS. Heaviest modules measured on the
dev machine: `test_ocr_pipeline` 2.3 GB (ensemble loads three OCR engines), `test_end_to_end`
2.2 GB. If available RAM stays below `--min-available-gb` (default 0.3) the current module is
killed and reported as a failure. Running the whole `tests/` tree in one process
(`unittest discover -s tests`) needs more than 2.5 GB free.

| Suite | What it covers |
|---|---|
| `tests/unit` | config, text processing, scoring, duplicates, OCR service modes, TTS adapters (mocked), audio manager |
| `tests/ocr` | each real OCR engine: init, local load with network blocked, CPU, fixture reads, confidence, errors, languages, latency |
| `tests/integration/test_tts_pipeline.py` | each real TTS engine (silent), hostile OCR strings |
| `tests/integration/test_ocr_pipeline.py` | real engines in every OCR mode |
| `tests/integration/test_end_to_end.py` | acceptance TEST 1–14 |
| `tests/integration/test_app_api.py` | HTTP API (no camera, silent TTS) |

An engine that cannot run on the machine is reported as **NOT_AVAILABLE** (tests skipped with
that reason) and never as PASS. An installed engine that fails to load is a **FAIL**.
Fixtures (`tests/fixtures/ocr/`, regenerated by `scripts/generate_ocr_fixtures.py`) are
synthetic. They prove the engines work, **not** how accurate they are.

## Benchmarking

```powershell
.venv\Scripts\python.exe tests\benchmarks\ocr_tts_benchmark.py --label mytest [--camera] [--set key=value ...]
```

Results: [`docs/benchmarks/ocr-tts-baseline.md`](docs/benchmarks/ocr-tts-baseline.md). The
v2.0.4 comparison is in `docs/baseline/ocr-baseline.json`.

## Jetson considerations

- Install torch/torchvision/torchaudio from NVIDIA's JetPack wheels **before**
  `pip install -r requirements.txt`. PaddlePaddle needs a Jetson (aarch64) Paddle Inference
  build. If none is available, disable it (`ocr.engines.paddle.enabled: false`); the app runs
  with the remaining engines.
- Use JetPack's OpenCV (built with GStreamer) and `camera.source_type: "gstreamer"` for CSI
  cameras (`nvarguscamerasrc`).
- `apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-kan espeak-ng`. Windows speech
  is unavailable on Jetson; use `tts.fallback_engines: ["espeak"]`.
- None of the latency numbers here were measured on a Jetson. Profile there before tuning.

## Known limitations

- Accuracy has **not** been measured on real classroom captures, only on synthetic fixtures.
  Engine reliability weights are initial values.
- Tesseract is not installed on the dev machine, so its adapter is implemented but untested
  against the real binary.
- Hindi/Kannada OCR models are not installed. Hindi/Kannada speech is available only via
  eSpeak NG. Coqui VITS and TrOCR are English-only.
- CPU-only OCR is slow (seconds per frame; see the benchmark). The continuous camera mode relies
  on change detection and duplicate suppression to keep this usable.
- Windows speech starts a PowerShell process per utterance (about 1 s overhead). It is a
  development fallback.
- Frame quality thresholds (dark/blank/blur) are conservative defaults, not tuned on real
  cameras.
