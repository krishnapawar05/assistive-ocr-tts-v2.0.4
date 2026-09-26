"""Offline-first switches for model libraries (rule 5). Call before loading any model."""
import os

OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",                         # huggingface_hub: never contact the Hub
    "TRANSFORMERS_OFFLINE": "1",                   # transformers: local files only
    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",  # PaddleX: skip model-hoster connectivity check
}


def apply_offline_env(enabled: bool) -> None:
    if enabled:
        for key, value in OFFLINE_ENV.items():
            os.environ.setdefault(key, value)
