# Target Hardware Deployment Plan — NVIDIA Jetson Orin Nano

**Document Version:** 1.0.0  
**Target Hardware:** NVIDIA Jetson Orin Nano Developer Kit (8 GB Unified LPDDR5)  
**Host Architecture:** aarch64 (ARMv8.2 64-bit)  
**Status:** Architectural Plan & Pre-Deployment Specification  
*(IMPORTANT: Do not claim production readiness on Jetson until real bench testing is conducted on physical hardware).*

---

## 1. Verification Separation Matrix

| Component | Status on Development Host (Windows x86_64) | Status on Target Hardware (Jetson Orin Nano) |
| :--- | :--- | :--- |
| **Pipeline Core** | **VERIFIED** (232 tests green, 0 failures) | **NOT YET VERIFIED ON TARGET HARDWARE** |
| **EasyOCR** | **VERIFIED** (CPU inference, 100% pass) | **NOT YET VERIFIED ON TARGET HARDWARE** (Requires PyTorch JetPack wheel) |
| **PaddleOCR** | **VERIFIED** (3.x det/rec models loaded offline) | **NOT YET VERIFIED ON TARGET HARDWARE** (Requires Paddle Inference aarch64 build) |
| **TrOCR** | **VERIFIED** (Hugging Face offline cache, region gating) | **NOT YET VERIFIED ON TARGET HARDWARE** (Requires PyTorch JetPack wheel) |
| **Coqui TTS** | **VERIFIED** (VITS model offline execution) | **NOT YET VERIFIED ON TARGET HARDWARE** (Requires aarch64 torchaudio build) |
| **Windows Speech** | **VERIFIED** (SAPI via PowerShell) | **NOT AVAILABLE ON LINUX/JETSON** (Intentionally replaced by eSpeak NG) |
| **eSpeak NG** | **VERIFIED** (Native CLI wrapper) | **NOT YET VERIFIED ON TARGET HARDWARE** (`apt install espeak-ng` ready) |
| **OpenCV Camera** | **VERIFIED** (DirectShow on webcam 0) | **NOT YET VERIFIED ON TARGET HARDWARE** (Requires V4L2 or GStreamer CSI) |
| **Web Dashboard** | **VERIFIED** (FastAPI, accessible templates, shortcuts) | **NOT YET VERIFIED ON TARGET HARDWARE** (Localhost browser ready) |

---

## 2. Hardware Specifications & Operating Envelopes

### 2.1 Compute & Power
- **Module:** NVIDIA Jetson Orin Nano (8 GB)
- **CPU:** 6-core Arm Cortex-A78AE v8.2 64-bit CPU @ 1.5 GHz
- **GPU:** 1024-core NVIDIA Ampere architecture GPU with 32 Tensor Cores @ 625 MHz
- **Memory:** 8 GB 128-bit LPDDR5 @ 68 GB/s (Unified CPU/GPU memory space)
- **Power Envelope:** Configured via `nvpmodel`:
  - 10W Mode (`nvpmodel -m 1`): Best for battery-powered student wearables; CPU throttled.
  - 15W Mode (`nvpmodel -m 0`): Maximum throughput; recommended for classroom desktop/stand use.
- **Thermals:** Active fan heat sink mandatory. Sustained CPU inference without active cooling causes thermal throttling at 85°C.

### 2.2 Sensors & Audio Peripherals
- **Camera Interfaces:**
  - *USB Webcams (UVC):* Handled via `/dev/video0` using `camera.source_type: "opencv"`.
  - *MIPI-CSI Cameras (Sony IMX219 / IMX477):* Handled via GStreamer hardware acceleration using `camera.source_type: "gstreamer"`:
    ```text
    nvarguscamerasrc sensor-id=0 ! video/x-raw(memory:NVMM), width=1280, height=720, framerate=30/1 ! nvvidconv ! video/x-raw, format=BGRx ! videoconvert ! video/x-raw, format=BGR ! appsink
    ```
