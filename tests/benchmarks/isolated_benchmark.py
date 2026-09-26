"""Isolated-process OCR/TTS benchmark with hard time and memory limits.

The parent process never loads a model. It runs one child process per stage (each OCR engine,
each OCR mode, each TTS engine), so EasyOCR, PaddleOCR and TrOCR are never loaded together
except in the ensemble stage, which runs last and only when RAM allows.

Limits
  per OCR/TTS call   60 s  (child records TIMEOUT and exits; a hung native call cannot be
                            cancelled, so the child does not continue with unknown state)
  per child process  6 min (parent kills the process tree -> KILLED_TIMEOUT)
  whole benchmark    25 min (parent kills the current child and skips the rest)
  memory             stage skipped if available RAM is below its minimum (SKIPPED_LOW_MEMORY);
                     child killed if available RAM stays below the floor (KILLED_LOW_MEMORY)

Every sample is printed and appended to a JSONL log as it happens, so a killed run keeps its
data. Statistics are computed only from completed samples.

Usage (repo root):
  .venv/Scripts/python.exe tests/benchmarks/isolated_benchmark.py
  .venv/Scripts/python.exe tests/benchmarks/isolated_benchmark.py --only engine:easyocr
"""
import argparse
import datetime as dt
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time

import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "tests", "benchmarks", "output")
REPORT = os.path.join(ROOT, "docs", "benchmarks", "ocr-tts-baseline.md")

CALL_TIMEOUT_S = 60.0
CHILD_TIMEOUT_S = 6 * 60.0
TOTAL_TIMEOUT_S = 25 * 60.0
REPEATS = 3
FIXTURES = ["room_204", "sentence", "greenboard", "blank"]
TROCR_EXTRA = ["hand_meet"]
MEMORY_FLOOR_GB = 0.25          # kill the child if available RAM stays below this ...
MEMORY_FLOOR_GRACE_S = 3.0      # ... for this long
GB = 1e9

# (stage id, minimum available RAM in GB to start it)
STAGES = [
    ("engine:tesseract", 0.3),
    ("engine:easyocr", 0.6),
    ("engine:paddle", 0.8),
    ("engine:trocr", 0.6),
    ("mode:single_engine", 0.6),
    ("mode:fallback", 0.8),
    ("tts:coqui", 0.6),
    ("tts:espeak", 0.3),
    ("tts:windows", 0.3),
    ("mode:ensemble", 1.5),        # last, and only with headroom
]


def available_gb() -> float:
    return psutil.virtual_memory().available / GB


# =============================================================================================
# Child side (loads models; imports core only here)
# =============================================================================================

def _emit(fh, event: dict) -> None:
    event["t"] = round(time.monotonic(), 3)
    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    fh.flush()


def _call(fn, timeout: float):
    """Run fn in a daemon thread. Returns (status, result, error_text, seconds)."""
    box = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as e:  # recorded, never raised past the benchmark
            box["error"] = f"{type(e).__name__}: {e}"

    t0 = time.perf_counter()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    elapsed = time.perf_counter() - t0
    if th.is_alive():
        return "TIMEOUT", None, f"no result within {timeout:.0f}s", elapsed
    if "error" in box:
        return "FAILED", None, box["error"], elapsed
    return "OK", box.get("result"), "", elapsed


def _progress(stage, fixture, repeat, status, seconds, t_start, extra=""):
    print(f"[{time.monotonic() - t_start:7.1f}s] {stage:20s} fixture={fixture:10s} repeat={repeat} "
          f"status={status:8s} latency={seconds:6.2f}s {extra}", flush=True)


