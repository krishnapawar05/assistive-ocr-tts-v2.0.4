"""Language identifiers.

The application uses short codes ("en", "hi", "kn"). Each engine has its own identifiers,
e.g. Tesseract traineddata names ("eng", "hin", "kan") or PaddleOCR's "ka" for Kannada.
Legacy v2.0.4 configs stored Tesseract-style codes in ``ocr.language``; those are accepted
as aliases.
"""
from typing import Dict, Optional

APP_LANGUAGES = ("en", "hi", "kn")

_ALIASES = {
    "en": "en", "eng": "en", "english": "en",
    "hi": "hi", "hin": "hi", "hindi": "hi",
    "kn": "kn", "kan": "kn", "kannada": "kn",
}

ENGINE_LANGUAGE_CODES: Dict[str, Dict[str, str]] = {
    "tesseract": {"en": "eng", "hi": "hin", "kn": "kan"},
    "easyocr": {"en": "en", "hi": "hi", "kn": "kn"},
    "paddle": {"en": "en", "hi": "hi", "kn": "ka"},
    "trocr": {"en": "en"},  # microsoft/trocr-base-handwritten is English-only
    "espeak": {"en": "en", "hi": "hi", "kn": "kn"},
    "coqui": {"en": "en"},
    "windows": {"en": "en", "hi": "hi", "kn": "kn"},
}

# Unicode blocks used to judge whether recognized letters belong to the configured language.
SCRIPT_RANGES: Dict[str, tuple] = {
    "en": ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F)),
    "hi": ((0x0900, 0x097F), (0xA8E0, 0xA8FF)),
    "kn": ((0x0C80, 0x0CFF),),
}


def normalize_language(code: str) -> Optional[str]:
    """Map any accepted spelling to an app language code, or None if unknown."""
    if not isinstance(code, str):
        return None
    return _ALIASES.get(code.strip().lower())


def engine_language(engine: str, app_lang: str) -> Optional[str]:
    """Engine-specific identifier for an app language, or None if the engine lacks it."""
    return ENGINE_LANGUAGE_CODES.get(engine, {}).get(app_lang)


def char_in_script(ch: str, app_lang: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in SCRIPT_RANGES.get(app_lang, ()))