- **Audio Output:**
  - USB Audio DAC / 3.5mm Headphone Jack (PAM8403 amplified speaker or wired student headphones).
  - Configured via ALSA/PulseAudio (`/dev/snd/pcmC0D0p`).

---

## 3. Unified Memory Constraints & Budgeting

On Jetson Orin Nano, the CPU and GPU **share the identical 8 GB memory pool**. System OS and display server consume ~1.2 GB.

```
Total Physical Memory: 8,192 MB
├── Linux OS & Desktop Environment:        1,200 MB
├── Python Runtime & Core Pipeline:          350 MB
├── EasyOCR Weights & PyTorch Engine:        750 MB
├── PaddleOCR 3.x Det/Rec Engines:           550 MB
├── TrOCR VisionEncoderDecoder Weights:      650 MB
├── TTS Synthesizer (Coqui / eSpeak):        400 MB
└── Dynamic Working Memory (Frames/Tensors): 800 MB
────────────────────────────────────────────────────
Peak Projected Consumption:                ~4,700 MB (Comfortably within 8,192 MB)
```

**Memory Safety Rules:**
1. Maintain `ocr.serialize_engines: true` so two OCR models never execute concurrently.
2. Maintain `ocr.preload: "primary"` so heavy fallback models load only on demand.
3. Retain swap space: 4 GB zRAM swap configured on JetPack.

---

## 4. Software Dependencies & Installation Plan (aarch64)

Standard PyPI `torch` wheels do not support Jetson GPU acceleration. The installation sequence on JetPack 5.x / 6.x:

```bash
# 1. System packages
sudo apt update && sudo apt install -y python3-pip python3-dev libopenblas-dev \
    libopenmpi-dev libomp-dev tesseract-ocr tesseract-ocr-hin tesseract-ocr-kan \
    espeak-ng libsndfile1 ffmpeg

# 2. NVIDIA PyTorch & Torchvision Wheels (Jetson pre-built)
# Example for JetPack 5.1 (PyTorch 2.0.0 aarch64):
wget https://developer.download.nvidia.com/compute/redist/jp/v512/pytorch/torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl
pip install torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl

# 3. Paddle Inference for aarch64
# If prebuilt aarch64 Paddle wheel is absent, disable PaddleOCR in config:
# ocr.engines.paddle.enabled: false

# 4. Install project requirements
pip install -r requirements.txt
```

---

## 5. Offline Model Storage Plan

Models must be pre-populated on the Jetson flash storage (NVMe SSD recommended; eMMC has limited endurance and speed):

- EasyOCR models: `/home/jetson/.EasyOCR/model/`
- TrOCR model: `/home/jetson/.cache/huggingface/hub/models--microsoft--trocr-base-handwritten/`
- PaddleOCR models: `/home/jetson/.paddlex/official_models/`
- Coqui VITS models: `/home/jetson/.local/share/tts/tts_models--en--vctk--vits/`

Environment flags enforced by `core/offline.py`:
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1`.

---

## 6. Expected Latency Projections (Target Estimates)

| Stage | Development Machine (Intel x86 CPU) | Projected Jetson Orin Nano (GPU Accelerated) |
| :--- | :--- | :--- |
| **CSI Camera Acquisition** | 15 ms | < 5 ms (Zero-copy NVMM) |
| **Motion Gating** | 1.5 ms | < 1 ms |
| **Printed Text OCR (EasyOCR)** | 4.0 s – 5.0 s (CPU) | **~350 ms – 600 ms (TensorRT/CUDA)** |
| **Handwriting OCR (TrOCR)** | 4.5 s – 6.0 s (CPU) | **~400 ms – 700 ms (CUDA fp16)** |
| **TTS Speech Start (eSpeak)** | ~25 ms | ~25 ms |
| **TTS Speech Start (Coqui)** | ~750 ms (CPU) | ~150 ms (CUDA) |
| **Total Turnaround Time** | **~4.5 s – 6.0 s** | **~0.8 s – 1.5 s** |

*Conclusion:* The architecture is fully prepared for Jetson migration, but must be profiled directly on the device using NVMM and TensorRT before classroom pilot validation.