def child_main(stage: str, log_path: str) -> int:
    sys.path.insert(0, ROOT)
    from core.offline import apply_offline_env
    apply_offline_env(True)

    import cv2

    from core.config import DEFAULT_CONFIG
    from tests.ocr.engine_case import MANIFEST, cer

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    kind, name = stage.split(":", 1)
    t_start = time.monotonic()
    proc = psutil.Process()
    fh = open(log_path, "a", encoding="utf-8")
    _emit(fh, {"event": "start", "stage": stage, "pid": os.getpid(), "available_gb": round(available_gb(), 2)})

    def image(fid):
        return cv2.imread(os.path.join(ROOT, "tests", "fixtures", "ocr", MANIFEST[fid]["path"]))

    def abort(reason):
        _emit(fh, {"event": "abort", "reason": reason, "rss_mb": round(proc.memory_info().rss / 1e6, 1)})
        fh.close()
        os._exit(3)  # a timed-out native call may still be running; do not continue

    def finish():
        _emit(fh, {"event": "end", "rss_mb": round(proc.memory_info().rss / 1e6, 1)})
        fh.close()
        return 0

    # ----- OCR engine alone ------------------------------------------------------------------
    if kind == "engine":
        from core.frame.processing import Preprocessor
        from core.ocr.service import build_adapters
        pre = Preprocessor(cfg["frame"]["preprocess"])
        adapter = build_adapters(cfg["ocr"], "en")[name]
        status, _, err, load_s = _call(adapter.initialize, CHILD_TIMEOUT_S)
        _emit(fh, {"event": "loaded", "status": adapter.status.value if status == "OK" else status,
                   "detail": adapter.status_detail or err, "load_s": round(load_s, 2),
                   "rss_mb": round(proc.memory_info().rss / 1e6, 1)})
        print(f"[{time.monotonic() - t_start:7.1f}s] {stage:20s} loaded status={adapter.status.value} "
              f"load={load_s:.1f}s", flush=True)
        if not adapter.is_available:
            return finish()
        fixtures = FIXTURES + (TROCR_EXTRA if name == "trocr" else [])
        prepared = {fid: pre.prepare(image(fid)).for_engine(adapter.input_kind) for fid in fixtures}
        warm = "hand_meet" if name == "trocr" else "room_204"
        st, _, err, sec = _call(lambda: adapter.recognize(prepared[warm]), CALL_TIMEOUT_S)
        _emit(fh, {"event": "warmup", "status": st, "seconds": round(sec, 3), "error": err})
        _progress(stage, warm, "warm", st, sec, t_start, "(not counted)")
        if st == "TIMEOUT":
            abort("warm-up timed out")
        for fid in fixtures:
            for rep in range(1, REPEATS + 1):
                st, res, err, sec = _call(lambda: adapter.recognize(prepared[fid]), CALL_TIMEOUT_S)
                text = res.text if res else ""
                ev = {"event": "sample", "fixture": fid, "repeat": rep, "status": st, "seconds": round(sec, 3),
                      "text": text[:80], "confidence": round(res.confidence, 3) if res else None,
                      "cer": round(cer(MANIFEST[fid]["text"], text), 3) if st == "OK" else None, "error": err}
                _emit(fh, ev)
                _progress(stage, fid, rep, st, sec, t_start, f"text={text[:30]!r}")
                if st == "TIMEOUT":
                    abort(f"call timed out on {fid}")
        return finish()

    # ----- OCR mode (what the pipeline does per frame, before duplicate filtering/TTS) ------------
    if kind == "mode":
        from core.frame.processing import Preprocessor, QualityAssessor
        from core.ocr.service import OCRService
        cfg["ocr"]["mode"] = name
        pre = Preprocessor(cfg["frame"]["preprocess"])
        qa = QualityAssessor(cfg["frame"]["quality"])
        svc = OCRService(cfg["ocr"], cfg["text"])
        status, statuses, err, load_s = _call(svc.initialize, CHILD_TIMEOUT_S)
        _emit(fh, {"event": "loaded", "status": "OK" if status == "OK" else status, "detail": statuses or err,
                   "load_s": round(load_s, 2), "rss_mb": round(proc.memory_info().rss / 1e6, 1)})
        print(f"[{time.monotonic() - t_start:7.1f}s] {stage:20s} loaded {statuses} load={load_s:.1f}s", flush=True)
        if status != "OK":
            abort(f"initialize: {status} {err}")
        frames = {fid: image(fid) for fid in FIXTURES}

        def frame_step(frame):
            report = qa.assess(frame)
            if not report.usable:
                return {"outcome": "unusable_frame", "reasons": report.reasons, "text": "", "engines_run": []}
            d = svc.recognize(pre.prepare(frame))
            return {"outcome": d.reason, "text": d.text, "engines_run": d.engines_run, "errors": d.errors}

        st, _, err, sec = _call(lambda: frame_step(frames["room_204"]), CALL_TIMEOUT_S)
        _emit(fh, {"event": "warmup", "status": st, "seconds": round(sec, 3), "error": err})
        _progress(stage, "room_204", "warm", st, sec, t_start, "(not counted)")
        if st == "TIMEOUT":
            abort("warm-up timed out")
        for fid in FIXTURES:
            for rep in range(1, REPEATS + 1):
                st, res, err, sec = _call(lambda: frame_step(frames[fid]), CALL_TIMEOUT_S)
                res = res or {}
                if st == "OK" and res.get("errors"):
                    st = "FAILED" if res["outcome"] == "all_engines_failed" else st
                ev = {"event": "sample", "fixture": fid, "repeat": rep, "status": st, "seconds": round(sec, 3),
                      "outcome": res.get("outcome"), "engines_run": res.get("engines_run"),
                      "engine_errors": res.get("errors"), "text": res.get("text", "")[:80],
                      "cer": round(cer(MANIFEST[fid]["text"], res.get("text", "")), 3) if st == "OK" else None,
                      "error": err}
                _emit(fh, ev)
                _progress(stage, fid, rep, st, sec, t_start,
                          f"outcome={res.get('outcome')} engines={res.get('engines_run')}")
                if st == "TIMEOUT":
                    abort(f"call timed out on {fid}")
        _emit(fh, {"event": "engines_loaded_at_end",
                   "engines": {n: a.status.value for n, a in svc.adapters.items()}})
        return finish()

    # ----- TTS (no repeated audible playback) -------------------------------------------------------
    if kind == "tts":
        from core.tts.service import build_tts_adapters
        cfg["tts"]["volume"] = 0.0
        adapter = build_tts_adapters(cfg["tts"])[name]
        status, _, err, load_s = _call(adapter.initialize, CHILD_TIMEOUT_S)
        _emit(fh, {"event": "loaded", "status": adapter.status.value if status == "OK" else status,
                   "detail": adapter.status_detail or err, "load_s": round(load_s, 2),
                   "rss_mb": round(proc.memory_info().rss / 1e6, 1)})
        print(f"[{time.monotonic() - t_start:7.1f}s] {stage:20s} loaded status={adapter.status.value} "
              f"load={load_s:.1f}s", flush=True)
        if not adapter.is_available():
            return finish()
        phrase = "Room 204 is on your left"
        if name == "coqui":  # synthesis only, never played
            st, _, err, sec = _call(lambda: adapter.synthesize(phrase), CALL_TIMEOUT_S)
            _emit(fh, {"event": "warmup", "status": st, "seconds": round(sec, 3), "error": err})
            _progress(stage, "phrase", "warm", st, sec, t_start, "(not counted)")
            if st == "TIMEOUT":
                abort("warm-up timed out")
            for rep in range(1, 4):
                st, wav, err, sec = _call(lambda: adapter.synthesize(phrase), CALL_TIMEOUT_S)
                audio_s = round(len(wav) / adapter.sample_rate, 3) if wav is not None else None
                _emit(fh, {"event": "sample", "fixture": "synthesis", "repeat": rep, "status": st,
                           "seconds": round(sec, 3), "audio_s": audio_s, "error": err})
                _progress(stage, "synthesis", rep, st, sec, t_start, f"audio={audio_s}s")
                if st == "TIMEOUT":
                    abort("synthesis timed out")
        else:  # one silent (volume 0) utterance: process start + synthesis + silent playback
            st, _, err, sec = _call(lambda: adapter.speak(phrase), CALL_TIMEOUT_S)
            _emit(fh, {"event": "sample", "fixture": "speak_volume0", "repeat": 1, "status": st,
                       "seconds": round(sec, 3), "error": err})
            _progress(stage, "speak_vol0", 1, st, sec, t_start)
            if st == "TIMEOUT":
                abort("speak timed out")
        return finish()

    raise SystemExit(f"unknown stage {stage}")


