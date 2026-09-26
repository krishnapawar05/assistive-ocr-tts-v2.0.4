"""OCRService: runs engines according to the configured mode and picks one result.

Modes:
  single_engine  first available engine of [engine] + fallback_order
  fallback       engines in that order; stop as soon as a valid candidate scores >= accept_score
  ensemble       every available engine; results are fused by the scorer

Each engine runs on its own single worker thread so a hung engine can be timed out without
blocking the pipeline; while it is still busy it is skipped (BUSY) instead of piling up work.

With ``serialize_engines`` (default) no engine starts while ANY engine call is still running,
process-wide and across service instances. On an 8 GB machine a timed-out PaddleOCR/EasyOCR
call plus a second engine exhausted memory and crashed the process natively (segfault).
"""
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Callable, Dict, List, Optional

from ..frame.processing import PreparedFrame
from ..languages import normalize_language
from ..text.processor import TextProcessor
from .base import OCRAdapter
from .scoring import OCRScorer
from .types import EngineStatus, OCRDecision, OCRError, OCRErrorCode, OCRResult

logger = logging.getLogger("ocr.service")

# Process-wide registry of submitted engine calls (engine name -> latest Future).
_INFLIGHT: Dict[str, Future] = {}
_INFLIGHT_LOCK = threading.Lock()


def engines_in_flight() -> List[str]:
    with _INFLIGHT_LOCK:
        return [n for n, f in _INFLIGHT.items() if not f.done()]


def build_adapters(ocr_cfg: Dict, language: str) -> Dict[str, OCRAdapter]:
    from .easyocr_adapter import EasyOCRAdapter
    from .paddle import PaddleOCRAdapter
    from .tesseract import TesseractOCRAdapter
    from .trocr import TrOCRAdapter

    engines = ocr_cfg["engines"]
    return {
        "tesseract": TesseractOCRAdapter(engines["tesseract"], language),
        "easyocr": EasyOCRAdapter(engines["easyocr"], language),
        "paddle": PaddleOCRAdapter(engines["paddle"], language),
        "trocr": TrOCRAdapter(engines["trocr"], language, ocr_cfg["regions"]),
    }


