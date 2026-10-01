# app.py
import gc
import hashlib
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.camera.base import CameraError
from core.camera.opencv_camera import create_camera
from core.config import Config, ConfigError
from core.offline import apply_offline_env
from core.status import EngineStatus

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.environ.get("SVA_CONFIG") or os.path.join(BASE_DIR, "config.json")

try:
    cfg = Config(CONFIG_PATH)
except ConfigError as e:
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger("assistive_app").error("%s\nFix %s and restart.", e, CONFIG_PATH)
    sys.exit(2)

logging.basicConfig(
    level=getattr(logging, cfg.data["app"]["log_level"]),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("assistive_app")
apply_offline_env(cfg.data["app"]["offline_mode"])  # before any model library is imported

# ── Environment detection ──────────────────────────────────────────────────────
IS_CLOUD = bool(
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RAILWAY_PROJECT_ID")
    or os.environ.get("ENVIRONMENT", "").lower() == "railway"
)
IS_JETSON = bool(
    os.environ.get("SVA_JETSON")
    or os.path.exists("/etc/nv_tegra_release")   # Jetson-specific file
)

if IS_CLOUD:
    # Railway: no physical camera, no Windows TTS, no GPU — use tesseract + espeak
    logger.info("Railway cloud environment detected — applying lightweight config overrides")
    ocr = cfg.data["ocr"]
    ocr["engine"] = "tesseract"
    ocr["fallback_order"] = ["tesseract"]
    ocr["serialize_engines"] = False
    ocr["preload"] = "primary"
    ocr["capture_interval"] = 0.5
    ocr["min_confidence"] = 0.50
    ocr["min_text_len"] = 3
    ocr["accept_score"] = 0.70
    ocr["min_final_score"] = 0.50
    ocr["latency_budget_s"] = 8.0
    ocr["engines"]["tesseract"]["timeout_s"] = 8.0
    ocr["engines"]["easyocr"]["enabled"] = False
    ocr["engines"]["paddle"]["enabled"] = False
    ocr["engines"]["trocr"]["enabled"] = False
    ocr["duplicates"]["cooldown_s"] = 5.0
    cfg.data["tts"]["engine"] = "espeak"
    cfg.data["tts"]["fallback_engines"] = ["espeak"]

elif IS_JETSON:
    # Jetson Orin Nano: GPU available → EasyOCR+CUDA, Coqui neural TTS
    logger.info("NVIDIA Jetson environment detected — applying GPU-accelerated config overrides")
    ocr = cfg.data["ocr"]
    ocr["engine"] = "easyocr"
    ocr["fallback_order"] = ["easyocr", "tesseract"]
    ocr["serialize_engines"] = False
    ocr["preload"] = "primary"
    ocr["capture_interval"] = 0.5
    ocr["min_confidence"] = 0.50
    ocr["min_text_len"] = 3
    ocr["accept_score"] = 0.70
    ocr["min_final_score"] = 0.50
    ocr["latency_budget_s"] = 6.0
    ocr["engines"]["easyocr"]["enabled"] = True
    ocr["engines"]["easyocr"]["gpu"] = True      # CUDA via Jetson PyTorch wheel
    ocr["engines"]["easyocr"]["timeout_s"] = 6.0
    ocr["engines"]["paddle"]["enabled"] = False   # save RAM; easyocr+GPU is sufficient
    ocr["engines"]["trocr"]["enabled"] = False
    ocr["duplicates"]["cooldown_s"] = 5.0
    cfg.data["tts"]["engine"] = "coqui"
    cfg.data["tts"]["fallback_engines"] = ["coqui", "espeak"]
    cfg.data["app"]["offline_mode"] = True        # guarantee no phone-home
# ──────────────────────────────────────────────────────────────────────────────

from core.frame.processing import FrameError  # noqa: E402
from core.pipeline import AssistivePipeline  # noqa: E402


@asynccontextmanager
async def lifespan(_app):
    yield
    if pipeline is not None:
        pipeline.shutdown()  # stop camera, OCR workers and audio on server exit


app = FastAPI(title="Assistive OCR→TTS", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _asset_version(name: str) -> str:
    """Content hash appended to static URLs. StaticFiles sends no Cache-Control, so browsers
    cache heuristically and could keep running an old dashboard.js against a new server."""
    with open(os.path.join(STATIC_DIR, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


ASSET_VERSIONS = {name: _asset_version(name) for name in ("dashboard.js", "style.css")}

pipeline: Optional[AssistivePipeline] = None
_reload_lock = threading.Lock()
_pipeline_ready = threading.Event()
_pipeline_error: Optional[str] = None


def _init_pipeline_bg():
    global pipeline, _pipeline_error
    try:
        logger.info("Initializing AssistivePipeline in background...")
        p = AssistivePipeline(cfg)
        pipeline = p
        logger.info("AssistivePipeline ready.")
    except Exception as e:
        _pipeline_error = str(e)
        logger.exception("AssistivePipeline initialization failed: %s", e)
    finally:
        _pipeline_ready.set()


_init_thread = threading.Thread(target=_init_pipeline_bg, name="pipeline-init", daemon=True)
_init_thread.start()


def current() -> AssistivePipeline:
    """The live pipeline, or wait if initializing, or HTTP 503 if reloading or failed."""
    global pipeline
    if pipeline is None:
        if not _pipeline_ready.is_set():
            _pipeline_ready.wait(timeout=30.0)
        if _pipeline_error is not None:
            raise HTTPException(status_code=500, detail=f"Pipeline initialization failed: {_pipeline_error}")
        if pipeline is None:
            raise HTTPException(status_code=503, detail="Pipeline initializing, try again shortly")
    return pipeline


@app.get("/health")
def health():
    """Fast, lightweight healthcheck endpoint for Railway and container orchestrators.
    Never blocks on models, camera, or audio hardware."""
    is_cloud = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID") or os.environ.get("ENVIRONMENT", "").lower() == "railway")
    return {
        "status": "ok",
        "environment": "railway" if is_cloud else os.environ.get("ENVIRONMENT", "local"),
        "pipeline_ready": pipeline is not None
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    p = current()
    # Engines that cannot run (unavailable or failed); READY and not-yet-loaded ones are usable.
    unusable = {name: d["status"] for name, d in p.diagnostics()["ocr_engines"].items()
                if d["status"] not in (EngineStatus.READY.value, EngineStatus.UNINITIALIZED.value)}
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "config": cfg.data, "voices": p.voices(), "assets": ASSET_VERSIONS,
        "unusable_ocr": unusable, "is_cloud": IS_CLOUD})


@app.post("/api/process-frame")
async def api_process_frame(request: Request):
    """Process an image frame submitted by the client (browser camera mode).
    Accepts JSON with base64 image or raw image binary."""
    import base64
    import cv2
    import numpy as np

    p = current()
    content_type = request.headers.get("content-type", "")

    img_bytes = None
    if "application/json" in content_type:
        try:
            payload = await request.json()
            b64_data = payload.get("image", "")
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_data)
        except Exception as e:
            return JSONResponse({"status": "error", "message": f"invalid JSON/base64: {e}"}, status_code=400)
    else:
        img_bytes = await request.body()

    if not img_bytes:
        return JSONResponse({"status": "error", "message": "no image data provided"}, status_code=400)

    np_arr = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"status": "error", "message": "could not decode image"}, status_code=400)

    outcome = p.process_frame(frame)
    return JSONResponse({
        "status": outcome.status,
        "text": outcome.text or "",
        "engine": outcome.engine or "",
        "confidence": round(outcome.confidence, 3) if outcome.confidence else 0.0,
        "details": outcome.details
    })


