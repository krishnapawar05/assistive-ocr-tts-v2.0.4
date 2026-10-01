# core/config.py
"""Application configuration: defaults, legacy-key migration, and validation.

Every tunable value used by core logic lives in DEFAULT_CONFIG. ``config.json`` only needs to
contain overrides; missing keys are filled from the defaults and written back.
"""
import copy
import json
import logging
import os
from typing import Any, Dict, List

from .languages import APP_LANGUAGES, normalize_language

logger = logging.getLogger("config")

OCR_ENGINES = ("tesseract", "easyocr", "paddle", "trocr")
TTS_ENGINES = ("coqui", "windows", "espeak")

DEFAULT_CONFIG: Dict[str, Any] = {
    "camera": {
        "source_type": "opencv",          # opencv | gstreamer
        "camera_id": 0,
        "resolution": "1080p",
        "resolutions": {"720p": [1280, 720], "1080p": [1920, 1080]},
        "gstreamer_framerate": 30,
        "buffer_size": 1,
        "reconnect_initial_delay_s": 1.0,
        "reconnect_max_delay_s": 10.0,
        "max_consecutive_read_failures": 30,
        "read_failure_sleep_s": 0.01,
    },
    "frame": {
        "preprocess": {
            "crop_if_larger_than": 1920,   # v2.0.4: center-crop frames whose longest side exceeds this
            "crop_margin_fraction": 0.1,
            "upscale_min_side": 400,       # v2.0.4: upscale gray image if longest side is smaller
            "min_side": 10,
            "max_input_side": 0,           # 0 = no downscale (v2.0.4 behavior)
        },
        "quality": {
            "enabled": True,
            "min_width": 64,
            "min_height": 64,
            "min_contrast_std": 3.0,       # below this the frame is blank/uniform
            "dark_mean_max": 15.0,
            "bright_mean_min": 250.0,
            "bright_std_max": 6.0,
            "min_sharpness": 0.0,          # Laplacian variance; 0 disables the blur gate
        },
        "change_detection": {
            "enabled": True,
            "thumbnail_size": 32,
            "min_mean_abs_diff": 2.0,      # frames closer than this to the last processed one are skipped
            "max_skip_s": 10.0,            # but re-process at least this often
        },
        "motion_detection": {
            "enabled": True,
            "thumbnail_size": 32,
            "motion_threshold": 25.0,      # MAD above this indicates strong camera movement
            "stabilization_frames": 2,     # calm frames required before resuming OCR
        },
    },
    "ocr": {
        "engine": "easyocr",               # primary engine
        "mode": "fallback",                # single_engine | fallback | ensemble
        "fallback_order": ["easyocr", "paddle", "tesseract", "trocr"],  # primary is skipped if listed
        "language": "en",
        "text_type": "printed",            # printed | handwritten
        "capture_interval": 0.2,
        "min_confidence": 0.30,            # engine-reported confidence below this is discarded
        "min_text_len": 3,
        "accept_score": 0.50,              # fallback mode stops once a candidate scores this high
        "min_final_score": 0.35,           # nothing below this is ever spoken
        "latency_budget_s": 0.0,           # max OCR duration before aborting fallback (0 = disabled)
        "serialize_engines": True,         # never run two OCR engines at once (memory safety)
        "preload": "primary",              # primary: load fallback engines on first use | all
        "engines": {
            "tesseract": {
                "enabled": True,
                "executable": "",
                "search_paths": [
                    "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                    "C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
                    "/usr/bin/tesseract",
                ],
                "oem": 3,
                "psm": 3,
                "timeout_s": 20.0,
            },
            "easyocr": {
                "enabled": True,
                "model_dir": "",           # empty = EasyOCR default (~/.EasyOCR/model)
                "gpu": False,
                "include_english": True,
                "canvas_size": 2560,       # EasyOCR default
                "mag_ratio": 1.0,
                "timeout_s": 60.0,
            },
            "paddle": {
                "enabled": True,
                "model_root": "~/.paddlex/official_models",
                "det_model": "PP-OCRv5_server_det",
                "rec_models": {
                    "en": "en_PP-OCRv5_mobile_rec",
                    "hi": "devanagari_PP-OCRv5_mobile_rec",
                    "kn": "ka_PP-OCRv3_mobile_rec",
                },
                "device": "cpu",
                "det_limit_side_len": 0,   # 0 = PaddleOCR default
                "det_limit_type": "max",
                "timeout_s": 90.0,
            },
            "trocr": {
                "enabled": True,
                "model": "microsoft/trocr-base-handwritten",
                "max_new_tokens": 64,
                "line_min_confidence": 0.6,
                "timeout_s": 60.0,
            },
        },
        "regions": {
            "min_contrast_std": 3.0,
            "min_gradient": 30.0,
            "join_width_fraction": 0.02,
            "join_height_px": 3,
            "min_line_height_px": 8,
            "max_line_height_fraction": 0.5,
            "min_aspect_ratio": 0.8,
            "merge_gap_height_ratio": 1.2,     # join same-line boxes whose gap < ratio * text height
            "merge_min_vertical_overlap": 0.5,
            "min_height_vs_median": 0.5,       # drop regions shorter than this * median line height
            "max_regions": 12,
            "padding_px": 6,
        },
        "scoring": {
            "weights": {
                "confidence": 0.35,
                "reliability": 0.20,
                "agreement": 0.15,
                "validity": 0.15,
                "language": 0.10,
                "length": 0.05,
                "bbox_agreement": 0.0,
                "speed": 0.0,
            },
            "penalties": {"garbage": 0.5, "repetition": 0.3},
            "engine_reliability": {
                "printed": {"tesseract": 0.8, "easyocr": 0.85, "paddle": 0.9, "trocr": 0.4},
                "handwritten": {"tesseract": 0.3, "easyocr": 0.6, "paddle": 0.6, "trocr": 0.85},
            },
            "max_expected_len": 400,
            "latency_budget_s": 10.0,
        },
        "duplicates": {
            "cooldown_s": 20.0,
            "fuzzy_threshold": 90.0,       # RapidFuzz ratio, 0-100
            "refresh_on_repeat": True,     # text that stays in view stays suppressed
            "max_entries": 50,
        },
    },
    "text": {
        "unicode_form": "NFC",
        "allowed_punctuation": ".,;:!?'\"()-/&%+@#$₹°",
        "edge_strip_chars": "|~`^_*\\<>{}[]=",
        "max_symbol_run": 1,
        "min_validity": 0.6,
    },
    "tts": {
        "engine": "coqui",
        "fallback_engines": ["windows", "espeak"],
        "language": "en",
        "coqui_model": "tts_models/en/vctk/vits",
        "voice": "p335",                   # Coqui speaker id
        "speed": 1.0,
        "volume": 0.9,
        "max_chars": 300,
        "engines": {
            "coqui": {"enabled": True, "model_dir": "", "gpu": False},
            "windows": {"enabled": True, "voice": "", "rate_per_speed_unit": 5, "timeout_s": 60.0},
            "espeak": {
                "enabled": True,
                "executable": "",
                "search_paths": ["C:\\Program Files\\eSpeak NG\\espeak-ng.exe", "/usr/bin/espeak-ng"],
                "voice": "",               # empty = derive from tts.language
                "base_wpm": 150,
                "min_wpm": 80,
                "max_wpm": 450,
                "max_amplitude": 200,
                "timeout_s": 60.0,
            },
        },
    },
    "audio": {
        "policy": "queue",                 # queue | interrupt | drop_if_busy
        "max_queue_size": 5,
        "max_age_s": 30.0,                 # queued speech older than this is dropped
        "max_frame_age_s": 30.0,           # queued speech whose camera frame is older than this is dropped
        "shutdown_timeout_s": 3.0,
    },
    "pipeline": {
        "frame_wait_timeout_s": 0.3,
        "join_timeout_s": 3.0,
        "stale_frame": {
            "enabled": True,
            "max_frame_age_s": 30.0,       # discard OCR speech if frame is older than this
            "max_seq_distance": 0,         # discard OCR speech if camera delivered > N newer frames (0 = disabled)
        },
    },
    "app": {
        "high_contrast": False,
        "font_size": "16px",
        "max_history": 50,
        "log_level": "INFO",
        "offline_mode": True,
    },
}

