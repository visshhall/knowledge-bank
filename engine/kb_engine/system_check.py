"""
system_check.py — reports whether the laptop is ready to run the Knowledge Bank.

WHAT:  Collects GPU name/memory, RAM, free disk space, Python/SQLite details,
       Ollama status and which required models are downloaded — and marks
       each as OK or a problem with a plain-English fix.

WHY:   Most "it doesn't work" problems in local-AI apps are setup problems
       (Ollama not running, model not downloaded, low disk). Showing them
       clearly on the status screen saves guessing.

WHEN:  - On demand from the app's status screen (server.py → GET /system).
       - From the command line: `python -m kb_engine.system_check`
         (prints a readable report; developer/troubleshooting use).

CONNECTED TO: config.py, db.py (FTS5 check), ollama_client.py.
"""

import json
import platform
import shutil
import sqlite3
import subprocess
import sys

import psutil

from . import __version__, config, db, ollama_client

# Free disk space below this triggers a warning. Models (~10 GB for the
# full set) + database + caches fit comfortably within 30 GB.
MIN_FREE_DISK_GB = 30


def gpu_info() -> dict:
    """
    Ask the NVIDIA driver about the graphics card via `nvidia-smi`.

    HOW:   nvidia-smi ships with every NVIDIA driver. We request name, total
           and used memory, and driver version in CSV form and parse it.
    RETURNS: {"available": True, "name": ..., "vram_total_mb": ..., ...}
             or {"available": False, "reason": ...} if no NVIDIA GPU/driver.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False, "reason": "nvidia-smi not found (NVIDIA driver missing?)"}
    try:
        out = subprocess.run(
            [
                exe,
                "--query-gpu=name,memory.total,memory.used,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip().splitlines()[0]
        name, total, used, driver = [part.strip() for part in out.split(",")]
        return {
            "available": True,
            "name": name,
            "vram_total_mb": int(float(total)),
            "vram_used_mb": int(float(used)),
            "driver": driver,
        }
    except (subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {"available": False, "reason": f"nvidia-smi failed: {exc}"}


def run_checks() -> dict:
    """
    Run every check and return one structured report.

    STRUCTURE: {"engine_version", "checks": [ {name, ok, detail, fix}, ... ],
                "gpu", "ollama_models", "all_ok"}
    CALLED BY: server.py (GET /system) and main() below.
    """
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "fix": fix})

    # Python version — 3.11+ needed for modern typing used in this code.
    py_ok = sys.version_info >= (3, 11)
    add("Python", py_ok, platform.python_version(),
        "" if py_ok else "Reinstall the Knowledge Bank app (it bundles its own Python).")

    # SQLite full-text search (instant word search depends on it).
    fts = db.fts5_available()
    add("SQLite full-text search", fts, f"SQLite {sqlite3.sqlite_version}",
        "" if fts else "Reinstall the Knowledge Bank app.")

    # GPU.
    gpu = gpu_info()
    if gpu["available"]:
        add("Graphics card", True, f"{gpu['name']} — {gpu['vram_total_mb']} MB video memory")
    else:
        add("Graphics card", False, gpu["reason"],
            "Install/update the NVIDIA driver. The app still works on CPU, but slowly.")

    # RAM — 16 GB recommended so an 8B model can partly spill into RAM.
    ram_gb = psutil.virtual_memory().total / 1024**3
    add("System RAM", ram_gb >= 15, f"{ram_gb:.1f} GB",
        "" if ram_gb >= 15 else "16 GB recommended for the overnight writing model.")

    # Disk space where the knowledge bank lives.
    config.ensure_dirs()
    free_gb = shutil.disk_usage(config.DATA_DIR).free / 1024**3
    add("Free disk space", free_gb >= MIN_FREE_DISK_GB,
        f"{free_gb:.0f} GB free at {config.DATA_DIR}",
        "" if free_gb >= MIN_FREE_DISK_GB else f"Free up at least {MIN_FREE_DISK_GB} GB.")

    # Ollama + required models.
    models: list[str] = []
    if ollama_client.is_running():
        add("Ollama (local AI)", True, f"version {ollama_client.version()}")
        try:
            models = ollama_client.installed_models()
        except ollama_client.OllamaError as exc:
            add("Ollama models", False, str(exc), "Restart Ollama.")
        for role, name in (("Fast model", config.FAST_MODEL),
                           ("Deep model", config.DEEP_MODEL),
                           ("Embedding model", config.EMBED_MODEL)):
            present = ollama_client.has_model(name, models)
            add(f"{role} ({name})", present,
                "downloaded" if present else "not downloaded",
                "" if present else "Use the Setup panel: Download AI models.")
    else:
        add("Ollama (local AI)", False, f"not answering at {config.OLLAMA_URL}",
            "Use the Setup panel: Install / Start AI engine.")

    return {
        "engine_version": __version__,
        "data_dir": str(config.DATA_DIR),
        "checks": checks,
        "gpu": gpu,
        "ollama_models": models,
        "all_ok": all(c["ok"] for c in checks),
    }


def main() -> None:
    """
    Command-line entry point: prints a readable report.
    Add --json to print raw JSON instead (useful when sending results to Claude).
    """
    report = run_checks()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return
    print(f"\nKnowledge Bank — system check (engine {report['engine_version']})")
    print(f"Data folder: {report['data_dir']}\n")
    for c in report["checks"]:
        mark = "OK  " if c["ok"] else "FIX "
        print(f"  [{mark}] {c['name']}: {c['detail']}")
        if c["fix"]:
            print(f"         -> {c['fix']}")
    print("\nAll good!" if report["all_ok"] else "\nSome items need attention (see -> lines).")


if __name__ == "__main__":
    main()
