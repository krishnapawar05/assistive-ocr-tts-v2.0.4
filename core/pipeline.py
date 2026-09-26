import threading
import time
import queue
import cv2
import logging
from typing import Dict, Any
from .ocr_engine import OCREngine, OCRResult
from .tts_engine import TTSEngine

logger = logging.getLogger("pipeline")


class AssistivePipeline:
    def __init__(self, config):
        self.config = config
        self.cfg = config.data
        self.ocr = OCREngine(self.cfg["ocr"])
        self.tts = TTSEngine(self.cfg["tts"])
        self.frame_q = queue.Queue(maxsize=1)
        self.text_q = queue.Queue()
        self.history = []
        self.lock = threading.Lock()
        self.running = False
        self.threads = []
        self.last_text = ""

    def start(self):
        if self.running:
            return
        self.running = True
        tcap = threading.Thread(target=self._capture_loop, name="capture", daemon=True)
        tproc = threading.Thread(target=self._process_loop, name="process", daemon=True)
        ttts = threading.Thread(target=self._tts_loop, name="tts", daemon=True)
        self.threads = [tcap, tproc, ttts]
        for t in self.threads:
            t.start()
        logger.info("Pipeline started")

    def stop(self):
        self.running = False
        try:
            self.frame_q.put(None, timeout=0.1)
        except queue.Full:
            pass
        try:
            self.text_q.put(None, timeout=0.1)
        except queue.Full:
            pass
        for t in self.threads:
            t.join(timeout=1)
        logger.info("Pipeline stopped")

    def _get_capture_source(self):
        cam_cfg = self.cfg["camera"]
        if cam_cfg.get("source_type") == "gstreamer":
            return (
                "nvarguscamerasrc ! video/x-raw(memory:NVMM), "
                f"width={self.cfg['camera'].get('width', 1920)}, "
                f"height={self.cfg['camera'].get('height', 1080)}, "
                "framerate=30/1 ! nvvidconv ! videoconvert ! appsink"
            )
        return int(cam_cfg.get("camera_id", 0))

    def _capture_loop(self):
        cap_source = self._get_capture_source()
        cap = cv2.VideoCapture(cap_source)
        interval = max(0.05, float(self.cfg["ocr"].get("capture_interval", 0.1)))
        last_push = 0.0

        if isinstance(cap_source, int) and cap.isOpened():
            res = self.cfg["camera"].get("resolution", "720p")  # Use 720p for speed
            if res == "1080p":
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            else:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            logger.error("Camera open failed")
            self.running = False
            return

        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            
            now = time.time()
            if now - last_push < interval:
                continue
            last_push = now
            
            try:
                if self.frame_q.full():
                    _ = self.frame_q.get_nowait()
                self.frame_q.put_nowait(frame)
            except queue.Full:
                pass
            except Exception:
                pass
        
        cap.release()

    def _process_loop(self):
        min_len = int(self.cfg["ocr"].get("min_text_len", 3))
        min_conf = float(self.cfg["ocr"].get("min_confidence", 0.5))
        last_text = ""
        last_time = 0
        frame_count = 0
        
        while self.running:
            try:
                frame = self.frame_q.get(timeout=0.3)  # Faster timeout for responsiveness
                if frame is None:
                    break

                frame_count += 1
                ocr_res: OCRResult = self.ocr.extract_text(frame)
                text = (ocr_res.text or "").strip()

                if not text or len(text) < min_len:
                    continue
                
                if ocr_res.confidence < min_conf:
                    continue

                # Simple duplicate check (fast) - allow same text after 1.5 seconds
                now = time.time()
                if text == last_text and (now - last_time < 1.5):
                    continue

                # Save to history and update status immediately
                with self.lock:
                    self.history.append({
                        "ts": now,
                        "text": text,
                        "engine": ocr_res.engine,
                        "confidence": ocr_res.confidence
                    })
                    if len(self.history) > self.cfg["app"].get("max_history", 50):
                        self.history.pop(0)

                last_text = text
                last_time = now
                self.last_text = text
                self.text_q.put(text)
                
            except queue.Empty:
                continue
            except Exception:
                continue

    def _tts_loop(self):
        while self.running:
            try:
                text = self.text_q.get(timeout=0.5)
                if text is None:
                    break
                self.tts.speak(
                    text,
                    voice=self.cfg["tts"].get("voice"),
                    speed=self.cfg["tts"].get("speed", 1.0),
                    volume=self.cfg["tts"].get("volume", 0.9),
                )
            except queue.Empty:
                continue
            except Exception:
                continue

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "last_text": self.last_text,
            "history_count": len(self.history),
        }

    def get_history(self):
        with self.lock:
            return list(self.history)[::-1]