# =============================================================================================
# Parent side (no model imports)
# =============================================================================================

def kill_tree(proc: psutil.Process) -> None:
    try:
        procs = proc.children(recursive=True) + [proc]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def run_child(stage: str, deadline_s: float, log_path: str, run_log) -> dict:
    """Run one stage; monitor RSS/CPU/system RAM; enforce deadline and memory floor."""
    cmd = [sys.executable, os.path.abspath(__file__), "--child", stage, "--log", log_path]
    t0 = time.monotonic()
    popen = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace")
    root = psutil.Process(popen.pid)

    def pump():
        for line in popen.stdout:
            if line.startswith("[") and "s]" in line[:12]:
                print(line, end="", flush=True)  # progress lines
            run_log.write(line)
            run_log.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    peak_rss, cpu_samples, min_avail = 0.0, [], available_gb()
    below_since = None
    result = "COMPLETED"
    primed = set()
    while popen.poll() is None:
        try:
            tree = [root] + root.children(recursive=True)
            rss = sum(p.memory_info().rss for p in tree) / 1e6
            cpu = 0.0
            for p in tree:
                if p.pid not in primed:
                    p.cpu_percent(None)
                    primed.add(p.pid)
                else:
                    cpu += p.cpu_percent(None)
            peak_rss = max(peak_rss, rss)
            cpu_samples.append(cpu)
        except psutil.NoSuchProcess:
            pass
        avail = available_gb()
        min_avail = min(min_avail, avail)
        if avail < MEMORY_FLOOR_GB:
            below_since = below_since or time.monotonic()
            if time.monotonic() - below_since >= MEMORY_FLOOR_GRACE_S:
                result = "KILLED_LOW_MEMORY"
                print(f"!! {stage}: available RAM {avail:.2f} GB < {MEMORY_FLOOR_GB} GB -> killing", flush=True)
                kill_tree(root)
                break
        else:
            below_since = None
        if time.monotonic() - t0 > deadline_s:
            result = "KILLED_TIMEOUT"
            print(f"!! {stage}: exceeded {deadline_s:.0f}s -> killing", flush=True)
            kill_tree(root)
            break
        time.sleep(0.5)
    popen.wait(timeout=30)
    reader.join(timeout=5)
    if result == "COMPLETED" and popen.returncode not in (0,):
        result = "ABORTED" if popen.returncode == 3 else f"CRASHED(exit {popen.returncode})"
    return {"result": result, "wall_s": round(time.monotonic() - t0, 1), "peak_rss_mb": round(peak_rss, 1),
            "cpu_percent_median": round(statistics.median(cpu_samples), 1) if cpu_samples else None,
            "min_available_gb": round(min_avail, 2), "exit_code": popen.returncode}


