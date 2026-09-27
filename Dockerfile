# Dockerfile — Railway container deployment for Smart Vision Assist
FROM python:3.10-slim

# Prevent interactive prompts and write logs unbuffered
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system dependencies for OpenCV, TTS, and OCR
# NOTE: No audio device exists on Railway; eSpeak runs via subprocess (no PortAudio needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsndfile1 \
    ffmpeg \
    espeak-ng \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install lightweight Python dependencies (no PyTorch/PaddlePaddle/EasyOCR/Coqui)
COPY requirements-railway.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-railway.txt

# Copy application source code
COPY . .

# Expose web port
EXPOSE 8000

# Healthcheck — /health always returns 200 immediately, even before models load
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start the application
CMD ["python", "app.py"]
