"""
setup_manager.py — the in-app setup wizard's engine side.

WHAT:  Runs the three first-time setup jobs in the background and reports
       their live progress, so the owner never has to open PowerShell:
         1. AI engine (Ollama): detect it, start it, or download + launch
            its official installer if it's missing.
         2. AI models: download every model the app needs, with progress
            (bytes done / total) per model.
         3. Benchmark: run benchmark.py on a folder the owner picks, and
            report where the result file was saved.

WHY:   The owner asked for a normal Windows app (.exe) — everything must be
       button-driven inside the app. These jobs can take minutes to hours, so
       each runs on its own background thread while the window stays
       responsive and polls status.

WHEN:  - status() is polled by the window every ~1.5 s via GET /setup/status.
       - start_*() functions are called when the owner presses a wizard
         button (POST /setup/... in server.py).

CONNECTED TO:
       - server.py         → exposes these functions as /setup/* endpoints
       - ollama_client.py  → checks whether Ollama is running / models present
       - benchmark.py      → run_benchmark() does the measuring
       - config.py         → model names, data folder
       - app/src/SetupWizard.jsx → the buttons and progress bars

SAFETY: Only one job of each kind can run at a time (a second click is
       ignored while the first is running). All state lives in memory; if the
       app is closed mid-download, Ollama resumes partial downloads next time.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from . import benchmark, config, ollama_client

# Official Ollama Windows installer. ollama.com redirects to the current
# release file; httpx follows the redirect.
OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"

# Where the Ollama Windows installer puts ollama.exe for the current user.
_OLLAMA_DEFAULT_EXE = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
)

# Every model the wizard downloads, in download order. Required ones first,
# then the extra candidates used only for the benchmark comparison.
# dict.fromkeys keeps order and drops duplicates (FAST and DEEP are the same
# model since the owner's benchmark).
REQUIRED_MODELS = list(dict.fromkeys([config.FAST_MODEL, config.EMBED_MODEL, config.DEEP_MODEL]))
WIZARD_MODELS = REQUIRED_MODELS + [m for m in config.BENCHMARK_MODELS if m not in REQUIRED_MODELS]

# One lock guards all shared state below (threads write, the server reads).
_lock = threading.Lock()

_ollama_job = {"state": "idle", "message": "", "downloaded": 0, "total": 0}
_models_job = {"state": "idle", "message": "", "current": None, "progress": {}}
_bench_job = {"state": "idle", "message": "", "report": None, "folder": None, "started_at": None}
_bench_cancel = threading.Event()   # set by cancel_benchmark(), read by the worker


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _update(job: dict, **changes) -> None:
    """Thread-safe update of one job's state dict."""
    with _lock:
        job.update(changes)


def find_ollama_exe() -> str | None:
    """
    Locate ollama.exe: first on PATH, then the installer's default location.
    RETURNS: full path, or None if Ollama isn't installed.
    """
    on_path = shutil.which("ollama")
    if on_path:
        return on_path
    if _OLLAMA_DEFAULT_EXE.exists():
        return str(_OLLAMA_DEFAULT_EXE)
    return None