def read_events(log_path: str, stage: str) -> list:
    events, current = [], None
    if not os.path.exists(log_path):
        return events
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "start":
                current = ev.get("stage")
            if current == stage:
                events.append(ev)
    return events


def summarize(stage: str, events: list, child: dict) -> dict:
    loaded = next((e for e in events if e["event"] == "loaded"), None)
    samples = [e for e in events if e["event"] == "sample"]
    ok = [e["seconds"] for e in samples if e["status"] == "OK"]
    s = {
        "stage": stage,
        "result": child.get("result"),
        "load_status": (loaded or {}).get("status"),
        "load_detail": (loaded or {}).get("detail"),
        "load_s": (loaded or {}).get("load_s"),
        "completed": len(ok),
        "failed": sum(1 for e in samples if e["status"] == "FAILED"),
        "timed_out": sum(1 for e in samples if e["status"] == "TIMEOUT"),
        "samples": samples,
        "warmup": next((e for e in events if e["event"] == "warmup"), None),
        "abort": next((e.get("reason") for e in events if e["event"] == "abort"), None),
        "engines_loaded_at_end": next((e["engines"] for e in events if e["event"] == "engines_loaded_at_end"), None),
        **{k: child.get(k) for k in ("wall_s", "peak_rss_mb", "cpu_percent_median", "min_available_gb",
                                     "available_gb_at_start", "exit_code")},
    }
    if ok:  # statistics only from completed samples
        srt = sorted(ok)
        s["latency"] = {"n": len(srt), "median": round(statistics.median(srt), 3),
                        "p95": round(srt[min(len(srt) - 1, round(0.95 * (len(srt) - 1)))], 3),
                        "min": round(srt[0], 3), "max": round(srt[-1], 3)}
    return s


