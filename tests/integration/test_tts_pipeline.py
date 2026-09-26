"""Live TTS engine tests (real engines, volume 0 so they are silent).

Each engine is PASS, FAIL, or NOT_AVAILABLE (tests skipped with that reason).
"""
import os
import tempfile
import unittest

import numpy as np

from core.status import UNAVAILABLE_STATUSES, EngineStatus
from core.tts.coqui import CoquiTTSAdapter
from core.tts.espeak import EspeakAdapter
from core.tts.service import TTSService
from core.tts.windows_speech import WindowsSpeechAdapter
from tests.helpers import default_config, no_network

os.environ.setdefault("HF_HUB_OFFLINE", "1")


def silent_cfg(**kw):
    cfg = default_config()["tts"]
    cfg["volume"] = 0.0
    cfg.update(kw)
    return cfg


_CACHE = {}


def adapter(cls, **kw):
    key = (cls, tuple(sorted(kw.items())))
    if key not in _CACHE:
        cfg = silent_cfg(**kw)
        a = cls(cfg["engines"][cls.name], cfg)
        with no_network() as guard:
            a.initialize()
        a.network_attempts = list(guard.attempts)
        _CACHE[key] = a
    return _CACHE[key]


def hostile_payloads(marker):
    m = marker.replace("\\", "\\\\")
    return [
        'Room "204"',
        "$(whoami)",
        "; Get-Process",
        "`whoami`",
        "& echo hacked",
        f'"); New-Item -Path "{marker}" -ItemType File; ("',
        f"$(New-Item -Path '{marker}' -ItemType File)",
        f"-w {marker}",
        f"& type nul > {m}",
    ]


class LiveEngineMixin:
    cls = None

    def setUp(self):
        self.a = adapter(self.cls)
        if self.a.status in UNAVAILABLE_STATUSES:
            self.skipTest(f"NOT_AVAILABLE: {self.a.status.value}: {self.a.status_detail}")
        self.assertEqual(self.a.status, EngineStatus.READY, self.a.status_detail)  # INIT_FAILED -> FAIL

    def test_initializes_offline(self):
        self.assertEqual(self.a.status, EngineStatus.READY)
        self.assertEqual(self.a.network_attempts, [])

    def test_speaks_english(self):
        with no_network():
            self.assertTrue(self.a.speak("Room 204"))

    def test_hostile_text_never_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "pwned.txt")
            for text in hostile_payloads(marker):
                with self.subTest(text=text):
                    self.a.speak(text)
                    self.assertFalse(os.path.exists(marker), f"command executed via {text!r}")
            self.assertEqual(os.listdir(tmp), [])

    def test_voices_listed(self):
        self.assertTrue(self.a.get_voices())


class EspeakLiveTest(LiveEngineMixin, unittest.TestCase):
    cls = EspeakAdapter

    def test_hindi_and_kannada_voices(self):
        for lang in ("hi", "kn"):
            with self.subTest(language=lang):
                a = adapter(EspeakAdapter, language=lang)
                self.assertIn(a.status, (EngineStatus.READY, EngineStatus.LANGUAGE_NOT_SUPPORTED))
                if a.is_available():
                    self.assertTrue(a.speak({"hi": "कमरा 204", "kn": "ಕೊಠಡಿ 204"}[lang]))

    def test_volume_argument_valid(self):
        argv = self.a.command()
        self.assertEqual(argv[argv.index("-a") + 1], "0")


class WindowsSpeechLiveTest(LiveEngineMixin, unittest.TestCase):
    cls = WindowsSpeechAdapter


class CoquiLiveTest(LiveEngineMixin, unittest.TestCase):
    cls = CoquiTTSAdapter

    def test_hostile_text_never_executes(self):  # no subprocess involved; keep it quick
        with tempfile.TemporaryDirectory() as tmp:
            for text in hostile_payloads(os.path.join(tmp, "pwned.txt"))[:3]:
                self.a.synthesize(text)
            self.assertEqual(os.listdir(tmp), [])

    def test_voice_selection(self):
        self.assertEqual(self.a.speaker, "p335")
        self.assertIn("p335", self.a.get_voices())

    def test_generates_audio(self):
        a = adapter(CoquiTTSAdapter, volume=1.0)
        wav = a.synthesize("Room 204")
        self.assertEqual(wav.dtype, np.float32)
        self.assertGreater(len(wav) / a.sample_rate, 0.3)
        self.assertGreater(float(np.abs(wav).max()), 0.05)

    def test_volume_scales_audio(self):
        # VITS sampling is stochastic, so feed one fixed waveform through the adapter's scaling.
        from unittest import mock
        fixed = list(np.sin(np.linspace(0, 200, 22050)) * 0.8)
        levels = {}
        for vol in (1.0, 0.5, 0.0):
            a = adapter(CoquiTTSAdapter, volume=vol)
            with mock.patch.object(a._tts, "tts", return_value=fixed):
                levels[vol] = float(np.abs(a.synthesize("Room 204")).max())
        self.assertAlmostEqual(levels[0.5] / levels[1.0], 0.5, places=3)
        self.assertEqual(levels[0.0], 0.0)

    def test_speed_changes_duration(self):
        normal = adapter(CoquiTTSAdapter, volume=1.0).synthesize("The library closes at five")
        fast = adapter(CoquiTTSAdapter, volume=1.0, speed=1.5).synthesize("The library closes at five")
        self.assertLess(len(fast), len(normal))

    def test_replay_buffer_in_memory(self):
        self.a.speak("Room 204")
        wav = self.a.last_audio_wav()
        self.assertTrue(wav and wav[:4] == b"RIFF")


class TTSServiceLiveTest(unittest.TestCase):
    def test_fallback_chain_on_this_machine(self):
        """Coqui unavailable -> next engine speaks (TEST 9)."""
        cfg = silent_cfg()
        cfg["engines"]["coqui"]["model_dir"] = os.path.join(tempfile.gettempdir(), "sva-no-model")
        svc = TTSService(cfg)
        svc.initialize()
        if not svc.available_engines():
            self.skipTest("NOT_AVAILABLE: no fallback TTS engine on this machine")
        self.assertNotEqual(svc.adapters["coqui"].status, EngineStatus.READY)
        self.assertIn(svc.speak("Room 204"), ("windows", "espeak"))


if __name__ == "__main__":
    unittest.main()
