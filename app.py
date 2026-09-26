# app.py
import uvicorn
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import logging
import os

from core.config import Config
from core.pipeline import AssistivePipeline
try:
    from core.ocr_engine import TESSER_AVAILABLE
except ImportError:
    TESSER_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("assistive_app")

app = FastAPI(title="Assistive OCR→TTS")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

cfg = Config(os.path.join(BASE_DIR, "config.json"))
pipeline = AssistivePipeline(cfg)

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    voices = []
    if pipeline.tts.coqui and hasattr(pipeline.tts.coqui, 'speakers') and pipeline.tts.coqui.speakers:
        voices = pipeline.tts.coqui.speakers
    return templates.TemplateResponse("dashboard.html", {"request": request, "config": cfg.data, "voices": voices})

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
async def api_update_config(payload: dict):
    global pipeline
    cfg.update(payload)
    pipeline.stop()
    pipeline = AssistivePipeline(cfg)
    pipeline.start()
    return JSONResponse({"status": "saved", "config": cfg.data})


@app.post("/api/speak")
async def api_speak(payload: dict):
    text = payload.get("text", "")
    if text:
        pipeline.tts.speak(text,
                          voice=cfg.data["tts"].get("voice"),
                          speed=cfg.data["tts"].get("speed",1.0),
                          volume=cfg.data["tts"].get("volume",0.9))
        return JSONResponse({"status": "speaking"})
    return JSONResponse({"status": "error", "message": "no text"}, status_code=400)

@app.get("/api/replay")
async def api_replay():
    # return last audio file if available
    last = pipeline.tts.last_audio_path
    if last and os.path.exists(last):
        return FileResponse(last, media_type="audio/wav", filename="last_audio.wav")
    return JSONResponse({"status":"no_audio"}, status_code=404)

@app.get("/api/test-camera")
async def api_test_camera():
    """Test if camera is accessible and can capture frames."""
    import cv2
    try:
        cam_id = cfg.data["camera"].get("camera_id", 0)
        cap = cv2.VideoCapture(cam_id)
        if not cap.isOpened():
            return JSONResponse({"status": "error", "message": f"Camera {cam_id} cannot be opened"})
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            return JSONResponse({
                "status": "ok", 
                "message": f"Camera {cam_id} working",
                "frame_shape": list(frame.shape)
            })
        else:
            return JSONResponse({"status": "error", "message": "Camera opened but cannot read frames"})
    except Exception as e:
        logger.exception("Camera test failed")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/api/test-ocr")
async def api_test_ocr():
    """Test OCR engine initialization - optimized version."""
    # Check Tesseract availability
    tesseract_module_available = False
    tesseract_executable_available = False
    tesseract_error = None
    
    try:
        import pytesseract
        tesseract_module_available = True
        try:
            pytesseract.get_tesseract_version()
            tesseract_executable_available = True
        except Exception as e:
            tesseract_executable_available = False
            tesseract_error = f"Module installed but executable not found: {str(e)}"
    except ImportError as e:
        tesseract_module_available = False
        tesseract_error = f"Module not installed: {str(e)}"
    except Exception as e:
        tesseract_error = f"Unexpected error: {str(e)}"
    
    # Simplified engines (only Tesseract now)
    engines = {
        "tesseract": tesseract_module_available and tesseract_executable_available
    }
    
    # Test Tesseract with a simple image
    tesseract_works = False
    tesseract_test_result = ""
    if tesseract_module_available and tesseract_executable_available:
        try:
            import cv2
            import numpy as np
            test_img = np.ones((100, 300, 3), dtype=np.uint8) * 255
            cv2.putText(test_img, "TEST", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            test_text = pytesseract.image_to_string(test_img, config=r'--oem 3 --psm 6').strip()
            tesseract_works = len(test_text) > 0
            tesseract_test_result = test_text if test_text else "No text detected from test image"
        except Exception as e:
            logger.error("Tesseract test failed: %s", e)
            tesseract_test_result = f"Error: {str(e)}"
    elif tesseract_error:
        tesseract_test_result = tesseract_error
    
    # Test OCR on a real camera frame if available
    ocr_test_result = None
    try:
        import cv2
        cam_id = cfg.data["camera"].get("camera_id", 0)
        cap = cv2.VideoCapture(cam_id)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                ocr_res = pipeline.ocr.extract_text(frame)
                ocr_test_result = {
                    "text": ocr_res.text[:100] if ocr_res.text else "",
                    "engine": ocr_res.engine,
                    "confidence": ocr_res.confidence,
                    "length": len(ocr_res.text) if ocr_res.text else 0
                }
    except Exception as e:
        logger.error("OCR test on camera frame failed: %s", e)
        ocr_test_result = {"error": str(e)}
    
    return JSONResponse({
        "status": "ok",
        "engines": engines,
        "tesseract_works": tesseract_works,
        "tesseract_test_result": tesseract_test_result,
        "tesseract_error": tesseract_error,
        "ocr_test_on_frame": ocr_test_result,
        "config": {
            "min_confidence": pipeline.ocr.min_confidence,
            "min_text_len": pipeline.ocr.min_text_len
        },
        "diagnostics": {
            "tesseract_module": tesseract_module_available,
            "tesseract_executable": tesseract_executable_available
        },
        "initialization_info": {
            "tesseract": "Tesseract is ready" if tesseract_executable_available else "Tesseract not available - install: pip install pytesseract and Tesseract OCR executable"
        }
    })

if __name__ == "__main__":
    # Create templates directory if missing (templates provided separately)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)