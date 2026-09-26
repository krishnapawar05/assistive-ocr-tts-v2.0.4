"""TTS adapters and service with mocked processes/engines (no audio)."""
import os
import subprocess
import unittest
from unittest import mock

from core.status import EngineStatus
from core.tts.base import TTSAdapter, TTSError, TTSErrorCode
from core.tts.composer import SpeechComposer
from core.tts.coqui import CoquiTTSAdapter
from core.tts.espeak import EspeakAdapter
from core.tts.service import TTSService
from core.tts.windows_speech import WindowsSpeechAdapter
from tests.helpers import default_config

HOSTILE = ['Room "204"', "$(whoami)", "; Get-Process", "`whoami`", "& echo hacked",
           "-w C:\\temp\\pwn.wav", "--path=C:\\evil", "'; Remove-Item x; '", "\"); calc; (\""]


def tts_cfg(**kw):
    cfg = default_config()["tts"]
    cfg.update(kw)
    return cfg


class FakeProc:
    def __init__(self, rc=0, err=b""):
        self.returncode = rc
        self.err = err
        self.input = None

    def communicate(self, input=None, timeout=None):
        self.input = input
        return b"", self.err

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


def ready_espeak(**cfg_over):
    cfg = tts_cfg(**cfg_over)
    a = EspeakAdapter(cfg["engines"]["espeak"], cfg)
    a.executable = "espeak-ng"
    a._voices = ["en", "hi", "kn"]
    a.status = EngineStatus.READY
    return a


class EspeakTest(unittest.TestCase):
    def test_volume_mapping_is_valid(self):
        """v2.0.4 produced -a9000 for volume 0.9 (valid range 0-200)."""
        self.assertEqual(ready_espeak(volume=0.0).amplitude, 0)
        self.assertEqual(ready_espeak(volume=0.9).amplitude, 180)
        self.assertEqual(ready_espeak(volume=1.0).amplitude, 200)
        a = ready_espeak()
        a.volume = 5.0  # out-of-range values are clamped
        self.assertEqual(a.amplitude, 200)
        a.volume = -1.0
        self.assertEqual(a.amplitude, 0)

    def test_speed_mapping_clamped(self):
        self.assertEqual(ready_espeak(speed=1.0).words_per_minute, 150)
        self.assertEqual(ready_espeak(speed=0.25).words_per_minute, 80)
        self.assertEqual(ready_espeak(speed=4.0).words_per_minute, 450)

    def test_voice_follows_language(self):
        self.assertEqual(ready_espeak(language="hi").voice, "hi")
        cfg = tts_cfg()
        cfg["engines"]["espeak"]["voice"] = "en-us"
        a = EspeakAdapter(cfg["engines"]["espeak"], cfg)
        self.assertEqual(a.voice, "en-us")

    def test_text_goes_to_stdin_not_argv(self):
        for text in HOSTILE:
            with self.subTest(text=text):
                a = ready_espeak()
                proc = FakeProc()
                with mock.patch.object(subprocess, "Popen", return_value=proc) as popen:
                    a.speak(text)
                argv = popen.call_args[0][0]
                self.assertIn("--stdin", argv)
                self.assertNotIn(text, argv)
                self.assertTrue(all(text not in arg for arg in argv))
                self.assertEqual(proc.input, text.encode("utf-8"))
                self.assertNotIn("shell", popen.call_args[1])

    def test_nonzero_exit_is_error(self):
        a = ready_espeak()
        with mock.patch.object(subprocess, "Popen", return_value=FakeProc(1, b"bad voice")):
            with self.assertRaises(TTSError) as ctx:
                a.speak("Room 204")
        self.assertEqual(ctx.exception.code, TTSErrorCode.SYNTHESIS_FAILED)

    def test_missing_executable_not_available(self):
        cfg = tts_cfg()
        cfg["engines"]["espeak"]["executable"] = "C:\\nope\\espeak-ng.exe"
        a = EspeakAdapter(cfg["engines"]["espeak"], cfg)
        self.assertEqual(a.initialize(), EngineStatus.NOT_AVAILABLE)


class WindowsSpeechTest(unittest.TestCase):
    def ready(self, **kw):
        cfg = tts_cfg(**kw)
        a = WindowsSpeechAdapter(cfg["engines"]["windows"], cfg)
        a._powershell = "powershell"
        a._voice = "Microsoft Zira Desktop"
        a.status = EngineStatus.READY
        return a

    def test_hostile_text_only_in_environment(self):
        for text in HOSTILE:
            with self.subTest(text=text):
                a = self.ready()
                with mock.patch.object(subprocess, "Popen", return_value=FakeProc()) as popen:
                    a.speak(text)
                argv = popen.call_args[0][0]
                self.assertTrue(all(text not in arg for arg in argv))
                self.assertEqual(popen.call_args[1]["env"]["SVA_TTS_TEXT"], text)

    def test_rate_and_volume(self):
        a = self.ready(speed=1.0, volume=0.9)
        self.assertEqual(a.rate, 0)
        env = a.environment("x")
        self.assertEqual(env["SVA_TTS_VOLUME"], "90")
        self.assertEqual(self.ready(speed=4.0).rate, 10)
        self.assertEqual(self.ready(speed=0.25).rate, -4)

    def test_stderr_is_failure(self):
        a = self.ready()
        with mock.patch.object(subprocess, "Popen", return_value=FakeProc(0, b"Exception calling Speak")):
            with self.assertRaises(TTSError):
                a.speak("Room 204")

    @unittest.skipIf(os.name == "nt", "non-Windows check")
    def test_not_available_off_windows(self):
        cfg = tts_cfg()
        self.assertEqual(WindowsSpeechAdapter(cfg["engines"]["windows"], cfg).initialize(),
                         EngineStatus.NOT_AVAILABLE)


