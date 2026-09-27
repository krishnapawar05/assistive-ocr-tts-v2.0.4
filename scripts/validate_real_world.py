"""Comprehensive Real-World Validation Script for Smart Vision Assist v2.0.4.

Executes real camera checks, printed text, handwriting, motion gating, duplicate
suppression, audio controls, and latency/memory measurements.
"""
import gc
import json
import logging
import os
import sys
import time
import cv2
import numpy as np
import psutil

# Ensure root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import Config
from core.pipeline import AssistivePipeline
from core.frame.processing import QualityAssessor, MotionDetector, Preprocessor
from core.camera.opencv_camera import OpenCVCamera
from core.status import EngineStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("validator")

process = psutil.Process()


def get_rss_mb():
    return process.memory_info().rss / (1024 * 1024)


def load_fixture(fixture_name):
    path = os.path.join(ROOT, "tests", "fixtures", "ocr", fixture_name)
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Fixture not found: {path}")
    return img


def run_validation():
    results = {}
    rss_start = get_rss_mb()
    logger.info("Starting validation. Initial RSS: %.1f MB", rss_start)

    cfg = Config(os.path.join(ROOT, "config.json"))
    # Ensure offline mode is respected
    pipeline = AssistivePipeline(cfg)
    rss_pipeline_init = get_rss_mb()
    logger.info("Pipeline initialized. RSS: %.1f MB", rss_pipeline_init)

    # -------------------------------------------------------------
    # 1. REAL WEBCAM VALIDATION (Scenarios A, D, E)
    # -------------------------------------------------------------
    logger.info("\n=== 1. Live Webcam Validation ===")
    cam = OpenCVCamera(cfg.data["camera"])
    cam.open()
    frames = []
    t_start = time.perf_counter()
    for _ in range(10):
        f = cam.read()
        if f is not None:
            frames.append(f)
        time.sleep(0.05)
    t_read = time.perf_counter() - t_start
    cam.close()

    webcam_ok = len(frames) == 10
    webcam_shape = list(frames[0].shape) if frames else None
    logger.info("Webcam 10 frames read: %s, shape: %s, time: %.3fs", webcam_ok, webcam_shape, t_read)

    # Test Quality Assessor on real webcam frame
    q_report = pipeline.quality.assess(frames[0])
    logger.info("Webcam frame quality: usable=%s, reasons=%s, brightness=%.1f",
                q_report.usable, q_report.reasons, q_report.metrics.get("mean_brightness", 0.0))

    # Test Motion Detector with static webcam frames
    pipeline.motion.reset()
    is_moving = False
    score = 0.0
    for f in frames[:5]:
        is_moving, score = pipeline.motion.update(f)
    logger.info("Webcam static frames motion: is_moving=%s, score=%.3f", is_moving, score)

    # Simulated motion by shifting frame
    h, w = frames[0].shape[:2]
    M = np.float32([[1, 0, 40], [0, 1, 30]])
    shifted = cv2.warpAffine(frames[0], M, (w, h))
    is_moving_shift, score_shift = pipeline.motion.update(shifted)
    logger.info("Webcam induced motion: is_moving=%s, score=%.3f", is_moving_shift, score_shift)

    # Run OCR on live webcam frame
    outcome_webcam = pipeline.process_frame(frames[0])
    logger.info("Live webcam OCR outcome: status=%s, engine=%s, conf=%.2f, text=%r",
                outcome_webcam.status,
                outcome_webcam.engine or "-",
                outcome_webcam.confidence,
                outcome_webcam.text)

    results["webcam"] = {
        "connected": webcam_ok,
        "resolution": webcam_shape,
        "quality_usable": q_report.usable,
        "motion_static_moving": is_moving,
        "motion_dynamic_moving": is_moving_shift,
        "ocr_status": outcome_webcam.status,
        "text": outcome_webcam.text
    }

    # -------------------------------------------------------------
    # 2. PRINTED DOCUMENT VALIDATION (Sentence, Chapter, Room 204)
    # -------------------------------------------------------------
    logger.info("\n=== 2. Printed Document Validation ===")
    printed_tests = [
        ("signs/room_204.png", "Room 204"),
        ("printed/sentence.png", "The quick brown fox jumps over the lazy dog"),
        ("printed/chapter_numbers.png", "Chapter 7 Page 132"),
        ("classroom/whiteboard.png", "Homework due Friday Read pages 40 to 45"),
        ("classroom/greenboard.png", "Photosynthesis Light energy to chemical energy"),
    ]

    results["printed"] = []
    for rel_path, expected in printed_tests:
        img = load_fixture(rel_path)
        t0 = time.perf_counter()
        outcome = pipeline.process_frame(img)
        dt = time.perf_counter() - t0
        winner = outcome.decision.winner if outcome.decision else None
        engine_used = outcome.engine or (winner.result.engine if winner else "none")
        conf = outcome.confidence or (winner.result.confidence if winner else 0.0)
        score = winner.final_score if winner else 0.0
        logger.info("Fixture [%s] -> Status: %s | Engine: %s | Conf: %.2f | Score: %.2f | Latency: %.3fs | Text: %r",
                    rel_path, outcome.status, engine_used, conf, score, dt, outcome.text)
        results["printed"].append({
            "fixture": rel_path,
            "expected": expected,
            "actual": outcome.text,
            "engine": engine_used,
            "confidence": round(conf, 3),
            "score": round(score, 3),
            "latency_s": round(dt, 3),
            "status": outcome.status
        })

    # -------------------------------------------------------------
    # 3. REAL HANDWRITING VALIDATION (TrOCR Region Gating)
    # -------------------------------------------------------------
    logger.info("\n=== 3. Handwriting Validation ===")
    hw_tests = [
        ("handwritten/hand_meet.png", "Meet me at noon"),
        ("handwritten/hand_notes.png", "Revise chapter three"),
    ]
    results["handwriting"] = []
    for rel_path, expected in hw_tests:
        img = load_fixture(rel_path)
        t0 = time.perf_counter()
        outcome = pipeline.process_frame(img)
        dt = time.perf_counter() - t0
        winner = outcome.decision.winner if outcome.decision else None
        engine_used = outcome.engine or (winner.result.engine if winner else "none")
        conf = outcome.confidence or (winner.result.confidence if winner else 0.0)
        score = winner.final_score if winner else 0.0
        logger.info("Handwriting [%s] -> Status: %s | Engine: %s | Conf: %.2f | Score: %.2f | Latency: %.3fs | Text: %r",
                    rel_path, outcome.status, engine_used, conf, score, dt, outcome.text)
        results["handwriting"].append({
            "fixture": rel_path,
            "expected": expected,
            "actual": outcome.text,
            "engine": engine_used,
            "confidence": round(conf, 3),
            "score": round(score, 3),
            "latency_s": round(dt, 3),
            "status": outcome.status
        })

    # -------------------------------------------------------------
    # 4. TEMPORAL & AUDIO VALIDATION (Duplicates, Scenes, Audio Control)
    # -------------------------------------------------------------
    logger.info("\n=== 4. Temporal & Audio Validation ===")
    img_room = load_fixture("signs/room_204.png")
    # First presentation: should accept
    out1 = pipeline.process_frame(img_room)
    # Immediate second presentation: should be duplicate
    out2 = pipeline.process_frame(img_room)
    logger.info("First presentation: status=%s, text=%r", out1.status, out1.text)
    logger.info("Duplicate presentation: status=%s (reason: %s)", out2.status, out2.details.get("reason"))

    # Test Audio Stop Speech
    pipeline.speak("This is a long sentence being spoken for testing stop speech.")
    time.sleep(0.1)
    is_speaking_before = pipeline.audio.is_speaking or pipeline.audio.pending() > 0
    pipeline.stop_speech()
    is_speaking_after = pipeline.audio.is_speaking
    pending_after = pipeline.audio.pending()
    logger.info("Audio stop test: before=%s, after_speaking=%s, pending=%d",
                is_speaking_before, is_speaking_after, pending_after)

    # Test Scene Invalidation
    pipeline.audio.submit("Queued old room announcement", source="ocr", scene_token=pipeline._scene_token)
    purged = pipeline.audio.invalidate_scene("scene_new_123")
    logger.info("Scene invalidation purged: %d queued items", purged)

    results["temporal_and_audio"] = {
        "duplicate_suppressed": out2.status == "duplicate",
        "stop_speech_cleared_queue": pending_after == 0,
        "scene_invalidation_purged": purged > 0
    }

    # -------------------------------------------------------------
    # 5. TTS ENGINE BENCHMARK (Windows SAPI, Coqui, eSpeak)
    # -------------------------------------------------------------
    logger.info("\n=== 5. TTS Engine Latency Benchmark ===")
    tts_results = {}
    for engine_name in ("windows", "espeak", "coqui"):
        adapter = pipeline.tts.adapters.get(engine_name)
        if adapter and adapter.status == EngineStatus.READY:
            t0 = time.perf_counter()
            try:
                # Speak short test sentence
                res = adapter.speak("Smart Vision Assist system is ready.")
                dt = time.perf_counter() - t0
                wav = adapter.last_audio_wav() if hasattr(adapter, "last_audio_wav") else None
                tts_results[engine_name] = {
                    "status": "PASS",
                    "latency_s": round(dt, 3),
                    "output_wav_bytes": len(wav) if wav else 0
                }
                logger.info("TTS [%s] -> PASS, Latency: %.3fs, WAV bytes: %d",
                            engine_name, dt, tts_results[engine_name]["output_wav_bytes"])
            except Exception as e:
                tts_results[engine_name] = {"status": "FAIL", "error": str(e)}
                logger.error("TTS [%s] failed: %s", engine_name, e)
        else:
            status = adapter.status.value if adapter else "NOT_FOUND"
            tts_results[engine_name] = {"status": status}
            logger.info("TTS [%s] -> %s", engine_name, status)
    results["tts"] = tts_results

    # -------------------------------------------------------------
    # 6. MEMORY FOOTPRINT
    # -------------------------------------------------------------
    rss_end = get_rss_mb()
    results["memory"] = {
        "rss_initial_mb": round(rss_start, 1),
        "rss_pipeline_init_mb": round(rss_pipeline_init, 1),
        "rss_peak_mb": round(rss_end, 1),
        "delta_mb": round(rss_end - rss_start, 1)
    }
    logger.info("Memory usage: Initial=%.1f MB, Final=%.1f MB, Delta=%.1f MB",
                rss_start, rss_end, rss_end - rss_start)

    pipeline.shutdown()
    gc.collect()

    return results


if __name__ == "__main__":
    out = run_validation()
    out_path = os.path.join(ROOT, "docs", "validation", "real_world_metrics.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("\nValidation complete. Output saved to:", out_path)
