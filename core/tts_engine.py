# core/tts_engine.py
import logging
import sounddevice as sd
import soundfile as sf
import numpy as np
import os
import subprocess
from typing import Optional

logger = logging.getLogger("tts_engine")

# Try coqui TTS
COQUI_AVAILABLE = False
try:
    from TTS.api import TTS as CoquiTTS
    COQUI_AVAILABLE = True
except Exception:
    COQUI_AVAILABLE = False


class TTSEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.engine = cfg.get("engine", "coqui")
        self.coqui = None
        self.last_audio_path = None
        if self.engine == "coqui" and COQUI_AVAILABLE:
            try:
                model = cfg.get("coqui_model", "tts_models/en/vctk/vits")
                if model:
                    self.coqui = CoquiTTS(model_name=model, progress_bar=False, gpu=False)
                    logger.info("Coqui TTS loaded: %s", model)
            except Exception as e:
                logger.warning("Failed to initialize Coqui TTS. Please ensure you have 'espeak-ng' installed (`sudo apt-get install espeak-ng` on Debian/Ubuntu, or see your distribution's package manager). Error: %s", e)
                self.coqui = None

    def _play_numpy_audio(self, audio: np.ndarray, sr: int):
        try:
            sd.play(audio, samplerate=sr)
            sd.wait()
        except Exception as e:
            logger.debug("sounddevice playback failed: %s", e)
            tmp = "last_audio.wav"
            sf.write(tmp, audio, sr)
            self.last_audio_path = tmp
            try:
                if os.name == "nt":
                    os.startfile(tmp)
                else:
                    subprocess.Popen(["xdg-open", tmp])
            except Exception:
                pass

    def speak(self, text: str, voice: Optional[str] = "p335", speed: float = 1.0, volume: float = 0.9):
        if not text:
            return
        if self.coqui:
            try:
                audio = None
                sr = 22050
                try:
                    audio = self.coqui.tts(text=text, speaker=voice, speed=speed)
                except TypeError:
                    audio = self.coqui.tts(text)
                if isinstance(audio, str):
                    self.last_audio_path = audio
                    data, sr = sf.read(audio, dtype="float32")
                    self._play_numpy_audio(data, sr)
                elif isinstance(audio, np.ndarray):
                    self._play_numpy_audio(audio, sr)
                else:
                    logger.warning("Coqui returned unexpected audio type: %s", type(audio))
            except Exception as e:
                logger.warning("Coqui playback failed, falling back: %s", e)
                self._espeak(text, speed, volume, voice)
        else:
            self._espeak(text, speed, volume, voice)

    def _espeak(self, text: str, speed: float, volume: float, voice: Optional[str] = None):
        try:
            if os.name == "posix":
                cmd = ["espeak-ng", f"-s{int(150*speed)}", f"-a{int(100*volume*100)}"]
                if voice:
                    cmd += ["-v", voice]  # e.g. "en+f3" for female voice
                cmd.append(text)
                subprocess.run(cmd, check=False)
            elif os.name == "nt":
                # Text and voice are passed via environment variables, never interpolated
                # into the script: OCR text is untrusted and would otherwise run as PowerShell.
                # See docs/adr/0001-tts-powershell-injection.md.
                env = dict(os.environ, SVA_TTS_TEXT=text, SVA_TTS_VOICE=voice or "")
                ps = (
                    'Add-Type -AssemblyName System.Speech; '
                    '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
                    'if ($env:SVA_TTS_VOICE) { $s.SelectVoice($env:SVA_TTS_VOICE) }; '
                    f'$s.Rate={int((speed-1)*5)}; '
                    f'$s.Volume={int(100*volume)}; '
                    '$s.Speak($env:SVA_TTS_TEXT);'
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, env=env)
            else:
                print(text)
        except Exception as e:
            logger.exception("Fallback TTS failed: %s", e)