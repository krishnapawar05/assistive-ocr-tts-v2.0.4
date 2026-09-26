"""Run the full test suite and print a PASS / FAIL / NOT_AVAILABLE matrix per engine.

  .venv/Scripts/python.exe scripts/run_tests.py [--fast]    (--fast: unit tests only)

Engine status rules:
  FAIL           any test of that engine failed or errored (including INIT_FAILED)
  NOT_AVAILABLE  every test was skipped with a "NOT_AVAILABLE" reason (missing runtime/model)
  PASS           tests ran and none failed
Exit code is non-zero if anything failed.
"""
import argparse
import collections
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENGINE_CLASSES = {
    "tests.ocr.test_tesseract.TesseractEngineTest": ("OCR", "tesseract"),
    "tests.ocr.test_easyocr.EasyOCREngineTest": ("OCR", "easyocr"),
    "tests.ocr.test_paddleocr.PaddleOCREngineTest": ("OCR", "paddle"),
    "tests.ocr.test_trocr.TrOCREngineTest": ("OCR", "trocr"),
    "tests.integration.test_tts_pipeline.CoquiLiveTest": ("TTS", "coqui"),
    "tests.integration.test_tts_pipeline.WindowsSpeechLiveTest": ("TTS", "windows"),
    "tests.integration.test_tts_pipeline.EspeakLiveTest": ("TTS", "espeak"),
}


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.outcomes = collections.defaultdict(list)  # class id -> [(outcome, reason)]

    @staticmethod
    def _cls(test):
        return f"{type(test).__module__}.{type(test).__name__}"

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[self._cls(test)].append(("pass", ""))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[self._cls(test)].append(("fail", str(err[1])[:200]))

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[self._cls(test)].append(("fail", str(err[1])[:200]))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.outcomes[self._cls(test)].append(("fail", str(err[1])[:200]))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[self._cls(test)].append(("skip", reason))


def engine_status(outcomes):
    if not outcomes:
        return "NOT RUN", ""
    if any(o == "fail" for o, _ in outcomes):
        return "FAIL", next(r for o, r in outcomes if o == "fail")
    if all(o == "skip" for o, _ in outcomes):
        reason = outcomes[0][1]
        return ("NOT_AVAILABLE" if reason.startswith("NOT_AVAILABLE") else "SKIPPED"), reason
    skipped = [r for o, r in outcomes if o == "skip"]
    return "PASS", (f"{len(skipped)} check(s) skipped" if skipped else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()
    start_dir = os.path.join(ROOT, "tests", "unit") if args.fast else os.path.join(ROOT, "tests")
    suite = unittest.TestLoader().discover(start_dir, top_level_dir=ROOT)
    runner = unittest.TextTestRunner(resultclass=RecordingResult, verbosity=1)
    t0 = time.time()
    result = runner.run(suite)

    print("\n=== Engine matrix ===")
    for cls, (kind, engine) in ENGINE_CLASSES.items():
        if args.fast:
            break
        status, reason = engine_status(result.outcomes.get(cls, []))
        print(f"{kind:4s} {engine:10s} {status:14s} {reason}")
    print(f"\nTotal: {result.testsRun} tests, {len(result.failures)} failures, {len(result.errors)} errors, "
          f"{len(result.skipped)} skipped in {time.time() - t0:.0f}s")
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
