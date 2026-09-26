# app.py
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.camera.base import CameraError
from core.camera.opencv_camera import create_camera
from core.config import Config, ConfigError
from core.offline import apply_offline_env

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

from core.frame.processing import FrameError  # noqa: E402
from core.pipeline import AssistivePipeline  # noqa: E402



@asynccontextmanager
async def lifespan(_app):
    yield
    pipeline.shutdown()  # stop camera, OCR workers and audio on server exit


app = FastAPI(title="Assistive OCR→TTS", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

pipeline = AssistivePipeline(cfg)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"config": cfg.data, "voices": pipeline.voices()})


@app.post("/api/start")
async def api_start():
    pipeline.start()
    return JSONResponse({"status": "started", "pipeline": pipeline.get_status()})


@app.post("/api/stop")
async def api_stop():
    pipeline.stop()
    return JSONResponse({"status": "stopped", "pipeline": pipeline.get_status()})


@app.get("/api/status")
async def api_status():
    return JSONResponse({"status": "ok", "pipeline": pipeline.get_status()})


@app.get("/api/history")
async def api_history():
    return JSONResponse({"history": pipeline.get_history()})


@app.get("/api/config")
async def api_get_config():
    return JSONResponse(cfg.data)


@app.post("/api/config")
def api_update_config(payload: dict):
    global pipeline
    try:
        cfg.update(payload)
    except ConfigError as e:
        return JSONResponse({"status": "error", "message": "Invalid configuration", "errors": e.errors},
                            status_code=400)
    was_running = pipeline.running
    pipeline.shutdown()
    pipeline = AssistivePipeline(cfg)
    if was_running:
        pipeline.start()
    return JSONResponse({"status": "saved", "config": cfg.data})


@app.post("/api/speak")
async def api_speak(payload: dict):
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"status": "error", "message": "no text"}, status_code=400)
    result = pipeline.speak(text)
    if result in ("queued", "interrupting"):
        return JSONResponse({"status": "speaking", "audio": result})
    return JSONResponse({"status": "error", "message": f"speech not accepted ({result})"}, status_code=503)


@app.get("/api/replay")
async def api_replay():
    wav = pipeline.last_audio_wav()
    if wav:
        return Response(content=wav, media_type="audio/wav",
                        headers={"Content-Disposition": 'inline; filename="last_audio.wav"'})
    return JSONResponse({"status": "no_audio", "message": "No synthesized audio yet (replay needs Coqui TTS)"},
                        status_code=404)


def _grab_frame():
    """Read one frame for diagnostics. The pipeline owns the camera while it is running."""
    if pipeline.running:
        raise CameraError("camera is in use by the running pipeline; stop it first")
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


@app.get("/api/test-ocr")
def api_test_ocr():
    """Report every OCR/TTS engine's status and run OCR once on a camera frame if possible."""
    diag = pipeline.diagnostics()
    frame_result = None
    try:
        frame = _grab_frame()
        report = pipeline.quality.assess(frame)
        decision = pipeline.ocr.recognize(pipeline.preprocessor.prepare(frame))
        frame_result = {
            "text": decision.text[:100],
            "engine": decision.winner.result.engine if decision.winner else "",
            "confidence": round(decision.winner.result.confidence, 3) if decision.winner else 0.0,
            "score": round(decision.winner.final_score, 3) if decision.winner else 0.0,
            "reason": decision.reason,
            "engines_run": decision.engines_run,
            "errors": decision.errors,
            "frame_quality": {"usable": report.usable, "reasons": report.reasons},
        }
    except (CameraError, FrameError) as e:
        frame_result = {"error": str(e)}
    ocr_cfg = cfg.data["ocr"]
    return JSONResponse({
        "status": "ok",
        "engines": {name: d["status"] == "READY" for name, d in diag["ocr_engines"].items()},
        "ocr_engines": diag["ocr_engines"],
        "tts_engines": diag["tts_engines"],
        "ocr_test_on_frame": frame_result,
        "config": {"mode": ocr_cfg["mode"], "engine": ocr_cfg["engine"],
                   "min_confidence": ocr_cfg["min_confidence"], "min_text_len": ocr_cfg["min_text_len"]},
    })


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
