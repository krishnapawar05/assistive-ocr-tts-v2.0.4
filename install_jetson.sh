#!/usr/bin/env bash
# install_jetson.sh — Smart Vision Assist setup for NVIDIA Jetson Orin Nano
# Tested on: JetPack 6.x (Ubuntu 22.04, aarch64, CUDA 12.x, Python 3.10)
#
# Usage:
#   chmod +x install_jetson.sh
#   ./install_jetson.sh
#
# After install:
#   python app.py          → serves at http://0.0.0.0:8000
#   Access from any device on the same WiFi: http://<jetson-ip>:8000

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Smart Vision Assist — Jetson Orin Nano Setup"
echo "  Platform: $(uname -m) | JetPack: $(cat /etc/nv_tegra_release 2>/dev/null | head -1 || echo 'unknown')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. System packages ────────────────────────────────────────────────────────
echo ""
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    espeak-ng \
    espeak-ng-data \
    libsndfile1 \
    portaudio19-dev \
    libportaudio2 \
    ffmpeg \
    libglib2.0-0 \
    libgl1 \
    curl

echo "  ✓ System packages installed"

# ── 2. Python venv ────────────────────────────────────────────────────────────
echo ""
echo "[2/6] Creating Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv --system-site-packages
    # system-site-packages gives us JetPack's GPU-enabled OpenCV + CUDA libs
fi
source .venv/bin/activate
pip install --upgrade pip --quiet
echo "  ✓ venv at .venv (system-site-packages enabled for GPU OpenCV)"

# ── 3. PyTorch for Jetson (NVIDIA wheel) ─────────────────────────────────────
echo ""
echo "[3/6] Installing PyTorch for Jetson Orin (aarch64 CUDA)..."
TORCH_INSTALLED=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null || true)
if [ -n "$TORCH_INSTALLED" ]; then
    echo "  ✓ PyTorch $TORCH_INSTALLED already installed"
else
    # NVIDIA Jetson PyTorch wheel — check https://developer.nvidia.com/embedded/jetson-linux for latest
    TORCH_WHL="https://developer.download.nvidia.com/compute/redist/jp/v60dp/pytorch/torch-2.3.0a0+ebedce2.nv24.05-cp310-cp310-linux_aarch64.whl"
    echo "  Downloading NVIDIA Jetson PyTorch wheel..."
    pip install "$TORCH_WHL" --quiet || {
        echo "  ⚠ NVIDIA wheel failed. Trying PyPI torch (CPU only, slower OCR)..."
        pip install torch --quiet
    }
    echo "  ✓ PyTorch installed"
fi

# ── 4. App requirements ───────────────────────────────────────────────────────
echo ""
echo "[4/6] Installing Smart Vision Assist dependencies..."
pip install -r requirements-jetson.txt --quiet
echo "  ✓ Dependencies installed"

# ── 5. Download TTS model (offline cache) ────────────────────────────────────
echo ""
echo "[5/6] Pre-downloading Coqui TTS model for offline use..."
TTS_MODEL_DIR="$HOME/.local/share/tts/tts_models--en--vctk--vits"
if [ -d "$TTS_MODEL_DIR" ]; then
    echo "  ✓ TTS model already cached at $TTS_MODEL_DIR"
else
    python3 -c "
from TTS.api import TTS
import os
os.environ['COQUI_TOS_AGREED'] = '1'
print('  Downloading tts_models/en/vctk/vits (one-time, ~350MB)...')
TTS('tts_models/en/vctk/vits')
print('  ✓ TTS model cached')
" || echo "  ⚠ TTS model download failed — will use eSpeak fallback"
fi

# ── 6. Write Jetson config ────────────────────────────────────────────────────
echo ""
echo "[6/6] Writing Jetson-optimised config..."
if [ ! -f "config.json" ] || grep -q '"engine": "easyocr"' config.json; then
    python3 - <<'PYEOF'
import json, os

with open("config.json") as f:
    cfg = json.load(f)

# OCR: EasyOCR with GPU
cfg["ocr"]["engine"] = "easyocr"
cfg["ocr"]["fallback_order"] = ["easyocr", "tesseract"]
cfg["ocr"]["serialize_engines"] = False
cfg["ocr"]["preload"] = "primary"
cfg["ocr"]["capture_interval"] = 0.5
cfg["ocr"]["min_confidence"] = 0.20
cfg["ocr"]["latency_budget_s"] = 6.0
cfg["ocr"]["engines"]["easyocr"]["enabled"] = True
cfg["ocr"]["engines"]["easyocr"]["gpu"] = True       # USE JETSON GPU
cfg["ocr"]["engines"]["easyocr"]["timeout_s"] = 6.0
cfg["ocr"]["engines"]["paddle"]["enabled"] = False   # disable to save RAM
cfg["ocr"]["engines"]["trocr"]["enabled"] = False
cfg["ocr"]["duplicates"]["cooldown_s"] = 5.0

# TTS: Coqui neural voice with GPU
cfg["tts"]["engine"] = "coqui"
cfg["tts"]["fallback_engines"] = ["coqui", "espeak"]
cfg["tts"]["coqui_model"] = "tts_models/en/vctk/vits"
cfg["tts"]["voice"] = "p335"
cfg["tts"]["speed"] = 1.0

# App
cfg["app"]["offline_mode"] = True
cfg["app"]["log_level"] = "INFO"

with open("config.json", "w") as f:
    json.dump(cfg, f, indent=2)

print("  ✓ config.json updated for Jetson (EasyOCR GPU + Coqui TTS)")
PYEOF
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Setup complete!"
echo ""
JETSON_IP=$(hostname -I | awk '{print $1}')
echo "  Start:         source .venv/bin/activate && python app.py"
echo "  Local access:  http://localhost:8000"
echo "  LAN access:    http://${JETSON_IP}:8000"
echo ""
echo "  From any phone/tablet on the same WiFi:"
echo "  → Open http://${JETSON_IP}:8000 in Safari or Chrome"
echo "  → Press Start Reading — your device camera sends frames to"
echo "    the Jetson for GPU-accelerated OCR, text is read aloud"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
