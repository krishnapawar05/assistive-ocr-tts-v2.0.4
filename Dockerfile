# Dockerfile — Railway container deployment for Smart Vision Assist
FROM python:3.10-slim

# Prevent interactive prompts and write logs unbuffered
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system dependencies for OpenCV, audio, TTS, and OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libasound2-dev \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    espeak-ng \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose web port
EXPOSE 8000

# Healthcheck targeting the API status endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/status || exit 1

# Start the application
CMD ["python", "app.py"]
