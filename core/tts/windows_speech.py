"""Windows System.Speech adapter (development fallback).

The PowerShell scripts below are constant strings. Text and voice are passed through
environment variables and read as data (ADR 0001); they are never interpolated.
"""
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

from ..status import EngineStatus
from .base import TTSAdapter, TTSError, TTSErrorCode, clamp, logger

_LIST_VOICES = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.GetInstalledVoices() | Where-Object { $_.Enabled } | "
    "ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture.Name }"
)

_SPEAK = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "if ($env:SVA_TTS_VOICE) { $s.SelectVoice($env:SVA_TTS_VOICE) }; "
    "$s.Rate = [int]$env:SVA_TTS_RATE; "
    "$s.Volume = [int]$env:SVA_TTS_VOLUME; "
    "$s.Speak($env:SVA_TTS_TEXT)"
)


class WindowsSpeechAdapter(TTSAdapter):
    name = "windows"

    def __init__(self, engine_cfg, tts_cfg):
        super().__init__(engine_cfg, tts_cfg)
        self._powershell: Optional[str] = None
        self._voices: List[Tuple[str, str]] = []  # (name, culture)
        self._voice: str = ""
        self._proc: Optional[subprocess.Popen] = None

    def _load(self):
        if os.name != "nt":
            return EngineStatus.NOT_AVAILABLE, "Windows only"
        ps = shutil.which("powershell")
        if not ps:
            return EngineStatus.NOT_AVAILABLE, "powershell not found"
        out = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", _LIST_VOICES],
                             capture_output=True, timeout=float(self.cfg["timeout_s"]), check=False)
        self._voices = [tuple(line.split("|", 1)) for line in out.stdout.decode("utf-8", "replace").splitlines()
                        if "|" in line]
        if not self._voices:
            return EngineStatus.NOT_AVAILABLE, "no enabled System.Speech voices"
        self._powershell = ps
        wanted = self.cfg.get("voice") or ""
        if wanted and wanted in [n for n, _ in self._voices]:
            self._voice = wanted
        else:
            if wanted:
                logger.warning("Windows voice '%s' not installed; choosing by language", wanted)
            match = [n for n, culture in self._voices if culture.lower().startswith(self.language + "-")]
            if not match:
                return EngineStatus.LANGUAGE_NOT_SUPPORTED, (
                    f"no installed voice for '{self.language}' (have: {', '.join(c for _, c in self._voices)})")
            self._voice = match[0]
        return EngineStatus.READY, f"System.Speech voice={self._voice}"

    @property
    def rate(self) -> int:
        return int(clamp(round((self.speed - 1.0) * float(self.cfg["rate_per_speed_unit"])), -10, 10))

    def environment(self, text: str) -> dict:
        return dict(os.environ, SVA_TTS_TEXT=text, SVA_TTS_VOICE=self._voice,
                    SVA_TTS_RATE=str(self.rate), SVA_TTS_VOLUME=str(int(round(self.volume * 100))))

    def command(self) -> List[str]:
        return [self._powershell, "-NoProfile", "-NonInteractive", "-Command", _SPEAK]

    def _speak(self, text: str) -> None:
        self._proc = subprocess.Popen(self.command(), env=self.environment(text), stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            _, err = self._proc.communicate(timeout=float(self.cfg["timeout_s"]))
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.communicate()
            raise TTSError(TTSErrorCode.TIMEOUT, self.name, "System.Speech did not finish")
        finally:
            rc, self._proc = (self._proc.returncode if self._proc else None), None
        if (rc not in (0, None) or err.strip()) and not self._stop_requested.is_set():
            raise TTSError(TTSErrorCode.SYNTHESIS_FAILED, self.name,
                           f"exit {rc}: {err.decode('utf-8', 'replace').strip()[:200]}")

    def _stop(self) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def get_voices(self) -> List[str]:
        return [n for n, _ in self._voices]

    def get_languages(self) -> List[str]:
        return sorted({c.split("-")[0] for _, c in self._voices})
