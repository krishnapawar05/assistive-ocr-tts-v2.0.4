"""TTSService: speaks through the first working engine of [engine] + fallback_engines."""
import logging
import threading
from typing import Callable, Dict, List, Optional

from ..status import EngineStatus
from .base import TTSAdapter, TTSError, TTSErrorCode

logger = logging.getLogger("tts.service")


def build_tts_adapters(tts_cfg: Dict) -> Dict[str, TTSAdapter]:
    from .coqui import CoquiTTSAdapter
    from .espeak import EspeakAdapter
    from .windows_speech import WindowsSpeechAdapter

    engines = tts_cfg["engines"]
    return {
        "coqui": CoquiTTSAdapter(engines["coqui"], tts_cfg),
        "windows": WindowsSpeechAdapter(engines["windows"], tts_cfg),
        "espeak": EspeakAdapter(engines["espeak"], tts_cfg),
    }


class TTSService:
    def __init__(self, tts_cfg: Dict, adapters: Optional[Dict[str, TTSAdapter]] = None,
                 adapter_factory: Callable[[Dict], Dict[str, TTSAdapter]] = build_tts_adapters):
        self.cfg = tts_cfg
        self.adapters = adapters if adapters is not None else adapter_factory(tts_cfg)
        self.order: List[str] = []
        for name in [tts_cfg["engine"]] + list(tts_cfg["fallback_engines"]):
            if name in self.adapters and name not in self.order:
                self.order.append(name)
        self._current: Optional[TTSAdapter] = None
        self._lock = threading.Lock()
        self.last_engine: Optional[str] = None

    def initialize(self) -> Dict[str, str]:
        for name in self.order:
            self.adapters[name].initialize()
        if not self.available_engines():
            logger.error("No TTS engine available (%s). Speech is disabled.",
                         ", ".join(f"{n}={a.status.value}" for n, a in self.adapters.items()))
        return {n: self.adapters[n].status.value for n in self.order}

    def available_engines(self) -> List[str]:
        return [n for n in self.order if self.adapters[n].is_available()]

    def speak(self, text: str) -> str:
        """Speak with the first engine that succeeds; returns its name.

        Raises TTSError(ALL_ENGINES_FAILED) if none could speak. Interruption via stop() is
        not a failure and does not trigger fallback.
        """
        failures = []
        for name in self.order:
            adapter = self.adapters[name]
            if adapter.status == EngineStatus.UNINITIALIZED:
                adapter.initialize()
            if not adapter.is_available():
                continue
            with self._lock:
                self._current = adapter
            try:
                adapter.speak(text)
                self.last_engine = name
                return name
            except TTSError as e:
                failures.append(f"{name}={e.code.value}")
                logger.warning("TTS %s failed (%s); trying next engine", name, e)
            finally:
                with self._lock:
                    self._current = None
        raise TTSError(TTSErrorCode.ALL_ENGINES_FAILED, "tts",
                       ", ".join(failures) or "no TTS engine available")

    def stop(self) -> None:
        with self._lock:
            current = self._current
        if current is not None:
            current.stop()

    def statuses(self) -> Dict[str, Dict]:
        return {n: a.describe() for n, a in self.adapters.items()}

    def voices(self) -> List[str]:
        primary = self.adapters.get(self.cfg["engine"])
        return primary.get_voices() if primary is not None and primary.is_available() else []

    def last_audio_wav(self) -> Optional[bytes]:
        coqui = self.adapters.get("coqui")
        return coqui.last_audio_wav() if coqui is not None and hasattr(coqui, "last_audio_wav") else None
