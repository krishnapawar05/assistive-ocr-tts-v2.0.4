"""Unit tests for Phase B: Frame sequence, stale invalidation, latency budget, and motion gating."""
import threading
import time
import unittest
import numpy as np

from core.audio.manager import AudioManager, SpeechRequest
from core.camera.controller import CapturedFrame
from core.frame.processing import MotionDetector, Preprocessor, PreparedFrame
from core.ocr.service import OCRService
from core.ocr.types import EngineStatus, OCRDecision, OCRResult
from core.pipeline import AssistivePipeline, ProcessOutcome
from tests.helpers import FakeOCRAdapter, RecordingTTS, default_config, text_frame


class FakeSpeaker:
    def __init__(self):
        self.spoken = []
        self._stop_called = False

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        self._stop_called = True


class SimulatedClock:
    def __init__(self, start_time: float = 100.0):
        self.now = start_time

    def time(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def make_ocr_cfg(**overrides):
    cfg = default_config()["ocr"]
    cfg.update(overrides)
    return cfg


def make_text_cfg(**overrides):
    cfg = default_config()["text"]
    cfg.update(overrides)
    return cfg


def make_preprocess_cfg(**overrides):
    cfg = default_config()["frame"]["preprocess"]
    cfg.update(overrides)
    return cfg


def base_pipeline_cfg(**overrides):
    cfg = default_config()
    cfg["frame"]["quality"]["enabled"] = False
    cfg["frame"]["change_detection"]["enabled"] = False
    cfg.update(overrides)
    return cfg


class FreshnessAndMotionTest(unittest.TestCase):

    # ----- Item A: Frame Sequence Propagation ------------------------------------------------
    def test_frame_sequence_propagation(self):
        """Frame sequence ID propagates from CapturedFrame -> PreparedFrame -> OCR -> Outcome."""
        img = text_frame("Room 101")
        captured = CapturedFrame(img, frame_seq_id=42, capture_timestamp=100.0)

        prep = Preprocessor(make_preprocess_cfg())
        prepared = prep.prepare(captured.image, frame_seq_id=captured.frame_seq_id,
                                capture_timestamp=captured.capture_timestamp)
        self.assertEqual(prepared.frame_seq_id, 42)
        self.assertEqual(prepared.capture_timestamp, 100.0)

        fake_adapter = FakeOCRAdapter("easyocr", text="Room 101", confidence=0.95)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine", latency_budget_s=5.0),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        decision = ocr_service.recognize(prepared)
        self.assertEqual(decision.frame_seq_id, 42)
        self.assertEqual(decision.capture_timestamp, 100.0)
        self.assertIsNotNone(decision.winner)
        self.assertEqual(decision.winner.result.frame_seq_id, 42)
        self.assertEqual(decision.winner.result.capture_timestamp, 100.0)

        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service)
        outcome = pipeline.process_frame(captured)
        self.assertEqual(outcome.frame_seq_id, 42)
        self.assertEqual(outcome.capture_timestamp, 100.0)
        pipeline.shutdown()

    # ----- Item B: Timestamp Propagation -----------------------------------------------------
    def test_timestamp_propagation(self):
        """Capture timestamp remains intact across the entire pipeline."""
        img = text_frame("Library Exit")
        captured = CapturedFrame(img, frame_seq_id=10, capture_timestamp=123.456)

        fake_adapter = FakeOCRAdapter("easyocr", text="Library Exit", confidence=0.90)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service)
        outcome = pipeline.process_frame(captured)

        self.assertEqual(outcome.capture_timestamp, 123.456)
        self.assertIsNotNone(outcome.decision)
        self.assertEqual(outcome.decision.capture_timestamp, 123.456)
        pipeline.shutdown()

    # ----- Item C: Stale OCR Result Rejection -------------------------------------------------
    def test_stale_ocr_result_rejection_by_age(self):
        """A frame whose capture timestamp exceeds max_frame_age_s is rejected before speech."""
        clock = SimulatedClock(100.0)
        img = text_frame("Danger Ahead")
        # Capture occurred at t=90.0, current clock is t=100.0 (age = 10.0s > max_age 3.0s)
        captured = CapturedFrame(img, frame_seq_id=1, capture_timestamp=90.0)

        fake_adapter = FakeOCRAdapter("easyocr", text="Danger Ahead", confidence=0.95)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        cfg["pipeline"]["stale_frame"] = {"enabled": True, "max_frame_age_s": 3.0, "max_seq_distance": 15}

        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service, clock=clock.time)
        outcome = pipeline.process_frame(captured)

        self.assertEqual(outcome.status, "stale_frame")
        self.assertEqual(outcome.details.get("reason"), "max_frame_age_exceeded")
        self.assertEqual(pipeline.audio.pending(), 0)
        self.assertEqual(pipeline.audio.stats.get("dropped_stale", 0), 0)  # Dropped before audio submit
        pipeline.shutdown()

    def test_stale_ocr_result_rejection_by_sequence_distance(self):
        """A frame too far behind the controller's delivered sequence is rejected."""
        clock = SimulatedClock(100.0)
        img = text_frame("Room 101")
        captured = CapturedFrame(img, frame_seq_id=5, capture_timestamp=99.5)

        fake_adapter = FakeOCRAdapter("easyocr", text="Room 101", confidence=0.95)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        cfg["pipeline"]["stale_frame"] = {"enabled": True, "max_frame_age_s": 10.0, "max_seq_distance": 5}

        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service, clock=clock.time)
        # Simulate that the camera controller has delivered 20 frames since
        class MockController:
            frames_delivered = 20
            def stop(self, timeout=None):
                pass
        pipeline.controller = MockController()

        outcome = pipeline.process_frame(captured)
        self.assertEqual(outcome.status, "stale_frame")
        self.assertEqual(outcome.details.get("reason"), "max_seq_distance_exceeded")
        pipeline.shutdown()

    # ----- Item D: Stale Queued Audio Rejection -----------------------------------------------
    def test_stale_queued_audio_rejection(self):
        """AudioManager drops queued speech if its capture timestamp exceeds max_frame_age_s."""
        clock = SimulatedClock(100.0)
        sp = FakeSpeaker()
        mgr = AudioManager(
            {"policy": "queue", "max_queue_size": 5, "max_age_s": 30.0, "max_frame_age_s": 2.0, "shutdown_timeout_s": 1.0},
            sp.speak, sp.stop, clock=clock.time
        )
        mgr.start()

        # Submit an OCR speech request with capture timestamp at t=95.0 (age = 5.0s > 2.0s)
        status = mgr.submit("Obsolete instruction", source="ocr", frame_seq_id=1, capture_timestamp=95.0)
        self.assertEqual(status, "queued")

        self.assertTrue(mgr.wait_idle(2.0))
        self.assertEqual(len(sp.spoken), 0)
        self.assertEqual(mgr.stats["dropped_stale"], 1)
        mgr.shutdown()

    # ----- Item E: Current Audio Still Speaks -------------------------------------------------
    def test_current_audio_still_speaks(self):
        """Fresh OCR speech and API speech are spoken without being dropped."""
        clock = SimulatedClock(100.0)
        sp = FakeSpeaker()
        mgr = AudioManager(
            {"policy": "queue", "max_queue_size": 5, "max_age_s": 30.0, "max_frame_age_s": 2.0, "shutdown_timeout_s": 1.0},
            sp.speak, sp.stop, clock=clock.time
        )
        mgr.start()

        # Fresh OCR request (age 0.5s < 2.0s)
        mgr.submit("Fresh OCR speech", source="ocr", frame_seq_id=2, capture_timestamp=99.5)
        # API request (always fresh)
        mgr.submit("API announcement", source="api")

        self.assertTrue(mgr.wait_idle(2.0))
        self.assertEqual(sp.spoken, ["Fresh OCR speech", "API announcement"])
        self.assertEqual(mgr.stats["dropped_stale"], 0)
        mgr.shutdown()

    # ----- Item F: Rapid Visual Scene Change --------------------------------------------------
    def test_rapid_visual_scene_change_invalidates_queued_ocr(self):
        """Scene change token invalidates pending OCR speech but leaves API speech intact."""
        clock = SimulatedClock(100.0)
        spoken = []
        first_spoken = threading.Event()
        proceed = threading.Event()

        def controlled_speak(text: str):
            spoken.append(text)
            first_spoken.set()
            proceed.wait(2.0)

        mgr = AudioManager(
            {"policy": "queue", "max_queue_size": 5, "max_age_s": 30.0, "max_frame_age_s": 10.0, "shutdown_timeout_s": 1.0},
            controlled_speak, lambda: None, clock=clock.time
        )
        mgr.start()

        # Submit first item to occupy speaker
        mgr.submit("Hold item", source="api")
        self.assertTrue(first_spoken.wait(1.0))

        # Now submit scene 1 item and an api item while speaker is busy
        mgr.submit("Scene 1 sign", source="ocr", frame_seq_id=1, capture_timestamp=100.0, scene_token="scene_1")
        mgr.submit("Important safety alert", source="api")
        self.assertEqual(mgr.pending(), 2)

        # Invalidate scene 1
        dropped = mgr.invalidate_scene("scene_2")
        self.assertEqual(dropped, 1)
        self.assertEqual(mgr.pending(), 1)
        self.assertEqual(mgr.stats["dropped_stale"], 1)

        # Allow speaker to finish
        proceed.set()
        self.assertTrue(mgr.wait_idle(2.0))
        self.assertEqual(spoken, ["Hold item", "Important safety alert"])
        mgr.shutdown()

    def test_rapid_visual_scene_change_invalidates_in_flight_frame(self):
        """If pipeline advances scene token during OCR, resulting outcome is stale_frame."""
        clock = SimulatedClock(100.0)
        img = text_frame("Old Room 101")
        captured = CapturedFrame(img, frame_seq_id=1, capture_timestamp=100.0)

        class SceneAdvancingAdapter(FakeOCRAdapter):
            def __init__(self, pipeline_ref):
                super().__init__("easyocr", text="Old Room 101", confidence=0.95)
                self.pipeline_ref = pipeline_ref

            def _recognize(self, image):
                # Simulate scene change (e.g. camera panned while OCR was computing)
                self.pipeline_ref[0].invalidate_scene("panned")
                return super()._recognize(image)

        pipeline_holder = []
        adapter = SceneAdvancingAdapter(pipeline_holder)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service, clock=clock.time)
        pipeline_holder.append(pipeline)

        outcome = pipeline.process_frame(captured)
        self.assertEqual(outcome.status, "stale_frame")
        self.assertEqual(outcome.details.get("reason"), "scene_invalidated")
        pipeline.shutdown()

    # ----- Item G: OCR Latency Timeout Behavior ----------------------------------------------
    def test_ocr_latency_budget_timeout(self):
        """Fallback OCR exceeding latency budget aborts and yields ocr_timeout without killing threads."""
        primary_fail = FakeOCRAdapter("easyocr", raise_exc=RuntimeError("primary failed"))
        slow_fallback = FakeOCRAdapter("paddle", text="Slow text", delay_s=0.35)

        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=["paddle"], mode="fallback", latency_budget_s=0.2),
            make_text_cfg(),
            adapters={"easyocr": primary_fail, "paddle": slow_fallback}
        )
        ocr_service.initialize()

        img = text_frame("Slow text")
        prepared = PreparedFrame(img, img, frame_seq_id=1, capture_timestamp=100.0)
        decision = ocr_service.recognize(prepared)

        self.assertIsNone(decision.winner)
        self.assertEqual(decision.reason, "latency_budget_exceeded")

        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service)
        outcome = pipeline.process_frame(img)
        self.assertEqual(outcome.status, "ocr_timeout")
        self.assertEqual(outcome.details.get("reason"), "latency_budget_exceeded")

        # Engine threads remain cleanly running
        self.assertTrue(ocr_service.adapters["easyocr"].is_available)
        self.assertTrue(ocr_service.adapters["paddle"].is_available)
        self.assertFalse(ocr_service._executors["easyocr"]._shutdown)
        self.assertFalse(ocr_service._executors["paddle"]._shutdown)
        pipeline.shutdown()
        ocr_service.shutdown()

    # ----- Item H: Camera Movement Suppressing OCR -------------------------------------------
    def test_camera_movement_suppressing_ocr(self):
        """Frames marked as moving produce camera_moving outcome and bypass OCR."""
        img = text_frame("Should Not Run")
        captured = CapturedFrame(img, frame_seq_id=5, capture_timestamp=100.0,
                                 is_moving=True, motion_score=45.2)

        fake_adapter = FakeOCRAdapter("easyocr", text="Should Not Run", confidence=0.95)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service)
        outcome = pipeline.process_frame(captured)

        self.assertEqual(outcome.status, "camera_moving")
        self.assertEqual(outcome.details.get("motion_score"), 45.2)
        self.assertEqual(fake_adapter.calls, 0)
        pipeline.shutdown()

    # ----- Item I: OCR Resumes After Stabilization -------------------------------------------
    def test_ocr_resumes_after_stabilization(self):
        """Motion detector gates OCR during motion and resumes once stabilized."""
        detector = MotionDetector({"enabled": True, "thumbnail_size": 32,
                                   "motion_threshold": 20.0, "stabilization_frames": 2})

        frame_black = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_white = np.ones((100, 100, 3), dtype=np.uint8) * 255

        # Initial frame
        is_moving, score = detector.update(frame_black)
        self.assertFalse(is_moving)

        # Huge jump: black to white -> motion triggered
        is_moving, score = detector.update(frame_white)
        self.assertTrue(is_moving)
        self.assertGreater(score, 20.0)

        # Calm frame 1: identical white frame (calm count = 1, required = 2) -> still flagged moving
        is_moving, score = detector.update(frame_white)
        self.assertTrue(is_moving)
        self.assertAlmostEqual(score, 0.0, places=1)

        # Calm frame 2: identical white frame (calm count = 2) -> stabilized!
        is_moving, score = detector.update(frame_white)
        self.assertFalse(is_moving)

        # Pipeline test with stabilized frame
        fake_adapter = FakeOCRAdapter("easyocr", text="Exit Sign", confidence=0.95)
        ocr_service = OCRService(
            make_ocr_cfg(engine="easyocr", fallback_order=[], mode="single_engine"),
            make_text_cfg(),
            adapters={"easyocr": fake_adapter}
        )
        ocr_service.initialize()
        cfg = base_pipeline_cfg()
        pipeline = AssistivePipeline(cfg, ocr_service=ocr_service)

        # Stabilized frame executes OCR with fresh capture timestamp
        now = time.monotonic()
        stabilized_frame = CapturedFrame(text_frame("Exit Sign"), frame_seq_id=10,
                                         capture_timestamp=now, is_moving=False, motion_score=score)
        outcome = pipeline.process_frame(stabilized_frame)
        self.assertEqual(outcome.status, "spoken")
        self.assertEqual(outcome.text, "Exit Sign")
        self.assertEqual(fake_adapter.calls, 1)
        pipeline.shutdown()


if __name__ == "__main__":
    unittest.main()