class OCRService:
    def __init__(self, ocr_cfg: Dict, text_cfg: Dict,
                 adapters: Optional[Dict[str, OCRAdapter]] = None,
                 adapter_factory: Callable[[Dict, str], Dict[str, OCRAdapter]] = build_adapters):
        self.cfg = ocr_cfg
        self.mode = ocr_cfg["mode"]
        self.language = normalize_language(ocr_cfg["language"])
        self.min_confidence = float(ocr_cfg["min_confidence"])
        self.min_text_len = int(ocr_cfg["min_text_len"])
        self.accept_score = float(ocr_cfg["accept_score"])
        self.min_final_score = float(ocr_cfg["min_final_score"])
        self.processor = TextProcessor(text_cfg, self.min_text_len)
        self.scorer = OCRScorer(ocr_cfg["scoring"], ocr_cfg["text_type"], self.processor, self.language)
        self.adapters = adapters if adapters is not None else adapter_factory(ocr_cfg, self.language)
        self.order: List[str] = []
        for name in [ocr_cfg["engine"]] + list(ocr_cfg["fallback_order"]):
            if name in self.adapters and name not in self.order:
                self.order.append(name)
        self._executors = {n: ThreadPoolExecutor(1, thread_name_prefix=f"ocr-{n}") for n in self.order}
        self.serialize = bool(ocr_cfg["serialize_engines"])
        self._pending: Dict[str, Future] = {}

    # ----- lifecycle -------------------------------------------------------------------------
    def initialize(self) -> Dict[str, str]:
        """Load engines at startup.

        ensemble, or preload="all": every engine in the order.
        otherwise: engines up to and including the first READY one; later fallback engines
        load on first use (saves memory and startup time when the primary is good enough).
        """
        load_all = self.mode == "ensemble" or self.cfg["preload"] == "all"
        for name in self.order:
            status = self.adapters[name].initialize()
            if not load_all and status == EngineStatus.READY:
                break
        if not self.available_engines():
            logger.error("No OCR engine available (%s). OCR is disabled until one is installed.",
                         ", ".join(f"{n}={a.status.value}" for n, a in self.adapters.items()))
        return {n: self.adapters[n].status.value for n in self.order}

    def available_engines(self) -> List[str]:
        return [n for n in self.order if self.adapters[n].is_available]

    def statuses(self) -> Dict[str, Dict]:
        return {n: a.describe() for n, a in self.adapters.items()}

    def shutdown(self) -> None:
        for ex in self._executors.values():
            ex.shutdown(wait=False, cancel_futures=True)

    # ----- inference ---------------------------------------------------------------------------
    def _engines_for_frame(self) -> List[str]:
        """Engines to try for this frame. Unloaded fallback engines are included and loaded
        only when the loop actually reaches them (see _ensure_loaded)."""
        names = []
        for name in self.order:
            adapter = self.adapters[name]
            if self.mode == "single_engine" and adapter.status == EngineStatus.UNINITIALIZED:
                adapter.initialize()
            if adapter.is_available or adapter.status == EngineStatus.UNINITIALIZED:
                names.append(name)
                if self.mode == "single_engine" and adapter.is_available:
                    break
        return names

    def _ensure_loaded(self, name: str) -> bool:
        adapter = self.adapters[name]
        if adapter.status == EngineStatus.UNINITIALIZED:
            logger.info("loading fallback OCR engine %s on first use", name)
            adapter.initialize()
        return adapter.is_available

    def _run(self, name: str, prepared: PreparedFrame) -> OCRResult:
        adapter = self.adapters[name]
        with _INFLIGHT_LOCK:
            pending = self._pending.get(name)
            if pending is not None and not pending.done():
                raise OCRError(OCRErrorCode.BUSY, name, "previous call still running")
            if self.serialize:
                running = [n for n, f in _INFLIGHT.items() if not f.done()]
                if running:
                    raise OCRError(OCRErrorCode.BUSY, name, f"{running[0]} still running")
            fut = self._executors[name].submit(adapter.recognize, prepared.for_engine(adapter.input_kind))
            self._pending[name] = fut
            _INFLIGHT[name] = fut
        timeout = float(adapter.cfg["timeout_s"])
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            raise OCRError(OCRErrorCode.TIMEOUT, name, f"no result within {timeout:.1f}s") from None

    def recognize(self, prepared: PreparedFrame) -> OCRDecision:
        t0 = time.perf_counter()
        decision = OCRDecision(winner=None)
        engines = self._engines_for_frame()
        if not engines:
            decision.reason = "no_engine_available"
            return decision

        results: List[OCRResult] = []
        for name in engines:
            if not self._ensure_loaded(name):
                continue
            decision.engines_run.append(name)
            try:
                res = self._run(name, prepared)
            except OCRError as e:
                decision.errors[name] = e.code.value
                log = logger.warning if e.code in (OCRErrorCode.TIMEOUT, OCRErrorCode.INFERENCE_FAILED) else logger.debug
                log("OCR %s failed: %s", name, e)
                continue
            logger.debug("OCR %s: conf=%.2f len=%d t=%.2fs", name, res.confidence, len(res.text), res.processing_time)
            if res.is_empty:
                continue
            if res.confidence < self.min_confidence:
                logger.debug("OCR %s below min_confidence (%.2f < %.2f)", name, res.confidence, self.min_confidence)
                continue
            results.append(res)
            if self.mode == "fallback":
                best = self._best(self.scorer.score(results))
                if best is not None and best.final_score >= self.accept_score:
                    break
                logger.debug("OCR fallback: best so far %s; trying next engine",
                             f"{best.final_score:.2f}" if best else "none")

        decision.candidates = self.scorer.score(results)
        decision.winner = self._best(decision.candidates)
        decision.processing_time = time.perf_counter() - t0
        if decision.winner is not None:
            decision.reason = "selected"
            logger.debug("OCR winner %s", OCRScorer.explain(decision.winner))
            for c in decision.candidates:
                if c is not decision.winner:
                    logger.debug("OCR rejected %s", OCRScorer.explain(c))
        elif decision.candidates:
            decision.reason = "below_threshold"
            logger.debug("OCR: no candidate passed (best %s)", OCRScorer.explain(decision.candidates[0]))
        elif not decision.engines_run:
            decision.reason = "no_engine_available"  # every lazily loaded engine failed to load
        else:
            decision.reason = "no_text" if len(decision.errors) < len(decision.engines_run) else "all_engines_failed"
        return decision

    def _best(self, candidates):
        for c in candidates:  # sorted best-first
            ok, why = self.processor.is_valid(c.cleaned_text)
            if ok and c.final_score >= self.min_final_score:
                return c
        return None