@app.post("/api/start")
async def api_start():
    p = current()
    p.start()
    return JSONResponse({"status": "started", "pipeline": p.get_status()})


@app.post("/api/stop")
async def api_stop():
    p = current()
    p.stop()
    return JSONResponse({"status": "stopped", "pipeline": p.get_status()})


@app.get("/api/status")
async def api_status():
    return JSONResponse({"status": "ok", "pipeline": current().get_status()})


@app.get("/api/history")
async def api_history():
    return JSONResponse({"history": current().get_history()})


@app.get("/api/config")
async def api_get_config():
    return JSONResponse(cfg.data)


@app.post("/api/config")
def api_update_config(payload: dict):
    global pipeline
    if not _reload_lock.acquire(blocking=False):
        return JSONResponse({"status": "error", "message": "A configuration reload is already running"},
                            status_code=409)
    try:
        try:
            cfg.update(payload)
        except ConfigError as e:
            return JSONResponse({"status": "error", "message": "Invalid configuration", "errors": e.errors},
                                status_code=400)
        was_running = pipeline.running if pipeline is not None else False
        if pipeline is not None:
            pipeline.shutdown()
        # Release the old models before loading new ones: holding both can exhaust RAM on 8 GB
        # devices. Requests during the rebuild get HTTP 503 from current().
        pipeline = None
        gc.collect()
        try:
            pipeline = AssistivePipeline(cfg)
        except Exception:
            logger.exception("pipeline rebuild failed")
            return JSONResponse({"status": "error", "message": "Settings saved but the pipeline failed to start; "
                                 "see server log"}, status_code=500)
        if was_running:
            pipeline.start()
        return JSONResponse({"status": "saved", "config": cfg.data})
    finally:
        _reload_lock.release()


