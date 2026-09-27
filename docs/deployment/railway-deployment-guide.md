# Railway Deployment Guide — Smart Vision Assist v2.0.4

This document outlines how to deploy **Smart Vision Assist v2.0.4** to [Railway](https://railway.com / https://railway.app).

---

## 1. Overview of Railway Support Files

The repository now contains all configuration files required for Railway's deployment lifecycle:

| File | Purpose |
| :--- | :--- |
| [`railway.json`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/railway.json) | Railway configuration schema: defines the builder (`NIXPACKS`), start command, and health check parameters. |
| [`Procfile`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/Procfile) | Declares the primary web dyno process (`web: python app.py`). |
| [`nixpacks.toml`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/nixpacks.toml) | Configures Railway's Nixpacks builder with required C/C++ runtime libraries, `espeak-ng`, `tesseract`, `ffmpeg`, `libGL`, and audio drivers. |
| [`Dockerfile`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/Dockerfile) | Alternative / fallback container build with Debian Slim, installing system packages and caching wheels. |
| [`.dockerignore`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/.dockerignore) | Excludes local virtual environments, test caches, and git history from the build context. |
| [`app.py`](file:///d:/NAIN%202.0%20(Main)/assistive-ocr-tts%20v2.0.4/app.py) | Dynamic port binding via `os.environ.get("PORT", 8000)` so Railway can route traffic through its reverse proxy. |

---

## 2. Step-by-Step Deployment on Railway

### Step 1: Push Code to GitHub
Push your repository changes to your remote GitHub repository:
```bash
git add .
git commit -m "feat(deployment): configure Railway deployment files and dynamic PORT binding"
git push origin main
```

### Step 2: Create a New Project on Railway
1. Log in to [Railway](https://railway.com).
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select your repository (`assistive-ocr-tts`).

### Step 3: Configure Environment Variables (Railway Dashboard)
In your Railway service settings under the **Variables** tab, set:
- `PYTHONUNBUFFERED`: `1`
- `TTS_ENGINE`: `espeak` (or `coqui`, since Windows SAPI is not present on Linux servers)
- *(Optional)* `OCR_MODE`: `fallback`

> [!NOTE]
> Railway automatically sets and injects the `PORT` environment variable. `app.py` automatically binds to `0.0.0.0:$PORT`.

### Step 4: Health Check Configuration
Railway will use the settings in `railway.json`:
- **Path:** `/api/status`
- **Timeout:** `300` seconds (to allow PyTorch and OCR weights to initialize on first boot)

---

## 3. Cloud Container Considerations (Camera & Audio)

When deployed on a cloud container host like Railway:
1. **Physical Webcam:** Cloud servers do not have an onboard USB webcam.
   - The system's API endpoints (`/api/status`, `/api/test-camera`, `/api/camera/snapshot`, `/api/test-ocr`) are fully operational.
   - For real-world remote feeds, set `"source_type": "gstreamer"` or an RTSP/IP camera stream URL in `config.json` or through the dashboard Settings UI.
2. **Audio Output:**
   - On a cloud server without physical speakers, active speech is synthesized into WAV audio buffers.
   - The `/api/replay` and browser Web Audio endpoints stream the synthesized audio directly to the user's browser for playback.
