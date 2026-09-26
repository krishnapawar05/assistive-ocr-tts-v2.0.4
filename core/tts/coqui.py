"""Coqui TTS adapter (maintained ``coqui-tts`` fork; import name ``TTS``).

Models load only from local files (model_file.pth + config.json); nothing is downloaded at
runtime. Audio plays through sounddevice. The last utterance is kept in memory for the
dashboard's replay button; nothing is written to disk.
"""
import io
import os
import threading
from typing import List, Optional

import numpy as np

from ..status import EngineStatus
from .base import TTSAdapter, TTSError, TTSErrorCode, clamp, logger


class CoquiTTSAdapter(TTSAdapter):
    name = "coqui"

    def __init__(self, engine_cfg, tts_cfg):
        super().__init__(engine_cfg, tts_cfg)
        self.model_name = tts_cfg["coqui_model"]
        self.requested_voice = tts_cfg.get("voice") or ""
        self.speaker: Optional[str] = None
        self.sample_rate = 0
        self._tts = None
        self._sd = None
        self._last_wav: Optional[bytes] = None
        self._lock = threading.Lock()

    def model_dir(self) -> str:
        if self.cfg.get("model_dir"):
            return os.path.expanduser(self.cfg["model_dir"])
        try:  # coqui-tts >= 0.25 moved this helper into coqui-tts-trainer
            from trainer.io import get_user_data_dir
        except ImportError:
            from TTS.utils.generic_utils import get_user_data_dir
        return os.path.join(str(get_user_data_dir("tts")), self.model_name.replace("/", "--"))

    def _load(self):
        try:
            import sounddevice as sd
            from TTS.api import TTS
        except ImportError as e:
            return EngineStatus.NOT_AVAILABLE, f"coqui-tts not importable: {str(e).strip()[:160]}"
        except OSError as e:  # PortAudio library missing
            return EngineStatus.NOT_AVAILABLE, f"audio library unavailable: {e}"
        mdir = self.model_dir()
        model_path, config_path = os.path.join(mdir, "model_file.pth"), os.path.join(mdir, "config.json")
        if not (os.path.isfile(model_path) and os.path.isfile(config_path)):
            return EngineStatus.MODEL_NOT_AVAILABLE, f"{self.model_name} not found in {mdir}"
        self._tts = TTS(model_path=model_path, config_path=config_path, progress_bar=False,
                        gpu=bool(self.cfg.get("gpu", False)))
        self._sd = sd
        self.sample_rate = int(self._tts.synthesizer.output_sample_rate)
        # tts(speed=...) is ignored for VITS in coqui-tts 0.27; VITS reads length_scale instead.
        model = self._tts.synthesizer.tts_model
        if hasattr(model, "length_scale"):
            model.length_scale = float(model.length_scale) / clamp(self.speed, 0.25, 4.0)
        speakers = self.get_voices()
        if speakers:
            if self.requested_voice in speakers:
                self.speaker = self.requested_voice
            else:
                self.speaker = speakers[0]
                logger.warning("Coqui speaker '%s' not in model; using '%s'", self.requested_voice, self.speaker)
        return EngineStatus.READY, f"{self.model_name} speaker={self.speaker} sr={self.sample_rate}"

    def synthesize(self, text: str) -> np.ndarray:
        kwargs = {"text": text, "speed": clamp(self.speed, 0.25, 4.0)}  # honored by models that support it
        if self.speaker:
            kwargs["speaker"] = self.speaker
        with self._lock:  # the model is not thread-safe
            wav = self._tts.tts(**kwargs)
        audio = np.asarray(wav, dtype=np.float32) * np.float32(self.volume)
        return np.clip(audio, -1.0, 1.0)

    def _speak(self, text: str) -> None:
        audio = self.synthesize(text)
        if self._stop_requested.is_set():
            return
        self._last_wav = self._to_wav(audio)
        sd = self._sd
        try:
            sd.play(audio, samplerate=self.sample_rate)
            sd.wait()
        except (sd.PortAudioError, OSError) as e:
            raise TTSError(TTSErrorCode.AUDIO_DEVICE_UNAVAILABLE, self.name, str(e)) from e

    def _stop(self) -> None:
        if self._sd is not None:
            self._sd.stop()

    def _to_wav(self, audio: np.ndarray) -> bytes:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, self.sample_rate, format="WAV")
        return buf.getvalue()

    def last_audio_wav(self) -> Optional[bytes]:
        return self._last_wav

    def get_voices(self) -> List[str]:
        return list(getattr(self._tts, "speakers", None) or []) if self._tts else []