class CoquiTest(unittest.TestCase):
    def test_missing_model_is_controlled(self):
        cfg = tts_cfg()
        cfg["engines"]["coqui"]["model_dir"] = os.path.join(os.path.dirname(__file__), "no_such_model")
        a = CoquiTTSAdapter(cfg["engines"]["coqui"], cfg)
        status = a.initialize()
        self.assertIn(status, (EngineStatus.MODEL_NOT_AVAILABLE, EngineStatus.NOT_AVAILABLE))

    def test_language_not_supported(self):
        cfg = tts_cfg(language="hi")
        self.assertEqual(CoquiTTSAdapter(cfg["engines"]["coqui"], cfg).initialize(),
                         EngineStatus.LANGUAGE_NOT_SUPPORTED)


class FakeTTS(TTSAdapter):
    def __init__(self, name, fail=None, status=EngineStatus.READY):
        self.name = name
        cfg = tts_cfg()
        super().__init__({"enabled": True}, cfg)
        self._status = status
        self.fail = fail
        self.spoken = []

    def _load(self):
        return self._status, "fake"

    def _speak(self, text):
        if self.fail:
            raise TTSError(self.fail, self.name, "fake failure")
        self.spoken.append(text)

    def _stop(self):
        pass


class TTSServiceTest(unittest.TestCase):
    def svc(self, adapters, engine, fallbacks):
        s = TTSService(tts_cfg(engine=engine, fallback_engines=fallbacks), adapters={a.name: a for a in adapters})
        s.initialize()
        return s

    def test_primary_used(self):
        c, w = FakeTTS("coqui"), FakeTTS("windows")
        self.assertEqual(self.svc([c, w], "coqui", ["windows"]).speak("hi there"), "coqui")
        self.assertEqual(w.spoken, [])

    def test_unavailable_primary_falls_back(self):
        c = FakeTTS("coqui", status=EngineStatus.NOT_AVAILABLE)
        w = FakeTTS("windows")
        self.assertEqual(self.svc([c, w], "coqui", ["windows"]).speak("Room 204"), "windows")

    def test_failing_primary_falls_back(self):
        c = FakeTTS("coqui", fail=TTSErrorCode.AUDIO_DEVICE_UNAVAILABLE)
        e = FakeTTS("espeak")
        self.assertEqual(self.svc([c, e], "coqui", ["espeak"]).speak("Room 204"), "espeak")
        self.assertEqual(e.spoken, ["Room 204"])

    def test_all_fail_is_controlled_error(self):
        adapters = [FakeTTS("coqui", status=EngineStatus.MODEL_NOT_AVAILABLE),
                    FakeTTS("windows", fail=TTSErrorCode.SYNTHESIS_FAILED),
                    FakeTTS("espeak", status=EngineStatus.NOT_AVAILABLE)]
        with self.assertLogs("tts.service", level="ERROR"):
            s = self.svc([adapters[0], adapters[2]], "coqui", ["espeak"])
        with self.assertRaises(TTSError) as ctx:
            s.speak("Room 204")
        self.assertEqual(ctx.exception.code, TTSErrorCode.ALL_ENGINES_FAILED)
        s2 = self.svc(adapters, "coqui", ["windows", "espeak"])
        with self.assertRaises(TTSError):
            s2.speak("Room 204")

    def test_empty_text_rejected(self):
        a = FakeTTS("coqui")
        a.initialize()
        with self.assertRaises(TTSError) as ctx:
            a.speak("   ")
        self.assertEqual(ctx.exception.code, TTSErrorCode.INVALID_INPUT)
        self.assertEqual(a.spoken, [])

    def test_unavailable_adapter_refuses(self):
        a = FakeTTS("coqui", status=EngineStatus.NOT_AVAILABLE)
        a.initialize()
        with self.assertRaises(TTSError) as ctx:
            a.speak("Room 204")
        self.assertEqual(ctx.exception.code, TTSErrorCode.ENGINE_NOT_AVAILABLE)


class ComposerTest(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(SpeechComposer(300).compose("Room 204"), "Room 204")

    def test_empty(self):
        self.assertIsNone(SpeechComposer(300).compose("  "))

    def test_long_text_cut_at_word(self):
        out = SpeechComposer(20).compose("The quick brown fox jumps over the lazy dog")
        self.assertEqual(out, "The quick brown fox")


if __name__ == "__main__":
    unittest.main()
