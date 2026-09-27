"""OCRService: runs engines according to the configured mode and picks one result.

Modes:
  single_engine  first available engine of [engine] + fallback_order
  fallback       engines in that order; stop as soon as a valid candidate scores >= accept_score
  ensemble       every available engine; results are fused by the scorer

Region-only engines (``needs_text_regions``: TrOCR) never see a whole frame. They run only on the
text regions of the first engine in this frame whose reading of a region is plausible text
(TextProcessor.is_valid); with no such region they are skipped (``decision.skipped``). If one is
reached before any region-finding engine has run it waits until right after the next one; in
ensemble mode they run last; in single_engine mode the first available region-finding engine
runs only to supply regions (its own text is not a candidate). See ADR 0007.

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
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..frame.processing import PreparedFrame
from ..languages import normalize_language
from ..text.processor import TextProcessor
from .base import OCRAdapter
from .scoring import OCRScorer
from .types import BBox, EngineStatus, OCRDecision, OCRError, OCRErrorCode, OCRResult

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
        self.latency_budget_s = float(ocr_cfg.get("latency_budget_s", 0.0))
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

    def _run(self, name: str, prepared: PreparedFrame, regions: Optional[List[BBox]] = None) -> OCRResult:
        adapter = self.adapters[name]
        with _INFLIGHT_LOCK:
            pending = self._pending.get(name)
            if pending is not None and not pending.done():
                raise OCRError(OCRErrorCode.BUSY, name, "previous call still running")
            if self.serialize:
                running = [n for n, f in _INFLIGHT.items() if not f.done()]
                if running:
                    raise OCRError(OCRErrorCode.BUSY, name, f"{running[0]} still running")
            fut = self._executors[name].submit(adapter.recognize, prepared.for_engine(adapter.input_kind), regions)
            self._pending[name] = fut
            _INFLIGHT[name] = fut
        timeout = float(adapter.cfg["timeout_s"])
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeout:
            raise OCRError(OCRErrorCode.TIMEOUT, name, f"no result within {timeout:.1f}s") from None

    def recognize(self, prepared: PreparedFrame) -> OCRDecision:
        t0 = time.perf_counter()
        seq_id = getattr(prepared, "frame_seq_id", 0)
        capture_ts = getattr(prepared, "capture_timestamp", 0.0)
        decision = OCRDecision(winner=None, frame_seq_id=seq_id, capture_timestamp=capture_ts)
        engines = self._engines_for_frame()
        if not engines:
            decision.reason = "no_engine_available"
            return decision

        queue, region_only = self._schedule(engines)
        results: List[OCRResult] = []
        hints: List[Tuple[float, float, float, float]] = []  # plausible text regions, as image fractions
        found_regions = False  # a region-finding engine completed on this frame
        while queue:
            elapsed = time.perf_counter() - t0
            if self.latency_budget_s > 0 and elapsed >= self.latency_budget_s and self.mode == "fallback":
                logger.warning("OCR latency budget reached (%.2fs >= %.2fs); aborting remaining fallback engines: %s",
                               elapsed, self.latency_budget_s, queue)
                for rem in queue:
                    decision.skipped[rem] = "latency_budget_exceeded"
                break

            name = queue.pop(0)
            adapter = self.adapters[name]
            regions = None
            if adapter.needs_text_regions:
                if not hints:
                    later = next((i for i, n in enumerate(queue) if not self.adapters[n].needs_text_regions), None)
                    if later is not None:  # a region-finding engine is still to run: retry right after it
                        queue.insert(later + 1, name)
                        continue
                    decision.skipped[name] = "no_text_region" if found_regions else "no_region_source"
                    logger.debug("OCR %s skipped: %s", name, decision.skipped[name])
                    continue
                if not self._ensure_loaded(name):
                    continue
                h, w = prepared.for_engine(adapter.input_kind).shape[:2]
                regions = [(int(fx * w), int(fy * h), max(1, int(fw * w)), max(1, int(fh * h)))
                           for fx, fy, fw, fh in hints]
            elif not self._ensure_loaded(name):
                continue
            if name not in region_only:
                decision.engines_run.append(name)
            try:
                res = self._run(name, prepared, regions)
            except OCRError as e:
                decision.errors[name] = e.code.value
                log = logger.warning if e.code in (OCRErrorCode.TIMEOUT, OCRErrorCode.INFERENCE_FAILED) else logger.debug
                log("OCR %s failed: %s", name, e)
                continue
            res.frame_seq_id = seq_id
            res.capture_timestamp = capture_ts
            logger.debug("OCR %s: conf=%.2f len=%d t=%.2fs", name, res.confidence, len(res.text), res.processing_time)
            if not adapter.needs_text_regions:
                found_regions = True
                if not hints:
                    hints = self._text_region_hints(res, prepared.for_engine(adapter.input_kind).shape)
                    if hints:
                        decision.region_source = name
            if name in region_only:
                continue  # single_engine: ran only to find regions for the selected engine
            if res.is_empty:
                continue
            if res.confidence < self.min_confidence:
                logger.debug("OCR %s below min_confidence (%.2f < %.2f)", name, res.confidence, self.min_confidence)
                decision.low_confidence[name] = res.confidence
                continue
            results.append(res)
            if self.mode == "fallback":
                best = self._best(self.scorer.score(results))
                if best is not None and best.final_score >= self.accept_score:
                    break
                elapsed = time.perf_counter() - t0
                if self.latency_budget_s > 0 and elapsed >= self.latency_budget_s and queue:
                    logger.warning("OCR latency budget reached after %s (%.2fs >= %.2fs); aborting remaining fallback",
                                   name, elapsed, self.latency_budget_s)
                    for rem in queue:
                        decision.skipped[rem] = "latency_budget_exceeded"
                    queue.clear()
                else:
                    logger.debug("OCR fallback: best so far %s; trying next engine",
                                 f"{best.final_score:.2f}" if best else "none")

        decision.candidates = self.scorer.score(results)
        decision.winner = self._best(decision.candidates)
        decision.processing_time = time.perf_counter() - t0
        if self.latency_budget_s > 0 and decision.processing_time > self.latency_budget_s:
            logger.warning("OCR total duration %.2fs exceeded latency budget %.2fs; invalidating winner",
                           decision.processing_time, self.latency_budget_s)
            decision.winner = None
            decision.reason = "latency_budget_exceeded"
            decision.errors["latency_budget"] = f"exceeded {self.latency_budget_s:.1f}s"
        elif decision.winner is not None:
            decision.reason = "selected"
            logger.debug("OCR winner %s", OCRScorer.explain(decision.winner))
            for c in decision.candidates:
                if c is not decision.winner:
                    logger.debug("OCR rejected %s", OCRScorer.explain(c))
        elif decision.candidates:
            decision.reason = "below_threshold"
            logger.debug("OCR: no candidate passed (best %s)", OCRScorer.explain(decision.candidates[0]))
        elif not decision.engines_run:
            # every lazily loaded engine failed to load, unless a region-only engine was skipped
            # because the region-finding engine saw no text
            decision.reason = "no_text" if "no_text_region" in decision.skipped.values() else "no_engine_available"
        elif decision.low_confidence:
            decision.reason = "below_min_confidence"  # text was read, but no engine was confident enough
        else:
            decision.reason = "no_text" if len(decision.errors) < len(decision.engines_run) else "all_engines_failed"
        return decision

    def _schedule(self, engines: List[str]) -> Tuple[List[str], Set[str]]:
        """Order this frame's engines for region-only engines; return (queue, region_only).
        region_only: engines run just to find text regions (single_engine mode)."""
        if self.mode == "ensemble":
            return ([n for n in engines if not self.adapters[n].needs_text_regions]
                    + [n for n in engines if self.adapters[n].needs_text_regions]), set()
        if self.mode == "single_engine" and engines and self.adapters[engines[0]].needs_text_regions:
            usable = (EngineStatus.READY, EngineStatus.UNINITIALIZED)
            source = next((n for n in self.order if not self.adapters[n].needs_text_regions
                           and self.adapters[n].status in usable), None)
            if source is not None:
                return [source] + engines, {source}
        return list(engines), set()

    def _text_region_hints(self, res: OCRResult, shape) -> List[Tuple[float, float, float, float]]:
        """Regions whose own reading is plausible text (same rule as for spoken text), as
        fractions of the engine's input image so they map onto any other engine's input."""
        h, w = shape[:2]
        hints = []
        for region in res.metadata.get("text_regions", []):
            ok, _ = self.processor.is_valid(self.processor.clean(region["text"]))
            if ok:
                x, y, bw, bh = region["box"]
                hints.append((x / w, y / h, bw / w, bh / h))
        return hints

    def _best(self, candidates):
        for c in candidates:  # sorted best-first
            ok, why = self.processor.is_valid(c.cleaned_text)
            if ok and c.final_score >= self.min_final_score:
                return c
        return None