@app.post("/api/speak")
async def api_speak(payload: dict):
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"status": "error", "message": "no text"}, status_code=400)
    result = current().speak(text)
    if result in ("queued", "interrupting"):
        return JSONResponse({"status": "speaking", "audio": result})
    return JSONResponse({"status": "error", "message": f"speech not accepted ({result})"}, status_code=503)


@app.get("/api/replay")
async def api_replay():
    wav = current().last_audio_wav()
    if wav:
        return Response(content=wav, media_type="audio/wav",
                        headers={"Content-Disposition": 'inline; filename="last_audio.wav"'})
    return JSONResponse({"status": "no_audio", "message": "No synthesized audio yet (replay needs Coqui TTS)"},
                        status_code=404)


@app.post("/api/stop-speech")
async def api_stop_speech():
    """Immediately silence active speech and clear the pending audio queue."""
    current().stop_speech()
    return JSONResponse({"status": "stopped", "message": "Speech stopped and queue cleared"})


@app.post("/api/replay-latest")
async def api_replay_latest():
    """Re-speak the most recent recognized text through TTS."""
    p = current()
    text = p.last_text
    if not text:
        return JSONResponse({"status": "no_text", "message": "No recognized text to replay yet"}, status_code=404)
    result = p.speak(text)
    return JSONResponse({"status": "replaying", "text": text, "audio": result})


_camera_lock = threading.Lock()


def _grab_frame(p: Optional[AssistivePipeline] = None):
    """Read one frame for diagnostics or preview.
    If the pipeline is running, borrow the most recent captured frame without disrupting the stream."""
    pipeline_inst = p if p is not None else current()
    if pipeline_inst.running:
        if pipeline_inst.controller is not None:
            # Wait up to 2.5 seconds for the streaming controller to yield its first frame if connecting
            for _ in range(5):
                captured = pipeline_inst.controller.get_current_frame()
                if captured is not None and getattr(captured, "image", None) is not None:
                    return captured.image.copy()
                time.sleep(0.5)
            state = pipeline_inst.controller.state
            err = pipeline_inst.controller.last_error
            raise CameraError(f"camera is in use by pipeline ({state}{f': {err}' if err else ''})")
        raise CameraError("camera is initializing in pipeline")

    with _camera_lock:
        if pipeline_inst.running:
            raise CameraError("camera is in use by pipeline")
        camera = create_camera(cfg.data["camera"])
        camera.open()
        try:
            frame = camera.read()
        finally:
            camera.close()
        if frame is None:
            raise CameraError("camera opened but returned no frame")
        return frame


@app.get("/api/test-camera")
def api_test_camera():
    """Test if camera is accessible and can capture frames."""
    try:
        frame = _grab_frame()
    except CameraError as e:
        return JSONResponse({"status": "error", "message": str(e)})
    return JSONResponse({"status": "ok", "message": f"Camera {cfg.data['camera']['camera_id']} working",
                         "frame_shape": list(frame.shape)})


@app.get("/api/camera/snapshot")
def api_camera_snapshot():
    """Return a JPEG snapshot of the camera's current frame for the UI viewfinder."""
    import cv2
    try:
        frame = _grab_frame()
        # Resize thumbnail for efficient browser rendering if large
        h, w = frame.shape[:2]
        if max(h, w) > 960:
            scale = 960.0 / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            raise CameraError("failed to encode JPEG")
        return Response(content=buf.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=503)


