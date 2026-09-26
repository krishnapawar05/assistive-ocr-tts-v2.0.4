"""AssistivePipeline: orchestrates Camera -> OCR -> text filtering -> speech.

Stages and their contracts:
  FrameController   camera frames (newest only, rate-limited, auto-reconnect)
  QualityAssessor   frame -> usable? (blank / dark / overexposed / tiny / blurred)
  ChangeDetector    skip frames that look like the last processed one
  Preprocessor      frame -> PreparedFrame (color + gray)
  OCRService        PreparedFrame -> OCRDecision (engine mode + scoring)
  DuplicateFilter   text -> new or repeat (cooldown)
  SpeechComposer    text -> utterance
  AudioManager      utterance -> one speech at a time via TTSService (engine fallback)

The public API used by app.py (start/stop/get_status/get_history) matches v2.0.4.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .audio.manager import AudioManager
from .camera.base import CameraInterface
from .camera.controller import FrameController
from .camera.opencv_camera import create_camera
from .frame.processing import ChangeDetector, FrameError, Preprocessor, QualityAssessor, validate_frame
from .ocr.service import OCRService
from .ocr.types import OCRDecision
from .offline import apply_offline_env
from .text.duplicates import DuplicateFilter
from .tts.composer import SpeechComposer
from .tts.service import TTSService

logger = logging.getLogger("pipeline")


@dataclass
class ProcessOutcome:
    """What happened to one frame. ``status`` is one of:
    invalid_frame, unusable_frame, unchanged, no_ocr_engine, ocr_failed, no_text,
    duplicate, spoken, speech_dropped."""

    status: str
    text: str = ""
    engine: str = ""
    confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    decision: Optional[OCRDecision] = None


class AssistivePipeline:
    def __init__(self, config, camera_factory: Callable[[Dict], CameraInterface] = create_camera,
                 ocr_service: Optional[OCRService] = None, tts_service: Optional[TTSService] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.cfg = config.data
        apply_offline_env(self.cfg["app"]["offline_mode"])
        self._camera_factory = camera_factory
        self._clock = clock

        frame_cfg = self.cfg["frame"]
        self.quality = QualityAssessor(frame_cfg["quality"])
        self.change = ChangeDetector(frame_cfg["change_detection"])
        self.preprocessor = Preprocessor(frame_cfg["preprocess"])
        self.ocr = ocr_service or OCRService(self.cfg["ocr"], self.cfg["text"])
        self.duplicates = DuplicateFilter(self.cfg["ocr"]["duplicates"], clock=clock)
        self.composer = SpeechComposer(self.cfg["tts"]["max_chars"])
        self.tts = tts_service or TTSService(self.cfg["tts"])
        self.audio = AudioManager(self.cfg["audio"], self.tts.speak, self.tts.stop)

        self.ocr.initialize()
        self.tts.initialize()
        self.audio.start()

        self.history: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.running = False
        self.last_text = ""
        self.last_outcome: Optional[str] = None
        self.frames_processed = 0
        self.controller: Optional[FrameController] = None
        self._process_thread: Optional[threading.Thread] = None
        self._warned_no_engine = False

    # ----- lifecycle -------------------------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.change.reset()
        self.controller = FrameController(self._camera_factory(self.cfg["camera"]), self.cfg["camera"],
                                          self.cfg["ocr"]["capture_interval"])
        self.controller.start()
        self._process_thread = threading.Thread(target=self._process_loop, name="process", daemon=True)
        self._process_thread.start()
        logger.info("Pipeline started")

    def stop(self) -> None:
        """Stop capture and OCR and silence pending OCR speech. TTS stays usable for /api/speak."""
        self.running = False
        timeout = float(self.cfg["pipeline"]["join_timeout_s"])
        if self.controller is not None:
            self.controller.stop(timeout)
        if self._process_thread is not None:
            self._process_thread.join(timeout)
            if self._process_thread.is_alive():
                logger.warning("process thread still busy (OCR call in progress); it will exit after it")
        self.audio.clear()
        logger.info("Pipeline stopped")

    def shutdown(self) -> None:
        """Stop everything, including the audio worker and OCR engine threads."""
        self.stop()
        self.audio.shutdown()
        self.ocr.shutdown()

    def threads_alive(self) -> List[str]:
        threads = [self._process_thread, self.audio._thread,
                   self.controller._thread if self.controller else None]
        return [t.name for t in threads if t is not None and t.is_alive()]

    # ----- per-frame processing -----------------------------------------------------------------
    def process_frame(self, frame: Any, now: Optional[float] = None) -> ProcessOutcome:
        """Run one frame through every stage. Never raises for bad input."""
        now = self._clock() if now is None else now
        try:
            frame = validate_frame(frame)
        except FrameError as e:
            return self._outcome(ProcessOutcome("invalid_frame", details={"error": str(e)}))

        report = self.quality.assess(frame)
        if not report.usable:
            return self._outcome(ProcessOutcome("unusable_frame",
                                                details={"reasons": report.reasons, **report.metrics}))
        if self.change.is_unchanged(frame, now):
            return self._outcome(ProcessOutcome("unchanged"))

        try:
            prepared = self.preprocessor.prepare(frame)
        except FrameError as e:
            return self._outcome(ProcessOutcome("invalid_frame", details={"error": str(e)}))

        decision = self.ocr.recognize(prepared)
        self.frames_processed += 1
        if decision.reason == "no_engine_available":
            if not self._warned_no_engine:
                logger.warning("frame skipped: no OCR engine available")
                self._warned_no_engine = True
            return self._outcome(ProcessOutcome("no_ocr_engine", decision=decision))
        if decision.reason == "all_engines_failed":
            return self._outcome(ProcessOutcome("ocr_failed", details={"errors": decision.errors},
                                                decision=decision))
        self.change.mark_processed(frame, now)  # only after a completed OCR pass
        if decision.winner is None:
            return self._outcome(ProcessOutcome("no_text", details={"reason": decision.reason},
                                                decision=decision))

        winner = decision.winner
        text = winner.cleaned_text
        base = dict(text=text, engine=winner.result.engine, confidence=winner.result.confidence,
                    decision=decision)
        is_dup, kind = self.duplicates.check(text, now)
        if is_dup:
            logger.debug("duplicate (%s) suppressed", kind)
            return self._outcome(ProcessOutcome("duplicate", details={"match": kind}, **base))

        with self.lock:
            self.history.append({"ts": time.time(), "text": text, "engine": winner.result.engine,
                                 "confidence": winner.result.confidence})
            del self.history[:-int(self.cfg["app"]["max_history"])]
        self.last_text = text
        utterance = self.composer.compose(text)
        result = self.audio.submit(utterance, source="ocr") if utterance else "nothing_to_say"
        status = "spoken" if result in ("queued", "interrupting") else "speech_dropped"
        return self._outcome(ProcessOutcome(status, details={"audio": result}, **base))

    def _outcome(self, outcome: ProcessOutcome) -> ProcessOutcome:
        self.last_outcome = outcome.status
        return outcome

    def _process_loop(self) -> None:
        wait = float(self.cfg["pipeline"]["frame_wait_timeout_s"])
        while self.running:
            frame = self.controller.get_frame(wait) if self.controller else None
            if frame is None or not self.running:
                continue
            try:
                outcome = self.process_frame(frame)
                logger.debug("frame -> %s", outcome.status)
            except Exception:  # never let one bad frame kill the loop, but never hide it either
                logger.exception("unexpected error while processing a frame")

    # ----- API helpers -------------------------------------------------------------------------
    def speak(self, text: str) -> str:
        utterance = self.composer.compose(text)
        return self.audio.submit(utterance, source="api") if utterance else "nothing_to_say"

    def voices(self) -> List[str]:
        return self.tts.voices()

    def last_audio_wav(self) -> Optional[bytes]:
        return self.tts.last_audio_wav()

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "last_text": self.last_text,
            "history_count": len(self.history),
            "last_outcome": self.last_outcome,
            "frames_processed": self.frames_processed,
            "camera": self.controller.status() if self.controller else {"state": "stopped"},
            "ocr": {"mode": self.ocr.mode, "available": self.ocr.available_engines()},
            "tts": {"available": self.tts.available_engines(), "last_engine": self.tts.last_engine},
            "audio": {"speaking": self.audio.is_speaking, "pending": self.audio.pending(),
                      **self.audio.stats, "last_error": self.audio.last_error},
        }

    def get_history(self):
        with self.lock:
            return list(self.history)[::-1]

    def diagnostics(self) -> Dict[str, Any]:
        return {"ocr_engines": self.ocr.statuses(), "tts_engines": self.tts.statuses()}
