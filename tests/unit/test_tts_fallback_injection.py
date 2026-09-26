"""Regression tests for ADR 0001: OCR text must never be interpolated into a PowerShell script.

Run from repo root:
    .venv/Scripts/python.exe -m unittest discover -s tests -t .
"""
import os
import subprocess
import unittest
from unittest import mock

from core import tts_engine
from core.tts_engine import TTSEngine

MALICIOUS = 'hello"); Remove-Item C:\\important; ("$(calc)'


class WindowsFallbackTest(unittest.TestCase):
    def setUp(self):
        self.engine = TTSEngine({"engine": "espeak"})

    def _speak_windows(self, text, voice):
        with mock.patch.object(tts_engine.os, "name", "nt"), \
                mock.patch.object(tts_engine.subprocess, "run") as run:
            self.engine._espeak(text, 1.0, 0.9, voice)
        run.assert_called_once()
        return run.call_args

    def test_text_not_in_script(self):
        args, kwargs = self._speak_windows(MALICIOUS, "p335")
        script = " ".join(args[0])
        self.assertNotIn(MALICIOUS, script)
        self.assertNotIn("Remove-Item", script)
        self.assertNotIn("p335", script)

    def test_text_and_voice_passed_via_env(self):
        _, kwargs = self._speak_windows(MALICIOUS, "p335")
        self.assertEqual(kwargs["env"]["SVA_TTS_TEXT"], MALICIOUS)
        self.assertEqual(kwargs["env"]["SVA_TTS_VOICE"], "p335")

    def test_no_voice_passes_empty(self):
        _, kwargs = self._speak_windows("Room 204", None)
        self.assertEqual(kwargs["env"]["SVA_TTS_VOICE"], "")


@unittest.skipUnless(os.name == "nt", "requires Windows PowerShell")
class WindowsLivePowerShellTest(unittest.TestCase):
    def test_env_text_is_inert(self):
        """Run the same env-var mechanism for real, with Write-Output instead of Speak."""
        marker = os.path.join(os.environ.get("TEMP", "."), "sva_injection_marker.txt")
        if os.path.exists(marker):
            os.remove(marker)
        payload = f'x"); New-Item -Path "{marker}" -ItemType File; ("'
        env = dict(os.environ, SVA_TTS_TEXT=payload)
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Write-Output $env:SVA_TTS_TEXT"],
            env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(out.stdout.strip(), payload)
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
