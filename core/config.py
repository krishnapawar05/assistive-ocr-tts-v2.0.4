# core/config.py
import json
import os
from typing import Dict

DEFAULT_CONFIG = {
    "camera": {
        "source_type": "opencv",
        "camera_id": 0,
        "resolution": "720p"  # 720p for speed (2x faster than 1080p)
    },
    "ocr": {
        "engine": "tesseract",
        "language": "eng",
        "capture_interval": 0.05,  # Ultra-fast: 20 FPS processing for instant detection
        "min_confidence": 0.4,  # Lower threshold for faster detection
        "min_text_len": 2  # Allow shorter text for faster detection
    },
    "tts": {
        "engine": "coqui",         # coqui or espeak
        "coqui_model": "tts_models/en/vctk/vits",
        "voice": "p335",        # speaker / voice for coqui
        "speed": 1.0,
        "volume": 0.9
    },
    "app": {
        "high_contrast": False,
        "font_size": "16px",
        "max_history": 50
    }
}

class Config:
    def __init__(self, filepath: str = "config.json"):
        self.filepath = filepath
        if not os.path.exists(self.filepath):
            self.data = json.loads(json.dumps(DEFAULT_CONFIG))
            self.save()
        else:
            self.load()

    def _merge_defaults(self, base: dict, override: Dict):
        """Recursively merge saved values into defaults so new keys keep defaults."""
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                self._merge_defaults(base[k], v)
            else:
                base[k] = v

    def load(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                saved = json.load(f)
                base = json.loads(json.dumps(DEFAULT_CONFIG))
                self._merge_defaults(base, saved)
                self.data = base
                # persist to add any new defaults
                self.save()
        except Exception:
            self.data = json.loads(json.dumps(DEFAULT_CONFIG))
            self.save()

    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def update(self, patch: Dict):
        """Recursively merge patch into config data."""
        self._merge_defaults(self.data, patch)
        self.save()