def _no_window_flags() -> int:
    """On Windows, stop child processes from flashing a black console window."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# --------------------------------------------------------------------------- #
# Status (polled by the window)
# --------------------------------------------------------------------------- #

def status() -> dict:
    """
    Snapshot of everything the wizard displays.

    RETURNS: {
      ollama:    {installed, running, job: {...}},
      models:    {list: [{name, required, present, completed, total}], job},
      benchmark: {job: {...}},
      setup_complete: True when Ollama runs and all REQUIRED models exist
    }
    """
    running = ollama_client.is_running()
    try:
        installed_models = ollama_client.installed_models() if running else []
    except ollama_client.OllamaError:
        installed_models = []

    with _lock:
        progress = dict(_models_job["progress"])
        models = [
            {
                "name": m,
                "required": m in REQUIRED_MODELS,
                "present": ollama_client.has_model(m, installed_models),
                "completed": progress.get(m, {}).get("completed", 0),
                "total": progress.get(m, {}).get("total", 0),
            }
            for m in WIZARD_MODELS
        ]
        snapshot = {
            "ollama": {
                "installed": bool(find_ollama_exe()) or running,
                "running": running,
                "job": dict(_ollama_job),
            },
            "models": {"list": models, "job": {k: v for k, v in _models_job.items() if k != "progress"}},
            "benchmark": {"job": dict(_bench_job)},
            "reports_dir": str(config.REPORTS_DIR),
        }
    snapshot["setup_complete"] = running and all(m["present"] for m in models if m["required"])
    return snapshot


# --------------------------------------------------------------------------- #
# Job 1: Ollama
# --------------------------------------------------------------------------- #

def start_ollama() -> dict:
    """
    Start the Ollama service if it's installed but not running.

    HOW:  Launches `ollama serve` as a detached, hidden background process,
          then waits up to 30 s for it to answer. Detached means it keeps
          running after the Knowledge Bank closes — Ollama is designed to run
          in the background, and restarting it every launch would be slow.
    """
    if ollama_client.is_running():
        return {"ok": True, "message": "Ollama is already running."}
    exe = find_ollama_exe()
    if not exe:
        return {"ok": False, "message": "Ollama is not installed."}
    flags = _no_window_flags()
    if sys.platform == "win32":
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([exe, "serve"], creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if ollama_client.is_running():
            return {"ok": True, "message": "Ollama started."}
        time.sleep(1)
    return {"ok": False, "message": "Ollama did not respond within 30 seconds."}


def _install_ollama_worker() -> None:
    """
    Background thread: download the official Ollama installer with progress,
    then open it for the owner to click through (it's Ollama's own standard
    installer — we don't modify it). Afterwards we keep checking until Ollama
    answers, then mark the job done.
    """
    target = config.DATA_DIR / "downloads" / "OllamaSetup.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _update(_ollama_job, state="downloading", message="Downloading the AI engine installer…",
                downloaded=0, total=0)
        with httpx.stream("GET", OLLAMA_INSTALLER_URL, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(target, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    _update(_ollama_job, downloaded=done, total=total)

        _update(_ollama_job, state="installing",
                message="Ollama's installer is open — click Install, then come back here.")
        if sys.platform == "win32":
            os.startfile(str(target))  # opens the installer like a double-click
        else:
            raise RuntimeError("Automatic Ollama install is only available on Windows.")

        # Wait up to 15 minutes for the owner to finish the installer.
        for _ in range(15 * 60 // 3):
            if ollama_client.is_running() or (find_ollama_exe() and start_ollama()["ok"]):
                _update(_ollama_job, state="done", message="AI engine installed and running.")
                return
            time.sleep(3)
        _update(_ollama_job, state="error",
                message="Installer not finished yet. Complete it, then press 'Start AI engine'.")
    except Exception as exc:
        _update(_ollama_job, state="error", message=f"Could not install the AI engine: {exc}")


def start_ollama_install(force: bool = False) -> dict:
    """
    Begin Job 1 in the background (ignored if it's already running).
    force=True is used by updates.py to install a newer Ollama over the
    current one (the official installer upgrades in place).
    """
    with _lock:
        if _ollama_job["state"] in ("downloading", "installing"):
            return {"ok": True, "message": "Already in progress."}
        _ollama_job.update(state="downloading", message="Starting…")
    threading.Thread(target=_install_ollama_worker, daemon=True).start()
    return {"ok": True, "message": "Started."}


# --------------------------------------------------------------------------- #
# Job 2: models
# --------------------------------------------------------------------------- #

def _pull_models_worker(names: list[str], force: bool = False) -> None:
    """
    Background thread: download each missing model through Ollama's
    /api/pull, which streams one JSON line per progress update
    ({"status", "total", "completed"}). We record completed/total per model
    so the window can draw a progress bar for each.
    """
    try:
        installed = ollama_client.installed_models()
        for name in names:
            if not force and ollama_client.has_model(name, installed):
                continue  # force=True (updates.py) re-pulls to fetch a newer version
            _update(_models_job, current=name, message=f"Downloading {name}…")
            with httpx.stream("POST", f"{config.OLLAMA_URL}/api/pull",
                              json={"model": name, "stream": True}, timeout=None) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise RuntimeError(f"{name}: {event['error']}")
                    if event.get("total"):
                        with _lock:
                            _models_job["progress"][name] = {
                                "completed": int(event.get("completed") or 0),
                                "total": int(event["total"]),
                            }
        _update(_models_job, state="done", current=None, message="All models downloaded.")
    except Exception as exc:
        _update(_models_job, state="error", current=None, message=f"Download stopped: {exc}")


def start_model_downloads(include_benchmark_extras: bool = True,
                          names: list[str] | None = None, force: bool = False) -> dict:
    """
    Begin Job 2. include_benchmark_extras=False downloads only the three
    required models (~8 GB) instead of all candidates (~15 GB).
    names + force=True: re-download exactly these models even if present —
    used by updates.py to fetch a newer published version.
    """
    if not ollama_client.is_running():
        return {"ok": False, "message": "Start the AI engine first."}
    if names is None:
        names = WIZARD_MODELS if include_benchmark_extras else REQUIRED_MODELS
    with _lock:
        if _models_job["state"] == "running":
            return {"ok": True, "message": "Already downloading."}
        _models_job.update(state="running", message="Starting downloads…", current=None)
    with _lock:
        for n in names:                      # reset bars for re-downloads
            _models_job["progress"].pop(n, None)
    threading.Thread(target=_pull_models_worker, args=(names, force), daemon=True).start()
    return {"ok": True, "message": "Started."}


def remove_models(names: list[str]) -> dict:
    """
    Delete downloaded models the app no longer needs (the benchmark's
    comparison models) to free disk space. Required models are refused.
    """
    removed, failed = [], []
    for n in names:
        if n in REQUIRED_MODELS or n not in WIZARD_MODELS:
            failed.append(n)
            continue
        (removed if ollama_client.delete_model(n) else failed).append(n)
    msg = f"Removed {len(removed)} model(s)." if removed else "Nothing removed."
    if failed:
        msg += f" Kept: {', '.join(failed)}."
    return {"ok": bool(removed), "message": msg, "removed": removed}


# --------------------------------------------------------------------------- #
# Job 3: benchmark
# --------------------------------------------------------------------------- #

def _benchmark_worker(folder: Path) -> None:
    """Background thread: run the benchmark and remember the report path."""
    try:
        md_path, _json_path = benchmark.run_benchmark(
            folder,
            progress=lambda msg: _update(_bench_job, message=msg),
            should_stop=_bench_cancel.is_set,
        )
        _update(_bench_job, state="done", report=str(md_path),
                message="Benchmark finished. Send the report to Claude.")
    except benchmark.Cancelled:
        _update(_bench_job, state="idle", message="Benchmark cancelled.")
    except Exception as exc:
        _update(_bench_job, state="error", message=f"Benchmark failed: {exc}")


def cancel_benchmark() -> dict:
    """
    Ask the running benchmark to stop. It stops before its next model
    request (the request in progress finishes first, at most a minute or two).
    """
    if _bench_job["state"] != "running":
        return {"ok": True, "message": "Nothing to cancel."}
    _bench_cancel.set()
    _update(_bench_job, message="Cancelling after the current step…")
    return {"ok": True, "message": "Cancelling."}


def start_benchmark(folder: str) -> dict:
    """Begin Job 3 on the chosen folder (must exist and contain PDFs)."""
    path = Path(folder)
    if not path.is_dir():
        return {"ok": False, "message": "That folder doesn't exist."}
    if not any(p.suffix.lower() == ".pdf" for p in path.iterdir()):
        return {"ok": False, "message": "No PDF files in that folder."}
    if not ollama_client.is_running():
        return {"ok": False, "message": "Start the AI engine first."}
    with _lock:
        if _bench_job["state"] == "running":
            return {"ok": True, "message": "Already running."}
        _bench_job.update(state="running", message="Starting…", report=None, folder=str(path),
                          started_at=time.time())
    _bench_cancel.clear()
    threading.Thread(target=_benchmark_worker, args=(path,), daemon=True).start()
    return {"ok": True, "message": "Started."}
