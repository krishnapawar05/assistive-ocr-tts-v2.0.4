"""Run the full test suite and print a PASS / FAIL / NOT_AVAILABLE matrix per engine.

  .venv/Scripts/python.exe scripts/run_tests.py [--fast] [--module-timeout S] [--min-available-gb G]
      --fast: unit tests only

Each test module runs in its own child process, so the models one module loads (EasyOCR,
PaddleOCR, TrOCR, Coqui...) are released before the next module starts. In a single process the
module-level engine caches accumulate to >2.5 GB, which exhausts RAM on 8 GB machines.
Per-module peak RSS is printed so memory regressions are visible. If system available RAM stays
below --min-available-gb for LOW_MEMORY_GRACE_S, that module is killed (reported as a failure) and
the run continues, instead of the machine thrashing.

Engine status rules:
  FAIL           any test of that engine failed or errored (including INIT_FAILED)
  NOT_AVAILABLE  every test was skipped with a "NOT_AVAILABLE" reason (missing runtime/model)
  PASS           tests ran and none failed
A module whose child process crashes, times out or is killed for low memory counts as a failure.
Exit code is non-zero if anything failed.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import psutil

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
DEFAULT_MODULE_TIMEOUT_S = 1800
DEFAULT_MIN_AVAILABLE_GB = 0.3
LOW_MEMORY_GRACE_S = 5.0
MONITOR_INTERVAL_S = 0.5


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


def discover_modules(start_dir):
    """Dotted names of every test module under start_dir, in discovery order."""
    suite = unittest.TestLoader().discover(start_dir, top_level_dir=ROOT)
    modules = []

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                name = type(t).__module__
                if name.startswith("unittest.loader"):  # import failure placeholder
                    name = t.id().split("_FailedTest.", 1)[-1]
                if name not in modules:
                    modules.append(name)
    walk(suite)
    return modules


def run_child(module, json_path):
    """Child process: run one module, write outcomes as JSON."""
    suite = unittest.TestLoader().loadTestsFromName(module)
    result = unittest.TextTestRunner(resultclass=RecordingResult, verbosity=1).run(suite)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                   "skipped": len(result.skipped), "outcomes": result.outcomes}, f)
    return 0 if result.wasSuccessful() else 1


def _tree_rss(proc):
    try:
        procs = [proc] + proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return 0
    total = 0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def _kill_tree(proc):
    try:
        procs = proc.children(recursive=True) + [proc]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def run_module(module, timeout_s, min_available_gb):
    """Parent: run one module in a child process; return (report dict, peak RSS bytes, seconds)."""
    fd, json_path = tempfile.mkstemp(suffix=".json", prefix="sva-tests-")
    os.close(fd)
    t0 = time.monotonic()
    print(f"\n--- {module}", flush=True)
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--child", module, "--json", json_path],
                             cwd=ROOT)
    proc = psutil.Process(child.pid)
    peak, killed, low_since = 0, None, None
    while child.poll() is None:
        peak = max(peak, _tree_rss(proc))
        available_gb = psutil.virtual_memory().available / 1e9
        now = time.monotonic()
        low_since = (low_since or now) if available_gb < min_available_gb else None
        if now - t0 > timeout_s:
            killed = f"timed out after {timeout_s:.0f}s"
        elif low_since is not None and now - low_since > LOW_MEMORY_GRACE_S:
            killed = (f"KILLED_LOW_MEMORY: system available RAM below {min_available_gb} GB for "
                      f"{LOW_MEMORY_GRACE_S:.0f}s (module peak RSS {peak / 1e9:.2f} GB)")
        if killed:
            _kill_tree(proc)
            child.wait()
            break
        time.sleep(MONITOR_INTERVAL_S)
    elapsed = time.monotonic() - t0
    try:
        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, ValueError):
        report = None
    finally:
        os.unlink(json_path)
    if report is None:
        why = killed or f"child process exited with code {child.returncode}"
        report = {"tests_run": 0, "failures": 0, "errors": 1, "skipped": 0, "crashed": why,
                  "outcomes": {module: [("fail", why)]}}
    return report, peak, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--module-timeout", type=float, default=DEFAULT_MODULE_TIMEOUT_S)
    ap.add_argument("--min-available-gb", type=float, default=DEFAULT_MIN_AVAILABLE_GB,
                    help="kill a module if available RAM stays below this (0 disables)")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--json", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        sys.exit(run_child(args.child, args.json))

    start_dir = os.path.join(ROOT, "tests", "unit") if args.fast else os.path.join(ROOT, "tests")
    t0 = time.time()
    outcomes = collections.defaultdict(list)
    totals = collections.Counter()
    rows = []
    for module in discover_modules(start_dir):
        report, peak, elapsed = run_module(module, args.module_timeout, args.min_available_gb)
        for cls, items in report["outcomes"].items():
            outcomes[cls].extend(tuple(i) for i in items)
        for key in ("tests_run", "failures", "errors", "skipped"):
            totals[key] += report[key]
        rows.append((module, report, peak, elapsed))

    print("\n=== Modules ===")
    for module, r, peak, elapsed in rows:
        status = r.get("crashed") or ("ok" if r["failures"] + r["errors"] == 0 else "FAILED")
        print(f"{module:45s} {r['tests_run']:4d} run {r['failures'] + r['errors']:3d} failed {r['skipped']:3d} skipped "
              f"{elapsed:6.0f}s  peak {peak / 1e9:.2f} GB  {status}")

    if not args.fast:
        print("\n=== Engine matrix ===")
        for cls, (kind, engine) in ENGINE_CLASSES.items():
            status, reason = engine_status(outcomes.get(cls, []))
            print(f"{kind:4s} {engine:10s} {status:14s} {reason}")
    failed = totals["failures"] + totals["errors"]
    print(f"\nTotal: {totals['tests_run']} tests, {totals['failures']} failures, {totals['errors']} errors, "
          f"{totals['skipped']} skipped in {time.time() - t0:.0f}s")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