def classify(s: dict) -> str:
    """One word per stage for the summary table."""
    if s["result"].startswith("SKIPPED"):
        return s["result"]
    if s["load_status"] in ("NOT_AVAILABLE", "MODEL_NOT_AVAILABLE", "LANGUAGE_NOT_SUPPORTED", "DISABLED"):
        return "NOT_AVAILABLE"
    if s["result"] == "KILLED_TIMEOUT" or s["timed_out"]:
        return "TIMED_OUT"
    if s["result"] == "KILLED_LOW_MEMORY":
        return "KILLED_LOW_MEMORY"
    if s["result"] != "COMPLETED" or s["load_status"] in ("INIT_FAILED", "TIMEOUT", "FAILED") or s["failed"]:
        return "FAILED"
    return "MEASURED"


def write_report(run: dict) -> None:
    L = []
    env = run["environment"]

    def fmt(v, unit=""):
        return "—" if v is None else f"{v}{unit}"

    L += ["# OCR → TTS benchmark (Milestone A)", "",
          f"**Run:** {run['started']} → {run['finished']} (wall time {run['wall_s']:.0f} s). "
          f"Total limit {TOTAL_TIMEOUT_S / 60:.0f} min; outcome: **{run['outcome']}**.", "",
          "> These are measurements of **synthetic fixtures on a memory-constrained development laptop**. "
          "They validate that the stages work and bound their cost. They are not accuracy results, not "
          "Jetson numbers, and not evidence of production readiness.", "",
          "Status legend: **MEASURED** (ran, statistics from completed samples only) · **NOT_AVAILABLE** "
          "(engine/runtime/model missing) · **FAILED** · **TIMED_OUT** · **KILLED_LOW_MEMORY** · "
          "**SKIPPED_LOW_MEMORY** / **SKIPPED_TOTAL_TIMEOUT** (not started).", "",
          "## 1. Environment", "",
          f"- OS: {env['platform']}", f"- Python: {env['python']}",
          f"- CPU: {env['processor']} — {env['physical_cpus']} cores / {env['logical_cpus']} threads, "
          f"max clock {env['cpu_max_mhz']} MHz", "- GPU/NPU: none used (CPU inference only)",
          f"- RAM: {env['ram_total_gb']} GB total", "",
          "## 2. Hardware/resource constraints", "",
          f"- Available RAM at benchmark start: **{env['available_gb_start']} GB** "
          f"({env['ram_used_percent']}% in use by other applications before the benchmark started).",
          f"- Stage minimum available RAM before start: " + ", ".join(f"{s} ≥ {m} GB" for s, m in STAGES) + ".",
          f"- Runtime memory floor: a child is killed if available RAM stays below {MEMORY_FLOOR_GB} GB for "
          f"{MEMORY_FLOOR_GRACE_S:.0f} s.", ""]

    L += ["## 3. OCR engine results (each engine alone, in its own process)", "",
          "| Engine | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % (1 core=100) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in run["stages"]:
        if not s["stage"].startswith("engine:"):
            continue
        lat = s.get("latency") or {}
        L.append(f"| {s['stage'][7:]} | {classify(s)} | {fmt(s['load_s'])} | {s['completed']} | {s['failed']} | "
                 f"{s['timed_out']} | {fmt(lat.get('median'))} | {fmt(lat.get('p95'))} | {fmt(lat.get('min'))} | "
                 f"{fmt(lat.get('max'))} | {fmt(s['peak_rss_mb'])} | {fmt(s['cpu_percent_median'])} |")
    L += ["", "Per-fixture reads (median latency, text, character error rate vs. the rendered text):", ""]
    for s in run["stages"]:
        if s["stage"].startswith("engine:") and s["samples"]:
            L.append(f"- **{s['stage'][7:]}**: " + "; ".join(
                f"{fid} {statistics.median([x['seconds'] for x in s['samples'] if x['fixture'] == fid and x['status'] == 'OK'] or [0]):.2f}s "
                f"`{next((x['text'] for x in s['samples'] if x['fixture'] == fid), '')[:28]}` "
                f"(CER {next((x['cer'] for x in s['samples'] if x['fixture'] == fid), '—')})"
                for fid in dict.fromkeys(x["fixture"] for x in s["samples"])))
        elif s["stage"].startswith("engine:") and s["load_detail"]:
            L.append(f"- **{s['stage'][7:]}**: {classify(s)} — {str(s['load_detail'])[:160]}")

    L += ["", "## 4. OCR mode results (quality gate + preprocessing + OCRService, per frame)", "",
          "| Mode | Status | Load s | Done | Failed | Timed out | Median s | p95 s | Min s | Max s | Peak RSS MB | CPU % | Engines loaded at end |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in run["stages"]:
        if not s["stage"].startswith("mode:"):
            continue
        lat = s.get("latency") or {}
        loaded = s.get("engines_loaded_at_end") or {}
        L.append(f"| {s['stage'][5:]} | {classify(s)} | {fmt(s['load_s'])} | {s['completed']} | {s['failed']} | "
                 f"{s['timed_out']} | {fmt(lat.get('median'))} | {fmt(lat.get('p95'))} | {fmt(lat.get('min'))} | "
                 f"{fmt(lat.get('max'))} | {fmt(s['peak_rss_mb'])} | {fmt(s['cpu_percent_median'])} | "
                 f"{', '.join(n for n, st in loaded.items() if st == 'READY') or '—'} |")
    L += ["", "Per-fixture outcome (engines run → text):", ""]
    for s in run["stages"]:
        if s["stage"].startswith("mode:") and s["samples"]:
            L.append(f"- **{s['stage'][5:]}**: " + "; ".join(
                f"{fid}: {x.get('outcome')} {'+'.join(x.get('engines_run') or []) or '(gated)'} → `{x.get('text', '')[:24]}`"
                for fid, x in {x['fixture']: x for x in s["samples"]}.items()))
        elif s["stage"].startswith("mode:"):
            L.append(f"- **{s['stage'][5:]}**: {classify(s)}" + (f" — {s['skip_reason']}" if s.get("skip_reason") else ""))

    L += ["", "## 5. TTS results (no repeated audible playback)", "",
          "| Engine | Status | Load s | Measured | Done | Median s | Min s | Max s | Peak RSS MB | Notes |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in run["stages"]:
        if not s["stage"].startswith("tts:"):
            continue
        lat = s.get("latency") or {}
        name = s["stage"][4:]
        what = "synthesis only ×3" if name == "coqui" else "one utterance at volume 0 (process start + synthesis + silent playback)"
        audio = [x.get("audio_s") for x in s["samples"] if x.get("audio_s")]
        note = f"audio length {audio[0]} s, real-time factor {lat['median'] / audio[0]:.2f}" if audio and lat else (
            str(s["load_detail"])[:80] if classify(s) != "MEASURED" else "")
        L.append(f"| {name} | {classify(s)} | {fmt(s['load_s'])} | {what} | {s['completed']} | {fmt(lat.get('median'))} | "
                 f"{fmt(lat.get('min'))} | {fmt(lat.get('max'))} | {fmt(s['peak_rss_mb'])} | {note} |")

    L += ["", "## 6. Timeout / failure / skip results", "",
          "| Stage | Child result | Exit | Wall s | Abort reason / skip reason |", "|---|---|---|---|---|"]
    for s in run["stages"]:
        L.append(f"| {s['stage']} | {s['result']} | {fmt(s.get('exit_code'))} | {fmt(s.get('wall_s'))} | "
                 f"{s.get('abort') or s.get('skip_reason') or ''} |")

    L += ["", "## 7. Memory measurements", "",
          "| Stage | Available RAM before (GB) | Lowest available during (GB) | Peak RSS of child (MB) |",
          "|---|---|---|---|"]
    for s in run["stages"]:
        L.append(f"| {s['stage']} | {fmt(s.get('available_gb_at_start'))} | {fmt(s.get('min_available_gb'))} | "
                 f"{fmt(s.get('peak_rss_mb'))} |")

    L += ["", "## 8. End-to-end observations", ""] + [f"- {o}" for o in run["observations"]]
    L += ["", "## 9. Known limitations", "",
          "- Synthetic, rendered fixtures (4 images + 1 handwriting image): they verify function and bound latency; "
          "they say nothing about accuracy on real classroom captures.",
          "- Measured on a Windows laptop with little free RAM; other applications affect latency. No Jetson "
          "numbers. No camera capture timing (the camera is not opened by the benchmark).",
          "- 3 repeats × 4 fixtures = 12 samples per stage, so p95 is effectively the slowest sample.",
          "- Mode latency covers quality gate + preprocessing + OCR; duplicate filtering and speech are "
          "measured separately (text processing and scoring are sub-millisecond and not timed here).",
          "- Windows speech and eSpeak are timed once each including process start and silent playback; they "
          "are not synthesis-only numbers.",
          "- CPU % is the child's summed per-process CPU (100 = one full logical core), sampled every 0.5 s.", ""]
    L += ["## 10. Exact benchmark configuration", "",
          f"- Script: `tests/benchmarks/isolated_benchmark.py` (commit {run['git_commit']})",
          f"- Config: `core.config.DEFAULT_CONFIG` (not the local `config.json`); TTS volume forced to 0.",
          f"- Fixtures: {', '.join(FIXTURES)} (+ {', '.join(TROCR_EXTRA)} for TrOCR); {REPEATS} timed repeats; "
          "1 untimed warm-up call per stage after loading.",
          f"- Timeouts: {CALL_TIMEOUT_S:.0f} s per OCR/TTS call, {CHILD_TIMEOUT_S / 60:.0f} min per child process, "
          f"{TOTAL_TIMEOUT_S / 60:.0f} min total.",
          "- Stage order: " + " → ".join(s for s, _ in STAGES) + " (ensemble last).",
          "- Offline: HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True.",
          f"- Raw data: `tests/benchmarks/output/{run['label']}.json` and `.jsonl` (not committed).", "",
          "## 11. Timestamp", "", f"{run['started']} (local time).", ""]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))


def observations(stages: list) -> list:
    obs = []
    by = {s["stage"]: s for s in stages}
    eng = {k[7:]: v for k, v in by.items() if k.startswith("engine:") and v.get("latency")}
    if eng:
        fastest = min(eng, key=lambda k: eng[k]["latency"]["median"])
        slowest = max(eng, key=lambda k: eng[k]["latency"]["median"])
        obs.append(f"Fastest measured OCR engine: {fastest} ({eng[fastest]['latency']['median']} s median); slowest: "
                   f"{slowest} ({eng[slowest]['latency']['median']} s median).")
    for k, v in by.items():
        if classify(v) not in ("MEASURED", "NOT_AVAILABLE"):
            obs.append(f"{k}: {classify(v)} ({v.get('abort') or v.get('skip_reason') or v['result']}).")
    fb = by.get("mode:fallback")
    if fb and fb.get("engines_loaded_at_end"):
        loaded = [n for n, st in fb["engines_loaded_at_end"].items() if st == "READY"]
        obs.append(f"Fallback mode loaded only {', '.join(loaded)} for these fixtures (lazy loading of fallback engines).")
    for k in ("mode:single_engine", "mode:fallback", "mode:ensemble"):
        s = by.get(k)
        if s and s["samples"]:
            blank = [x for x in s["samples"] if x["fixture"] == "blank"]
            if blank and all(x.get("outcome") == "unusable_frame" for x in blank):
                obs.append(f"{k[5:]}: the blank frame was rejected by the quality gate before OCR "
                           f"({statistics.median([x['seconds'] for x in blank]) * 1000:.1f} ms).")
    return obs


def parent_main(args) -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    label = args.label or "isolated-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    jsonl = os.path.join(OUT_DIR, f"{label}.jsonl")
    child_log = open(os.path.join(OUT_DIR, f"{label}.child.log"), "w", encoding="utf-8")
    vm = psutil.virtual_memory()
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip()
    except OSError:
        commit = "unknown"
    freq = psutil.cpu_freq()
    run = {"label": label, "started": dt.datetime.now().isoformat(timespec="seconds"), "git_commit": commit,
           "environment": {"platform": platform.platform(), "python": platform.python_version(),
                           "processor": platform.processor(), "physical_cpus": psutil.cpu_count(False),
                           "logical_cpus": psutil.cpu_count(True), "cpu_max_mhz": int(freq.max) if freq else None,
                           "ram_total_gb": round(vm.total / GB, 1), "available_gb_start": round(vm.available / GB, 2),
                           "ram_used_percent": vm.percent},
           "stages": []}
    stages = [(s, m) for s, m in STAGES if not args.only or s in args.only]
    t_run = time.monotonic()
    print(f"benchmark {label}: {len(stages)} stages, total limit {TOTAL_TIMEOUT_S / 60:.0f} min, "
          f"available RAM {available_gb():.2f} GB", flush=True)
    for stage, min_gb in stages:
        remaining = TOTAL_TIMEOUT_S - (time.monotonic() - t_run)
        avail = available_gb()
        base = {"stage": stage, "available_gb_at_start": round(avail, 2)}
        if remaining <= 5:
            print(f"-- {stage}: SKIPPED_TOTAL_TIMEOUT", flush=True)
            run["stages"].append(summarize(stage, [], {"result": "SKIPPED_TOTAL_TIMEOUT", **base})
                                 | {"skip_reason": "total benchmark time limit reached"})
            continue
        if avail < min_gb:
            reason = f"available RAM {avail:.2f} GB < required {min_gb} GB"
            print(f"-- {stage}: SKIPPED_LOW_MEMORY ({reason})", flush=True)
            run["stages"].append(summarize(stage, [], {"result": "SKIPPED_LOW_MEMORY", **base})
                                 | {"skip_reason": reason})
            continue
        print(f"== {stage}: starting (available RAM {avail:.2f} GB, deadline {min(CHILD_TIMEOUT_S, remaining):.0f}s)",
              flush=True)
        child = run_child(stage, min(CHILD_TIMEOUT_S, remaining), jsonl, child_log)
        child.update(base)
        if child["result"] == "KILLED_TIMEOUT" and remaining < CHILD_TIMEOUT_S:
            child["result"] = "KILLED_TOTAL_TIMEOUT"
        s = summarize(stage, read_events(jsonl, stage), child)
        run["stages"].append(s)
        lat = s.get("latency")
        print(f"== {stage}: {classify(s)} ({child['result']}) wall={child['wall_s']}s peakRSS={child['peak_rss_mb']}MB "
              f"median={lat['median'] if lat else '—'}s done={s['completed']} failed={s['failed']} "
              f"timeouts={s['timed_out']}", flush=True)
    run["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    run["wall_s"] = time.monotonic() - t_run
    killed_total = any(s["result"] in ("KILLED_TOTAL_TIMEOUT", "SKIPPED_TOTAL_TIMEOUT") for s in run["stages"])
    run["outcome"] = "STOPPED AT 25-MINUTE LIMIT (partial results)" if killed_total else "completed within limits"
    run["observations"] = observations(run["stages"])
    with open(os.path.join(OUT_DIR, f"{label}.json"), "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2, ensure_ascii=False)
    if not args.no_report:
        write_report(run)
        print(f"report: {REPORT}", flush=True)
    print(f"done in {run['wall_s']:.0f}s: {run['outcome']}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child")
    ap.add_argument("--log")
    ap.add_argument("--label")
    ap.add_argument("--only", nargs="*", help="run only these stages, e.g. engine:easyocr mode:fallback")
    ap.add_argument("--no-report", action="store_true", help="do not overwrite docs/benchmarks/ocr-tts-baseline.md")
    args = ap.parse_args()
    if args.child:
        sys.exit(child_main(args.child, args.log))
    sys.exit(parent_main(args))


if __name__ == "__main__":
    main()
