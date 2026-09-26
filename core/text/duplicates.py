"""Suppress repeated readings of the same text across frames."""
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from rapidfuzz import fuzz

from .processor import duplicate_key

_DIGITS = re.compile(r"\d+")

class DuplicateFilter:
    """Exact, normalized and fuzzy duplicate detection within a cooldown window.

    With ``refresh_on_repeat`` a text that stays in view keeps being suppressed; it is spoken
    again only after it has been absent for ``cooldown_s``.
    """

    def __init__(self, cfg: Dict[str, Any], clock=time.monotonic):
        self.cooldown_s = float(cfg["cooldown_s"])
        self.fuzzy_threshold = float(cfg["fuzzy_threshold"])
        self.refresh_on_repeat = bool(cfg["refresh_on_repeat"])
        self.max_entries = int(cfg["max_entries"])
        self._clock = clock
        self._seen: "OrderedDict[str, float]" = OrderedDict()  # key -> last seen time
        self._lock = threading.Lock()

    def check(self, text: str, now: Optional[float] = None) -> Tuple[bool, str]:
        """Return (is_duplicate, match_kind) and record the sighting."""
        now = self._clock() if now is None else now
        key = duplicate_key(text)
        with self._lock:
            self._expire(now)
            match, kind = self._match(key)
            if match is not None:
                if self.refresh_on_repeat:
                    self._seen[match] = now
                    self._seen.move_to_end(match)
                return True, kind
            self._seen[key] = now
            while len(self._seen) > self.max_entries:
                self._seen.popitem(last=False)
            return False, "new"

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()

    def _expire(self, now: float) -> None:
        for key in [k for k, t in self._seen.items() if now - t > self.cooldown_s]:
            del self._seen[key]

    def _match(self, key: str):
        if not key:
            return None, ""
        if key in self._seen:
            return key, "exact"
        digits = _DIGITS.findall(key)
        for prev in self._seen:
            # Numbers carry the meaning ("Room 204" vs "Room 1204"): they must match exactly.
            if _DIGITS.findall(prev) == digits and fuzz.ratio(key, prev) >= self.fuzzy_threshold:
                return prev, "fuzzy"
        return None, ""
