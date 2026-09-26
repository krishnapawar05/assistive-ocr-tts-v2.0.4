# Dependency matrix — Python 3.10 (Windows dev machine)

Verified 2026-09-26 on Windows 11, Intel CPU (Family 6 Model 154), 7.9 GB RAM, no CUDA GPU.
"Offline" means it was run with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` and models loaded from local paths.
Full pinned set: [`docs/environment/pip-freeze.txt`](../environment/pip-freeze.txt).
Original v2.0.4 environment: [`pip-freeze.txt`](pip-freeze.txt).

## Python packages

| Package | Installed | Required range | Used by | CPU | Offline | Jetson (aarch64) | Known issues | Decision |
|---|---|---|---|---|---|---|---|---|
| numpy | 2.2.6 | >=1.26,<2.3 | everything | yes | yes | yes | Old `numpy==1.22.0` pin was never honored (paddle/opencv pull 2.x) | Replace pin with verified range |
| opencv-python-headless | 4.12.0.88 | >=4.10,<5.0 | camera, preprocessing | yes | yes | Use JetPack OpenCV (has GStreamer) | `opencv-contrib-python` 4.10 is also installed (pulled by a dependency); `cv2` resolves to headless 4.12 | Keep headless; old `<4.9` pin dropped |
| Pillow | 12.1.0 | >=10,<13 | TrOCR input, fixtures | yes | yes | yes | Built without `raqm`: cannot shape Hindi/Kannada | Keep; Indic fixtures rendered via .NET GDI+ |
| psutil | 7.2.1 | >=5.9,<8 | benchmarks | yes | yes | yes | — | Add (was implicit) |
| fastapi | 0.128.0 | >=0.110,<1.0 | `app.py` | yes | yes | yes | — | Keep |
| uvicorn | 0.40.0 | >=0.29,<1.0 | `app.py` | yes | yes | yes | — | Keep |
| jinja2 | 3.1.6 | >=3.1,<4 | dashboard | yes | yes | yes | — | Keep |
| python-multipart | not installed | — | nothing (`Form` imported, unused) | — | — | — | — | Removed from requirements |
| aiofiles | not installed | — | nothing (Starlette no longer needs it) | — | — | — | — | Removed |
| pytesseract | 0.3.13 | >=0.3.10,<0.4 | Tesseract adapter | yes | yes | yes (`apt install tesseract-ocr`) | **Tesseract executable not installed** on dev machine | Keep; adapter reports NOT_AVAILABLE |
| easyocr | 1.7.2 | >=1.7.1,<1.8 | EasyOCR adapter | yes | yes, with `download_enabled=False` | yes (with JetPack torch) | Only `english_g2` + `craft` models cached; Hindi (`devanagari`) and Kannada missing | Keep |
| paddleocr | 3.3.2 | >=3.3,<3.4 | PaddleOCR adapter | yes | yes, with explicit `*_model_dir` | Limited: needs Paddle Inference Jetson build | 3.x removed `use_gpu`/`show_log`; `ocr()` → `predict()`; v2.0.4 code fails to init | Keep 3.x; adapter uses 3.x API |
| paddlepaddle | 3.2.2 | >=3.2,<3.3 | PaddleOCR | yes | yes | Needs NVIDIA/Paddle Jetson wheel | Server det model ~11 s/frame on this CPU | Keep |
| paddlex | 3.3.13 | (transitive) | PaddleOCR | yes | yes | as paddle | Checks model hoster unless `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` | Not listed; adapter sets the env var |
| transformers | 4.57.3 | >=4.45,<4.58 | TrOCR adapter | yes | yes, with `local_files_only=True` | yes | TrOCR is line-level; whole-frame use hallucinates (`'0 0'` on blank) | Keep; region-based TrOCR |
| torch / torchvision | 2.9.1 / 0.24.1 | >=2.4,<2.10 / >=0.19,<0.25 | EasyOCR, TrOCR, Coqui | yes | yes | Must use JetPack wheels | — | Keep |
| torchaudio | 2.9.1 (added) | >=2.4,<2.10 | Coqui (import-time) | yes | yes | JetPack wheel | Must match torch exactly | Added; install was additive only |
| torchcodec | 0.8.1 (added) | >=0.8,<0.9 | Coqui import guard | yes | yes | unverified | Coqui refuses import on torch≥2.9 without it; FFmpeg not needed for synthesis | Added |
| coqui-tts | 0.27.5 (added) | >=0.27,<0.28 | Coqui adapter | yes | yes, via `model_path`+`config_path` | yes (slow) | Original `TTS==0.22.0` needs numpy 1.22 → incompatible; it was never installed | Replace with maintained fork |
| rapidfuzz | 3.14.3 | >=3.0,<4.0 | duplicate filter, OCR agreement | yes | yes | yes | — | Keep (now used) |
| symspellpy | 6.9.0 | — | nothing | — | — | — | Unused | Removed from requirements |
| ImageHash | not installed | — | nothing | — | — | — | Unused | Removed |
| ultralytics | not installed | — | nothing (YOLO not wired up) | — | — | — | `yolov8n.pt` present but unused | Deferred to object-awareness milestone |
| sounddevice / soundfile | 0.5.3 / 0.13.1 | >=0.4.6,<0.6 / >=0.12,<0.14 | Coqui playback | yes | yes | yes (PortAudio) | — | Keep |

The Coqui install was checked with `pip install --dry-run` first. It added packages only and
changed no existing version (diffed `pip freeze` before and after).

## External runtimes and models

| Item | Present | Location | Needed by | Notes |
|---|---|---|---|---|
| Tesseract executable | **No** | — | Tesseract adapter | Install UB-Mannheim build (see README) |
| eSpeak NG 1.52.0 | Yes | `C:\Program Files\eSpeak NG\` | eSpeak adapter | Voices: en, en-us, hi, kn |
| Windows System.Speech | Yes | built in | Windows speech adapter | Dev fallback only |
| Paddle `PP-OCRv5_server_det` | Yes | `~/.paddlex/official_models/` | PaddleOCR | ~11 s/frame on CPU |
| Paddle `en_PP-OCRv5_mobile_rec` | Yes | same | PaddleOCR (en) | |
| Paddle `PP-OCRv5_server_rec` | Yes | same | PaddleOCR (hi/kn not covered) | Chinese/English/Japanese |
| Paddle mobile det, Devanagari/Kannada rec | No | — | faster det / hi / kn | Manual download step |
| EasyOCR `craft_mlt_25k`, `english_g2` | Yes | `~/.EasyOCR/model/` | EasyOCR (en) | |
| EasyOCR `devanagari`, `kannada` | No | — | EasyOCR hi / kn | Manual download step |
| `microsoft/trocr-base-handwritten` | Yes | HF cache | TrOCR | English handwriting only |
| Coqui `tts_models/en/vctk/vits` | Yes | `%LOCALAPPDATA%\tts\` | Coqui | 109 speakers incl. p335 |
| Coqui `xtts_v2`, `tacotron2-DDC` | Yes | same | not used | |
