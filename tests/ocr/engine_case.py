"""Shared real-engine test suite. Each tests/ocr/test_<engine>.py subclasses EngineTestBase.

Status semantics (see scripts/run_tests.py):
  PASS           all checks ran and passed
  FAIL           any check failed or errored
  NOT_AVAILABLE  engine could not be loaded on this machine; every test is skipped with a
                 reason starting "NOT_AVAILABLE". Never reported as PASS.
Synthetic fixtures prove the engine functions; they are not accuracy measurements.
"""
import json
import os
import time
import unittest

import cv2
import numpy as np

from core.frame.processing import Preprocessor
from core.ocr.service import build_adapters
from core.ocr.types import EngineStatus, OCRError, OCRErrorCode
from core.status import UNAVAILABLE_STATUSES
from tests.helpers import default_config, no_network

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "ocr")
with open(os.path.join(FIXTURES, "manifest.json"), encoding="utf-8") as _f:
    MANIFEST = {m["id"]: m for m in json.load(_f)["fixtures"]}


def cer(ref: str, hyp: str) -> float:
    ref = " ".join(ref.lower().split())
    hyp = " ".join(hyp.lower().split())
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


_ADAPTER_CACHE = {}


def load_adapter(engine: str, language: str = "en"):
    """Build + initialize once per (engine, language), under a network block."""
    key = (engine, language)
    if key not in _ADAPTER_CACHE:
        cfg = default_config()
        adapter = build_adapters(cfg["ocr"], language)[engine]
        with no_network() as guard:
            adapter.initialize()
        adapter.network_attempts = list(guard.attempts)
        _ADAPTER_CACHE[key] = adapter
    return _ADAPTER_CACHE[key]


class EngineTestBase(unittest.TestCase):
    engine = ""
    #: fixtures this engine must read (id -> max CER)
    must_read = {}
    #: languages other than English to probe
    other_languages = ("hi", "kn")

    @classmethod
    def setUpClass(cls):
        if cls is EngineTestBase:
            raise unittest.SkipTest("base class")
        cls.adapter = load_adapter(cls.engine)
        cls.pre = Preprocessor(default_config()["frame"]["preprocess"])

    def setUp(self):
        if self.adapter.status in UNAVAILABLE_STATUSES:
            self.skipTest(f"NOT_AVAILABLE: {self.adapter.status.value}: {self.adapter.status_detail}")
        # INIT_FAILED and anything else unexpected falls through and fails the tests.

    def fixture(self, fid: str) -> np.ndarray:
        img = cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"]))
        self.assertIsNotNone(img, fid)
        return self.pre.prepare(img).for_engine(self.adapter.input_kind)

    def run_fixture(self, fid: str):
        with no_network():
            return self.adapter.recognize(self.fixture(fid))

    # A. initialization / B. model loading
    def test_a_initialization(self):
        self.assertEqual(self.adapter.status, EngineStatus.READY)
        self.assertTrue(self.adapter.status_detail)

    def test_b_model_loaded_from_local_storage(self):
        self.assertEqual(self.adapter.network_attempts, [], "engine tried to reach the network while loading")
        self.assertGreater(self.adapter.init_time, 0)

    # C. offline inference / D. CPU inference
    def test_c_offline_inference(self):
        res = self.run_fixture(next(iter(self.must_read)))
        self.assertFalse(res.is_empty)

    def test_d_cpu_inference(self):
        self.assertFalse(self.adapter.cfg.get("gpu", False))
        self.assertIn(self.adapter.cfg.get("device", "cpu"), ("cpu",))

    # E. image inference (synthetic)
    def test_e_reads_fixtures(self):
        for fid, max_cer in self.must_read.items():
            with self.subTest(fixture=fid):
                res = self.run_fixture(fid)
                err = cer(MANIFEST[fid]["text"], res.text)
                self.assertLessEqual(err, max_cer, f"{fid}: got {res.text!r} (CER {err:.2f})")

    # F. confidence
    def test_f_confidence(self):
        res = self.run_fixture(next(iter(self.must_read)))
        self.assertGreater(res.confidence, 0.0)
        self.assertLessEqual(res.confidence, 1.0)
        self.assertEqual(res.engine, self.engine)
        self.assertGreater(res.processing_time, 0.0)
        self.assertTrue(res.bounding_boxes)

    def test_f_blank_frame_gives_no_confident_text(self):
        res = self.run_fixture("blank")
        self.assertTrue(res.is_empty or res.confidence < 0.5, f"blank frame read as {res.text!r} ({res.confidence:.2f})")

    # G. error handling
    def test_g_invalid_input(self):
        for bad in (np.zeros((0, 0, 3), np.uint8), "not an image", np.zeros((4, 4, 3, 2), np.uint8)):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(OCRError) as ctx:
                    self.adapter.recognize(bad)
                self.assertEqual(ctx.exception.code, OCRErrorCode.INVALID_INPUT)

    def test_g_inference_exception_is_wrapped(self):
        broken = type(self.adapter).__new__(type(self.adapter))
        broken.__dict__.update(self.adapter.__dict__)
        for attr in ("_reader", "_ocr", "_model", "_pt"):
            if attr in broken.__dict__:
                broken.__dict__[attr] = None  # simulate a model that vanished mid-run
        with self.assertRaises(OCRError) as ctx, self.assertLogs("ocr", level="ERROR"):
            broken.recognize(self.fixture(next(iter(self.must_read))))
        self.assertEqual(ctx.exception.code, OCRErrorCode.INFERENCE_FAILED)

    # H. languages
    def test_h_other_languages_report_clear_status(self):
        acceptable = {EngineStatus.READY, EngineStatus.MODEL_NOT_AVAILABLE, EngineStatus.LANGUAGE_NOT_SUPPORTED}
        for lang in self.other_languages:
            with self.subTest(language=lang):
                a = load_adapter(self.engine, lang)
                self.assertIn(a.status, acceptable, f"{lang}: {a.status.value} {a.status_detail}")
                self.assertEqual(a.network_attempts, [])
                if a.status == EngineStatus.READY:
                    fid = {"hi": "hindi_room", "kn": "kannada_room"}[lang]
                    img = self.pre.prepare(cv2.imread(os.path.join(FIXTURES, MANIFEST[fid]["path"])))
                    res = a.recognize(img.for_engine(a.input_kind))
                    self.assertIn("204", res.text)

    # I. performance (recorded; asserted only against the configured timeout)
    def test_i_latency_within_timeout(self):
        img = self.fixture(next(iter(self.must_read)))
        t0 = time.perf_counter()
        self.adapter.recognize(img)
        self.assertLess(time.perf_counter() - t0, float(self.adapter.cfg["timeout_s"]))
