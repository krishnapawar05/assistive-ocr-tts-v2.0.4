"""eSpeak NG adapter.

Text goes to espeak-ng on stdin (``--stdin``), never on the command line: OCR text such as
"-w out.wav" would otherwise be parsed as an option.
"""
import os
import shutil
import subprocess
from typing import List, Optional

from ..languages import engine_language
from ..status import EngineStatus
from .base import TTSAdapter, TTSError, TTSErrorCode, clamp, logger


class EspeakAdapter(TTSAdapter):
    name = "espeak"

    def __init__(self, engine_cfg, tts_cfg):
        super().__init__(engine_cfg, tts_cfg)
        self.executable: Optional[str] = None
        self._voices: List[str] = []
        self._resolved_voice: Optional[str] = None  # set by _load() after distro-aware fallback
        self._proc: Optional[subprocess.Popen] = None

    def _find_executable(self) -> Optional[str]:
        configured = self.cfg.get("executable")
        if configured:
            return configured if os.path.isfile(configured) else None
        for name in ("espeak-ng", "espeak"):
            found = shutil.which(name)
            if found:
                return found
        return next((p for p in self.cfg.get("search_paths", []) if os.path.isfile(p)), None)

    def _load(self):
        exe = self._find_executable()
        if not exe:
            return EngineStatus.NOT_AVAILABLE, "espeak-ng executable not found (see README 'eSpeak NG')"
        out = subprocess.run([exe, "--voices"], capture_output=True, timeout=float(self.cfg["timeout_s"]),
                             check=False)
        lines = out.stdout.decode("utf-8", "replace").splitlines()[1:]
        self._voices = sorted({ln.split()[1] for ln in lines if len(ln.split()) > 1})
        self.executable = exe
        voice = self.voice
        if voice not in self._voices:
            # Try prefix match: 'en-us' → first voice starting with 'en' (e.g. 'en-gb' on some distros)
            prefix = voice.split("-")[0]
            fallback = next((v for v in self._voices if v.startswith(prefix + "-") or v == prefix), None)
            if fallback:
                logger.info("espeak voice '%s' not found; using '%s' instead", voice, fallback)
                self._resolved_voice = fallback
                voice = fallback
            else:
                return EngineStatus.LANGUAGE_NOT_SUPPORTED, (
                    f"espeak voice '{voice}' not installed "
                    f"(available: {', '.join(self._voices[:10])}{'...' if len(self._voices) > 10 else ''})"
                )
        else:
            self._resolved_voice = voice
        return EngineStatus.READY, f"espeak-ng at {exe}, voice={voice}"

    @property
    def voice(self) -> str:
        # Return the distro-resolved voice if _load() found a fallback, otherwise use config/language map
        if self._resolved_voice:
            return self._resolved_voice
        return self.cfg.get("voice") or engine_language(self.name, self.language)

    @property
    def amplitude(self) -> int:
        """Map app volume 0.0-1.0 onto espeak's 0-max_amplitude (espeak accepts 0-200)."""
        return int(round(clamp(self.volume, 0.0, 1.0) * int(self.cfg["max_amplitude"])))

    @property
    def words_per_minute(self) -> int:
        wpm = round(int(self.cfg["base_wpm"]) * self.speed)
        return int(clamp(wpm, int(self.cfg["min_wpm"]), int(self.cfg["max_wpm"])))

    def command(self) -> List[str]:
        return [self.executable, "-b", "1", "--stdin", "-v", self.voice,
                "-s", str(self.words_per_minute), "-a", str(self.amplitude)]

    def _speak(self, text: str) -> None:
        self._proc = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE)
        try:
            _, err = self._proc.communicate(text.encode("utf-8"), timeout=float(self.cfg["timeout_s"]))
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise TTSError(TTSErrorCode.TIMEOUT, self.name, "espeak-ng did not finish")
        finally:
            rc, self._proc = (self._proc.returncode if self._proc else None), None
        if rc not in (0, None) and not self._stop_requested.is_set():
            raise TTSError(TTSErrorCode.SYNTHESIS_FAILED, self.name,
                           f"exit {rc}: {err.decode('utf-8', 'replace').strip()[:200]}")
        logger.debug("espeak spoke %d chars", len(text))

    def _stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def get_voices(self) -> List[str]:
        return list(self._voices)
