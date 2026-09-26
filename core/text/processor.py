"""Conservative OCR text normalization and validation.

It cleans OCR artifacts (control characters, stray edge symbols, symbol runs, whitespace)
but never rewrites words: "Room 204" stays "Room 204".
"""
import re
import unicodedata
from typing import Any, Dict, Tuple

from ..languages import char_in_script

_WS = re.compile(r"\s+")


def _is_word_char(ch: str) -> bool:
    # Letters, digits and combining marks (needed for Devanagari/Kannada vowel signs).
    return unicodedata.category(ch)[0] in ("L", "N", "M")


class TextProcessor:
    def __init__(self, text_cfg: Dict[str, Any], min_text_len: int):
        self.cfg = text_cfg
        self.min_text_len = int(min_text_len)
        self.allowed_punct = set(text_cfg["allowed_punctuation"])
        self.edge_strip = text_cfg["edge_strip_chars"] + " "
        self.max_symbol_run = int(text_cfg["max_symbol_run"])
        self.min_validity = float(text_cfg["min_validity"])
        self._symbol_run = re.compile(r"([^\w\s])\1{%d,}" % self.max_symbol_run)

    # ----- cleaning ------------------------------------------------------------------------
    def clean(self, text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize(self.cfg["unicode_form"], text)
        # Drop control/format characters (keep whitespace, which is normalized below).
        text = "".join(ch for ch in text if ch.isspace() or unicodedata.category(ch)[0] != "C")
        text = _WS.sub(" ", text).strip()
        text = self._symbol_run.sub(lambda m: m.group(1) * self.max_symbol_run, text)
        # Remove tokens that consist only of disallowed symbols (e.g. "|", "~~", "«»").
        tokens = [t for t in text.split(" ")
                  if any(_is_word_char(c) for c in t) or all(c in self.allowed_punct for c in t)]
        text = " ".join(tokens)
        return text.strip(self.edge_strip)

    # ----- measurements (0..1) -------------------------------------------------------------
    def validity(self, text: str) -> float:
        """Share of non-space characters that are letters/digits/marks or allowed punctuation."""
        chars = [c for c in text if not c.isspace()]
        if not chars:
            return 0.0
        good = sum(1 for c in chars if _is_word_char(c) or c in self.allowed_punct)
        return good / len(chars)

    def garbage_fraction(self, text: str) -> float:
        return 1.0 - self.validity(text) if text.strip() else 1.0

    def language_consistency(self, text: str, language: str) -> float:
        """Share of letters that belong to the language's script. Digits-only text scores 1."""
        letters = [c for c in text if unicodedata.category(c)[0] in ("L", "M")]
        if not letters:
            return 1.0 if any(c.isdigit() for c in text) else 0.0
        return sum(1 for c in letters if char_in_script(c, language)) / len(letters)

    @staticmethod
    def repetition_fraction(text: str) -> float:
        """How much of the text is repeated tokens (OCR from overlapping regions)."""
        tokens = [t.casefold() for t in text.split()]
        if len(tokens) < 2:
            return 0.0
        return 1.0 - len(set(tokens)) / len(tokens)

    def is_valid(self, text: str) -> Tuple[bool, str]:
        if len(text) < self.min_text_len:
            return False, "too_short"
        if not any(_is_word_char(c) for c in text):
            return False, "no_letters_or_digits"
        if self.validity(text) < self.min_validity:
            return False, "low_validity"
        return True, "ok"


def duplicate_key(text: str) -> str:
    """Case/space/punctuation-insensitive key: 'Room 204.' / 'Room204' -> 'room204'."""
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in text if _is_word_char(c))
