# Dockerfile — Railway container deployment for Smart Vision Assist
FROM python:3.10-slim

# Prevent interactive prompts and write logs unbuffered
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    # Tell app it is running on Railway — switches OCR to tesseract, TTS to espeak
    RAILWAY_ENVIRONMENT=production \
    # Suppress offline-mode model downloads
    DISABLE_MODEL_SOURCE_CHECK=1 \
    # eSpeak data path
    ESPEAK_DATA_PATH=/usr/lib/x86_64-linux-gnu/espeak-ng-data

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV headless runtime
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    # OCR — Tesseract with English data
    tesseract-ocr \
    tesseract-ocr-eng \
    # TTS — eSpeak NG
    espeak-ng \
    # Audio helpers (for soundfile)
    libsndfile1 \
    # Health check
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements-railway.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-railway.txt

# Copy application source
COPY . .

# Expose web port
EXPOSE 8000

# Healthcheck — /health returns 200 immediately even before models load
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start application
CMD ["python", "app.py"]
