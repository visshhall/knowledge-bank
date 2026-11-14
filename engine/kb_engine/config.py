"""
config.py — every setting of the engine, in one place.

WHAT:  Defines where data is stored, which port the engine listens on, and
       which AI models are used.

WHY:   If paths or model names were scattered across files, changing a model
       later (e.g. after the Phase 0 benchmark) would mean hunting through the
       code. Here it's one edit.

WHEN:  Imported by every other module the moment they load.

CONNECTED TO: db.py, server.py, system_check.py, ollama_client.py,
       benchmark.py all read values from here.

OVERRIDES: Any value can be changed without editing code by setting an
       environment variable (listed next to each setting). This lets the
       owner test a different model with one command.
"""

import os
from pathlib import Path


def _default_data_dir() -> Path:
    """
    Decide where the knowledge bank lives on disk.

    WHAT:  Returns the folder that holds the database, imported-file cache
           and reports.
    HOW:   On Windows this is %LOCALAPPDATA%\\KnowledgeBank (the standard
           place for per-user app data, and NOT inside the code folder, so
           updating the app never touches the owner's data). On other systems
           (used only for development/testing) it is ~/.knowledge-bank.
    WHEN:  Called once, when this module loads.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "KnowledgeBank"
    return Path.home() / ".knowledge-bank"


# --- Storage -----------------------------------------------------------------

# Root data folder. Override: KB_DATA_DIR
DATA_DIR = Path(os.environ.get("KB_DATA_DIR", _default_data_dir()))

# The single SQLite file that holds the entire knowledge bank
# (sources, pages, passages, topics, links, conflicts).
DB_PATH = DATA_DIR / "knowledge_bank.sqlite3"

# Where benchmark and diagnostic reports are written for the owner to send.
REPORTS_DIR = DATA_DIR / "reports"

# --- Local server ------------------------------------------------------------

# 127.0.0.1 = "this computer only". The engine is never reachable from the
# network, which matters because the documents may be confidential.
ENGINE_HOST = "127.0.0.1"

# Port the window uses to reach the engine. Override: KB_ENGINE_PORT
ENGINE_PORT = int(os.environ.get("KB_ENGINE_PORT", "8765"))

# --- Local AI (Ollama) ---------------------------------------------------------

# Ollama runs the AI models locally and listens on this address by default.
# Override: KB_OLLAMA_URL
OLLAMA_URL = os.environ.get("KB_OLLAMA_URL", "http://127.0.0.1:11434")

# FAST model: used for interactive answers (search pages, quick questions).
# ~4B models fit fully inside the RTX 3060's 6 GB, so they are quick.
# Final choice is made from the Phase 0 benchmark. Override: KB_FAST_MODEL
FAST_MODEL = os.environ.get("KB_FAST_MODEL", "qwen3.5:4b")

# DEEP model: used only for the overnight job that writes Knowledge Topics,
# where quality matters more than speed. An ~8B model is tight on 6 GB and
# may spill partly into system RAM (slower), which is acceptable overnight.
# Override: KB_DEEP_MODEL
DEEP_MODEL = os.environ.get("KB_DEEP_MODEL", "qwen3:8b")

# EMBEDDING model: turns text into numbers that capture meaning, so the app
# can find passages that say the same thing in different words.
# Override: KB_EMBED_MODEL
EMBED_MODEL = os.environ.get("KB_EMBED_MODEL", "nomic-embed-text")

# Every model the benchmark compares. The owner's results decide which
# become FAST_MODEL and DEEP_MODEL. Override: KB_BENCHMARK_MODELS (comma list)
BENCHMARK_MODELS = [
    m.strip()
    for m in os.environ.get(
        "KB_BENCHMARK_MODELS", "qwen3.5:4b,qwen3:4b,qwen3:8b,llama3.1:8b"
    ).split(",")
    if m.strip()
]

# How long to wait for one AI response before giving up (seconds).
# Generous because an 8B model partly running on RAM can be slow.
OLLAMA_TIMEOUT_SECONDS = float(os.environ.get("KB_OLLAMA_TIMEOUT", "600"))


def ensure_dirs() -> None:
    """
    Create the data and report folders if they don't exist yet.

    WHEN:  Called by db.py, server.py and benchmark.py before writing files.
    WHY:   On first launch nothing exists; this prevents "folder not found"
           errors. Safe to call repeatedly (does nothing if folders exist).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