def _test_ocr_on_frame(p: AssistivePipeline) -> dict:
    """Grab one frame and run the configured OCR on it. Distinguishes: no usable frame
    ("error"), and via "reason": selected, no_text, below_min_confidence, below_threshold,
    no_engine_available, all_engines_failed."""
    t0 = time.perf_counter()
    try:
        frame = _grab_frame()
        report = p.quality.assess(frame)  # raises FrameError for an invalid frame
        prepared = p.preprocessor.prepare(frame)
    except (CameraError, FrameError) as e:
        logger.info("test-ocr: no usable frame: %s", e)
        return {"error": str(e)}
    frame_info = {"shape": list(frame.shape), "dtype": str(frame.dtype), "min": int(frame.min()),
                  "max": int(frame.max()), "mean": round(float(frame.mean()), 1),
                  "prepared_shape": list(prepared.gray.shape)}
    logger.info("test-ocr: frame shape=%s dtype=%s min=%d max=%d mean=%.1f prepared=%s quality=%s",
                frame_info["shape"], frame_info["dtype"], frame_info["min"], frame_info["max"],
                frame_info["mean"], frame_info["prepared_shape"], "ok" if report.usable else report.reasons)
    decision = p.ocr.recognize(prepared)
    winner = decision.winner
    latency = time.perf_counter() - t0
    logger.info("test-ocr: primary=%s mode=%s engines_run=%s errors=%s low_confidence=%s skipped=%s reason=%s "
                "engine=%s confidence=%.2f score=%.2f latency=%.2fs", p.ocr.cfg["engine"], p.ocr.mode,
                decision.engines_run, decision.errors, decision.low_confidence, decision.skipped, decision.reason,
                winner.result.engine if winner else "-", winner.result.confidence if winner else 0.0,
                winner.final_score if winner else 0.0, latency)
    for c in decision.candidates:  # recognized text: DEBUG only (privacy)
        logger.debug("test-ocr: candidate %s raw=%r conf=%.2f score=%.2f", c.result.engine, c.result.text,
                     c.result.confidence, c.final_score)
    logger.debug("test-ocr: accepted text=%r", decision.text)
    return {
        "text": decision.text[:100],
        "engine": winner.result.engine if winner else "",
        "confidence": round(winner.result.confidence, 3) if winner else 0.0,
        "score": round(winner.final_score, 3) if winner else 0.0,
        "reason": decision.reason,
        "engines_run": decision.engines_run,
        "errors": decision.errors,
        "low_confidence": {k: round(v, 3) for k, v in decision.low_confidence.items()},
        "skipped": decision.skipped,
        "region_source": decision.region_source,
        "candidates": [{"engine": c.result.engine, "text": c.cleaned_text[:100],
                        "confidence": round(c.result.confidence, 3), "score": round(c.final_score, 3)}
                       for c in decision.candidates if c is not winner],
        "frame_quality": {"usable": report.usable, "reasons": report.reasons},
        "frame": frame_info,
        "latency_s": round(latency, 2),
    }


@app.get("/api/test-ocr")
def api_test_ocr():
    """Report every OCR/TTS engine's status and run OCR once on a camera frame if possible."""
    p = current()
    frame_result = _test_ocr_on_frame(p)
    diag = p.diagnostics()  # after OCR, so lazily loaded fallback engines show their real state
    ocr_cfg = cfg.data["ocr"]
    return JSONResponse({
        "status": "ok",
        "engines": {name: d["status"] == "READY" for name, d in diag["ocr_engines"].items()},
        "ocr_engines": diag["ocr_engines"],
        "tts_engines": diag["tts_engines"],
        "ocr_test_on_frame": frame_result,
        "config": {"mode": ocr_cfg["mode"], "engine": ocr_cfg["engine"],
                   "min_confidence": ocr_cfg["min_confidence"], "min_text_len": ocr_cfg["min_text_len"],
                   "min_final_score": ocr_cfg["min_final_score"]},
    })


if __name__ == "__main__":
    # Pass the app object, not "app:app": the import string makes uvicorn import this file a
    # second time as module "app", which built a second pipeline (EasyOCR + Coqui loaded twice).
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