# v2.0.4 keys that are no longer used. Kept out of the file after migration.
_DEAD_OCR_KEYS = ("parallel_ocr", "use_yolo", "onnx_sr_model", "easyocr_languages")


class ConfigError(ValueError):
    def __init__(self, errors: List[str]):
        super().__init__("Invalid configuration:\n  - " + "\n  - ".join(errors))
        self.errors = errors


def _merge(base: dict, override: Dict) -> None:
    """Recursively merge override into base (in place)."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def migrate(data: Dict[str, Any]) -> List[str]:
    """Translate v2.0.4 keys in place. Returns human-readable notes of what changed."""
    notes = []
    ocr = data.get("ocr")
    if isinstance(ocr, dict):
        engines = ocr.setdefault("engines", {})
        if "use_trocr" in ocr:
            engines.setdefault("trocr", {})["enabled"] = bool(ocr.pop("use_trocr"))
            notes.append("ocr.use_trocr -> ocr.engines.trocr.enabled")
        if "handwriting_fallback" in ocr:
            engines.setdefault("easyocr", {})["enabled"] = bool(ocr.pop("handwriting_fallback"))
            notes.append("ocr.handwriting_fallback -> ocr.engines.easyocr.enabled")
        for key in _DEAD_OCR_KEYS:
            if key in ocr:
                ocr.pop(key)
                notes.append(f"ocr.{key} removed (unused)")
        lang = ocr.get("language")
        if isinstance(lang, str) and normalize_language(lang) and normalize_language(lang) != lang:
            ocr["language"] = normalize_language(lang)
            notes.append(f"ocr.language '{lang}' -> '{ocr['language']}'")
    return notes


# ----- validation ----------------------------------------------------------------------------

def _get(data, path):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def validate(data: Dict[str, Any]) -> List[str]:
    """Return a list of problems; empty means valid."""
    errors: List[str] = []

    def num(path, lo=None, hi=None, integer=False):
        v, ok = _get(data, path)
        if not ok:
            errors.append(f"{path}: missing")
            return
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (integer and not isinstance(v, int)):
            errors.append(f"{path}: expected {'integer' if integer else 'number'}, got {v!r}")
            return
        if lo is not None and v < lo:
            errors.append(f"{path}: {v} is below minimum {lo}")
        if hi is not None and v > hi:
            errors.append(f"{path}: {v} is above maximum {hi}")

    def choice(path, options):
        v, ok = _get(data, path)
        if not ok or v not in options:
            errors.append(f"{path}: {v!r} is not one of {list(options)}")

    def boolean(path):
        v, ok = _get(data, path)
        if not isinstance(v, bool):
            errors.append(f"{path}: expected true/false, got {v!r}")

    def string(path):
        v, ok = _get(data, path)
        if not isinstance(v, str):
            errors.append(f"{path}: expected string, got {v!r}")

    # camera
    choice("camera.source_type", ("opencv", "gstreamer"))
    num("camera.camera_id", 0, integer=True)
    res, _ = _get(data, "camera.resolutions")
    if not isinstance(res, dict) or data["camera"].get("resolution") not in res:
        errors.append(f"camera.resolution: {data['camera'].get('resolution')!r} not in camera.resolutions")
    num("camera.gstreamer_framerate", 1, 240, integer=True)
    num("camera.buffer_size", 1, 64, integer=True)
    num("camera.reconnect_initial_delay_s", 0.01)
    num("camera.reconnect_max_delay_s", 0.01)
    num("camera.max_consecutive_read_failures", 1, integer=True)
    num("camera.read_failure_sleep_s", 0)

    # frame
    for k in ("crop_if_larger_than", "upscale_min_side", "min_side", "max_input_side"):
        num(f"frame.preprocess.{k}", 0, integer=True)
    num("frame.preprocess.crop_margin_fraction", 0, 0.45)
    boolean("frame.quality.enabled")
    for k in ("min_width", "min_height"):
        num(f"frame.quality.{k}", 1, integer=True)
    for k in ("min_contrast_std", "dark_mean_max", "bright_std_max", "min_sharpness"):
        num(f"frame.quality.{k}", 0)
    num("frame.quality.bright_mean_min", 0, 255)
    boolean("frame.change_detection.enabled")
    num("frame.change_detection.thumbnail_size", 4, 256, integer=True)
    num("frame.change_detection.min_mean_abs_diff", 0, 255)
    num("frame.change_detection.max_skip_s", 0)
    boolean("frame.motion_detection.enabled")
    num("frame.motion_detection.thumbnail_size", 4, 256, integer=True)
    num("frame.motion_detection.motion_threshold", 0, 255)
    num("frame.motion_detection.stabilization_frames", 1, 60, integer=True)

    # ocr
    choice("ocr.engine", OCR_ENGINES)
    choice("ocr.mode", ("single_engine", "fallback", "ensemble"))
    order, _ = _get(data, "ocr.fallback_order")
    if not isinstance(order, list) or any(e not in OCR_ENGINES for e in order):
        errors.append(f"ocr.fallback_order: must be a list of {list(OCR_ENGINES)}, got {order!r}")
    lang, _ = _get(data, "ocr.language")
    if normalize_language(lang) not in APP_LANGUAGES:
        errors.append(f"ocr.language: {lang!r} is not one of {list(APP_LANGUAGES)}")
    choice("ocr.text_type", ("printed", "handwritten"))
    num("ocr.capture_interval", 0.05, 60)
    num("ocr.min_confidence", 0, 1)
    num("ocr.min_text_len", 1, integer=True)
    num("ocr.accept_score", 0, 1)
    num("ocr.min_final_score", 0, 1)
    num("ocr.latency_budget_s", 0)
    boolean("ocr.serialize_engines")
    choice("ocr.preload", ("primary", "all"))
    for eng in OCR_ENGINES:
        boolean(f"ocr.engines.{eng}.enabled")
        num(f"ocr.engines.{eng}.timeout_s", 0.1)
    num("ocr.engines.tesseract.oem", 0, 3, integer=True)
    num("ocr.engines.tesseract.psm", 0, 13, integer=True)
    num("ocr.engines.easyocr.canvas_size", 64, integer=True)
    num("ocr.engines.easyocr.mag_ratio", 0.1, 10)
    string("ocr.engines.paddle.device")
    choice("ocr.engines.paddle.det_limit_type", ("max", "min"))
    num("ocr.engines.paddle.det_limit_side_len", 0, integer=True)
    num("ocr.engines.trocr.max_new_tokens", 1, 512, integer=True)
    num("ocr.engines.trocr.line_min_confidence", 0, 1)
    for k in ("min_contrast_std", "min_gradient", "join_width_fraction", "max_line_height_fraction",
              "min_aspect_ratio", "merge_gap_height_ratio", "merge_min_vertical_overlap",
              "min_height_vs_median"):
        num(f"ocr.regions.{k}", 0)
    for k in ("join_height_px", "min_line_height_px", "max_regions", "padding_px"):
        num(f"ocr.regions.{k}", 0, integer=True)
    weights, _ = _get(data, "ocr.scoring.weights")
    if not isinstance(weights, dict) or not any(isinstance(w, (int, float)) and w > 0 for w in weights.values()):
        errors.append("ocr.scoring.weights: need at least one positive weight")
    else:
        for k in weights:
            num(f"ocr.scoring.weights.{k}", 0, 1)
    for k in ("garbage", "repetition"):
        num(f"ocr.scoring.penalties.{k}", 0, 1)
    for tt in ("printed", "handwritten"):
        for eng in OCR_ENGINES:
            num(f"ocr.scoring.engine_reliability.{tt}.{eng}", 0, 1)
    num("ocr.scoring.max_expected_len", 1, integer=True)
    num("ocr.scoring.latency_budget_s", 0.01)
    num("ocr.duplicates.cooldown_s", 0)
    num("ocr.duplicates.fuzzy_threshold", 0, 100)
    boolean("ocr.duplicates.refresh_on_repeat")
    num("ocr.duplicates.max_entries", 1, integer=True)

    # text
    choice("text.unicode_form", ("NFC", "NFKC", "NFD", "NFKD"))
    string("text.allowed_punctuation")
    string("text.edge_strip_chars")
    num("text.max_symbol_run", 1, integer=True)
    num("text.min_validity", 0, 1)

    # tts
    choice("tts.engine", TTS_ENGINES)
    fb, _ = _get(data, "tts.fallback_engines")
    if not isinstance(fb, list) or any(e not in TTS_ENGINES for e in fb):
        errors.append(f"tts.fallback_engines: must be a list of {list(TTS_ENGINES)}, got {fb!r}")
    tlang, _ = _get(data, "tts.language")
    if normalize_language(tlang) not in APP_LANGUAGES:
        errors.append(f"tts.language: {tlang!r} is not one of {list(APP_LANGUAGES)}")
    num("tts.speed", 0.25, 4.0)
    num("tts.volume", 0.0, 1.0)
    num("tts.max_chars", 1, integer=True)
    for eng in TTS_ENGINES:
        boolean(f"tts.engines.{eng}.enabled")
    num("tts.engines.windows.rate_per_speed_unit", 0, 10)
    num("tts.engines.windows.timeout_s", 0.1)
    for k in ("base_wpm", "min_wpm", "max_wpm"):
        num(f"tts.engines.espeak.{k}", 1, 1000, integer=True)
    num("tts.engines.espeak.max_amplitude", 0, 200, integer=True)
    num("tts.engines.espeak.timeout_s", 0.1)

    # audio / pipeline / app
    choice("audio.policy", ("queue", "interrupt", "drop_if_busy"))
    num("audio.max_queue_size", 1, integer=True)
    num("audio.max_age_s", 0)
    num("audio.max_frame_age_s", 0)
    num("audio.shutdown_timeout_s", 0)
    num("pipeline.frame_wait_timeout_s", 0.01)
    num("pipeline.join_timeout_s", 0.1)
    boolean("pipeline.stale_frame.enabled")
    num("pipeline.stale_frame.max_frame_age_s", 0)
    num("pipeline.stale_frame.max_seq_distance", 0, integer=True)
    num("app.max_history", 1, integer=True)
    choice("app.log_level", ("DEBUG", "INFO", "WARNING", "ERROR"))
    boolean("app.offline_mode")
    return errors


class Config:
    def __init__(self, filepath: str = "config.json"):
        self.filepath = filepath
        if not os.path.exists(self.filepath):
            self.data = copy.deepcopy(DEFAULT_CONFIG)
            self.save()
        else:
            self.load()

    def load(self):
        """Load, migrate and validate. Raises ConfigError instead of silently resetting the file."""
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError([f"{self.filepath}: cannot read JSON ({e})"]) from e
        if not isinstance(saved, dict):
            raise ConfigError([f"{self.filepath}: top level must be an object"])
        for note in migrate(saved):
            logger.info("config migration: %s", note)
        data = copy.deepcopy(DEFAULT_CONFIG)
        _merge(data, saved)
        errors = validate(data)
        if errors:
            raise ConfigError(errors)
        self.data = data
        self.save()  # persist new defaults / migrations

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def preview(self, patch: Dict) -> Dict[str, Any]:
        """Return the config that would result from ``patch`` (validated), without applying it."""
        patch = copy.deepcopy(patch)
        migrate(patch)
        data = copy.deepcopy(self.data)
        _merge(data, patch)
        errors = validate(data)
        if errors:
            raise ConfigError(errors)
        return data

    def update(self, patch: Dict):
        """Validate and merge patch into config data. Raises ConfigError; nothing changes on error."""
        self.data = self.preview(patch)
        self.save()
