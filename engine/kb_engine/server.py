"""
server.py — the private local web server the desktop window talks to.

WHAT:  A small FastAPI server on 127.0.0.1:8765 (this computer only).
       Endpoints:
         GET  /health                  — "are you alive?" + engine version
         GET  /system                  — readiness report (GPU, RAM, disk, Ollama, models)
         GET  /stats                   — what the knowledge bank holds (dashboard)
         GET  /setup/status            — live state of the setup wizard jobs
         POST /setup/ollama/install    — download + open the Ollama installer
         POST /setup/ollama/start      — start Ollama if installed but stopped
         POST /setup/models/pull       — download AI models (with progress)
         POST /setup/benchmark/start   — run the benchmark on a chosen folder
         POST /setup/benchmark/cancel  — stop a running benchmark
         POST /setup/models/remove     — delete comparison models (frees disk)
         GET  /library                 — every imported file with its counts
         POST /library/add             — import files/folders
         POST /library/remove          — take one file out of the bank
         POST /library/retry           — re-queue files that failed
         GET  /import/status           — live import progress
         GET  /settings/watch          — watched folders
         POST /settings/watch          — change watched folders
         GET  /search?q=...            — instant exact-word search
         POST /distill/start           — build topics (Phase 2)
         GET  /distill/status          — live progress of building topics
         GET  /topics                  — all topics with sizes + links
         GET  /topic?id=...            — one topic's article, points and sources
         POST /write/start             — write topic articles (Phase 3)
         GET  /write/status            — live progress of article writing
         POST /write/cancel            — stop after the current article
         GET  /passage/context?id=...  — a passage with its neighbours (v0.6.1)
         GET  /search/quick?q=...      — meaning + word search for Ctrl+K (v0.6.3)
         GET  /overview/flow           — files → topics counts for the Overview map (v0.6.3)
         GET  /passage/section?id=...  — the whole document part it belongs to (v0.6.3)
         GET  /lesson?id=...           — a topic's visual lesson + check results
         POST /lesson/regenerate       — redesign one topic's lesson
         POST /updates/check           — online check for Ollama/model updates
         GET  /updates/status          — result of the last check
         POST /updates/model           — update one model
         POST /updates/ollama          — install the latest Ollama
       Later phases add written topic pages, answer pages, learn mode, etc.

WHY:   Separating the window (Electron) from the engine (Python) means
       hours-long processing never freezes the interface, and each side uses
       the language best suited to it.

WHEN:  Started automatically by app/electron/main.js when the app opens:
           python -m kb_engine.server
       and stopped when the app closes. Can also be run by hand for testing.

SECURITY:
       - Listens on 127.0.0.1 only → unreachable from the network.
       - Every request must carry the header  X-KB-Token: <secret>.
         main.js creates a fresh random secret each launch and passes it to
         this process (env var KB_ENGINE_TOKEN). This stops other programs or
         malicious web pages in a browser from quietly querying the engine on
         localhost. If no token is set (manual testing), the check is skipped
         and a warning is printed.

CONNECTED TO: config.py, db.py, system_check.py, setup_manager.py,
       importer.py, search.py, distill.py, writer.py, lessons.py, updates.py;
       called by
       app/electron/main.js (which relays requests from the window).
"""

import hmac
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import (__version__, config, db, distill, importer, lessons, meaning, search, setup_manager, system_check, updates, writer)

# Secret shared with the Electron app for this launch only.
_TOKEN = os.environ.get("KB_ENGINE_TOKEN", "")

def require_token(x_kb_token: str = Header(default="")) -> None:
    """
    Reject any request without the correct secret header.

    HOW:   hmac.compare_digest compares in constant time, so the secret can't
           be guessed by measuring how fast wrong guesses are rejected.
    WHEN:  Runs before every endpoint below (FastAPI "dependency").
    """
    if _TOKEN and not hmac.compare_digest(x_kb_token, _TOKEN):
        raise HTTPException(status_code=401, detail="Invalid engine token")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Runs once when the server starts (before `yield`) and once when it stops.

    WHY:   First launch creates the database; later launches upgrade it if
           the app was updated with a newer schema. Doing it here guarantees
           every endpoint can assume the database is ready.
    """
    version = db.init_db()
    print(f"[engine] database ready at {config.DB_PATH} (schema v{version})", flush=True)
    importer.start()  # resume interrupted imports + start watched-folder scanner
    yield
    print("[engine] shutting down", flush=True)


app = FastAPI(title="Knowledge Bank Engine", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None)  # no public API docs page needed


@app.get("/health", dependencies=[Depends(require_token)])
def health() -> dict:
    """Alive-check. main.js polls this until it answers, then shows the window content."""
    return {"ok": True, "engine_version": __version__}


@app.get("/system", dependencies=[Depends(require_token)])
def system() -> dict:
    """Readiness report shown on the status screen (see system_check.run_checks)."""
    return system_check.run_checks()


@app.get("/stats", dependencies=[Depends(require_token)])
def stats() -> dict:
    """Knowledge bank totals and coverage % (see db.stats)."""
    return db.stats()


# ---------------------------------------------------------------------------
# Setup wizard (see setup_manager.py for what each job does)
# ---------------------------------------------------------------------------

class ModelPullRequest(BaseModel):
    """Body of POST /setup/models/pull. False = only the 3 required models."""
    include_benchmark_extras: bool = True


class BenchmarkRequest(BaseModel):
    """Body of POST /setup/benchmark/start — the folder the owner picked."""
    folder: str


@app.get("/setup/status", dependencies=[Depends(require_token)])
def setup_status() -> dict:
    """Polled by the wizard every ~1.5 s to draw progress."""
    return setup_manager.status()


@app.post("/setup/ollama/install", dependencies=[Depends(require_token)])
def setup_ollama_install() -> dict:
    return setup_manager.start_ollama_install()


@app.post("/setup/ollama/start", dependencies=[Depends(require_token)])
def setup_ollama_start() -> dict:
    return setup_manager.start_ollama()


@app.post("/setup/models/pull", dependencies=[Depends(require_token)])
def setup_models_pull(body: ModelPullRequest) -> dict:
    return setup_manager.start_model_downloads(body.include_benchmark_extras)


@app.post("/setup/benchmark/start", dependencies=[Depends(require_token)])
def setup_benchmark_start(body: BenchmarkRequest) -> dict:
    return setup_manager.start_benchmark(body.folder)


# ---------------------------------------------------------------------------
# Library / import (Phase 1 — see importer.py)
# ---------------------------------------------------------------------------

class AddPathsRequest(BaseModel):
    """Files and/or folders the owner chose or dropped onto the window."""
    paths: list[str]


class SourceRequest(BaseModel):
    source_id: int


class WatchRequest(BaseModel):
    folders: list[str]


class RemoveModelsRequest(BaseModel):
    names: list[str]


@app.post("/setup/models/remove", dependencies=[Depends(require_token)])
def setup_models_remove(body: RemoveModelsRequest) -> dict:
    return setup_manager.remove_models(body.names)


@app.post("/setup/benchmark/cancel", dependencies=[Depends(require_token)])
def setup_benchmark_cancel() -> dict:
    return setup_manager.cancel_benchmark()


@app.get("/library", dependencies=[Depends(require_token)])
def library() -> dict:
    return {"sources": importer.library(), "stats": db.stats()}


@app.post("/library/add", dependencies=[Depends(require_token)])
def library_add(body: AddPathsRequest) -> dict:
    return importer.add_paths(body.paths)


@app.post("/library/remove", dependencies=[Depends(require_token)])
def library_remove(body: SourceRequest) -> dict:
    return importer.remove_source(body.source_id)


@app.post("/library/retry", dependencies=[Depends(require_token)])
def library_retry() -> dict:
    return importer.retry_failed()


@app.get("/import/status", dependencies=[Depends(require_token)])
def import_status() -> dict:
    return importer.status()


@app.get("/settings/watch", dependencies=[Depends(require_token)])
def get_watch() -> dict:
    return {"folders": importer.watch_folders()}


@app.post("/settings/watch", dependencies=[Depends(require_token)])
def set_watch(body: WatchRequest) -> dict:
    return importer.set_watch_folders(body.folders)


@app.get("/search", dependencies=[Depends(require_token)])
def search_passages(q: str = "") -> dict:
    return search.search(q)


# ---------------------------------------------------------------------------
# Topics (Phase 2 — see distill.py)
# ---------------------------------------------------------------------------

@app.post("/distill/start", dependencies=[Depends(require_token)])
def distill_start() -> dict:
    return distill.start()


@app.get("/distill/status", dependencies=[Depends(require_token)])
def distill_status() -> dict:
    return distill.status()


@app.get("/topics", dependencies=[Depends(require_token)])
def topics() -> dict:
    return distill.list_topics()


@app.get("/topic", dependencies=[Depends(require_token)])
def topic(id: int) -> dict:
    detail = distill.topic_detail(id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return detail


# ---------------------------------------------------------------------------
# Articles (Phase 3 — see writer.py)
# ---------------------------------------------------------------------------

class WriteRequest(BaseModel):
    """rewrite_all=True rewrites existing articles too (e.g. after a model change)."""
    rewrite_all: bool = False


@app.post("/write/start", dependencies=[Depends(require_token)])
def write_start(body: WriteRequest) -> dict:
    return writer.start(body.rewrite_all)


@app.get("/write/status", dependencies=[Depends(require_token)])
def write_status() -> dict:
    return writer.status()


@app.post("/write/cancel", dependencies=[Depends(require_token)])
def write_cancel() -> dict:
    return writer.cancel()


class TopicRequest(BaseModel):
    topic_id: int


@app.get("/passage/context", dependencies=[Depends(require_token)])
def passage_context(id: int) -> dict:
    """A passage with the text just before and after it ("Read in context")."""
    data = distill.passage_context(id)
    if data is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    return data


@app.get("/passage/section", dependencies=[Depends(require_token)])
def passage_section(id: int) -> dict:
    """Every passage of the same file and document part ("Read the whole section")."""
    data = distill.section_passages(id)
    if data is None:
        raise HTTPException(status_code=404, detail="Passage not found")
    return data


@app.get("/overview/flow", dependencies=[Depends(require_token)])
def overview_flow() -> dict:
    """Files → topics flow counts for the Overview map."""
    return distill.flow()


@app.get("/search/quick", dependencies=[Depends(require_token)])
def search_quick(q: str = "") -> dict:
    """Quick search (Ctrl+K): meaning + exact words, with each hit's topic."""
    return meaning.quick_search(q)


@app.get("/lesson", dependencies=[Depends(require_token)])
def lesson(id: int) -> dict:
    data = lessons.get_lesson(id)
    return data or {"lesson": None}


@app.post("/lesson/regenerate", dependencies=[Depends(require_token)])
def lesson_regenerate(body: TopicRequest) -> dict:
    return writer.start(only_topic=body.topic_id)


# ---------------------------------------------------------------------------
# AI updates (see updates.py)
# ---------------------------------------------------------------------------

class ModelRequest(BaseModel):
    name: str


@app.post("/updates/check", dependencies=[Depends(require_token)])
def updates_check() -> dict:
    return updates.check()


@app.get("/updates/status", dependencies=[Depends(require_token)])
def updates_status() -> dict:
    return updates.last_result()


@app.post("/updates/model", dependencies=[Depends(require_token)])
def updates_model(body: ModelRequest) -> dict:
    return updates.update_model(body.name)


@app.post("/updates/ollama", dependencies=[Depends(require_token)])
def updates_ollama() -> dict:
    return updates.update_ollama()


def main() -> None:
    """
    Start the server.

    log_level="warning" keeps the console quiet; errors still appear.
    The '[engine] ready' line is printed by _startup and is what main.js
    could watch for, though it relies on polling /health to be robust.
    """
    if not _TOKEN:
        print("[engine] WARNING: KB_ENGINE_TOKEN not set — running without "
              "request authentication (OK for manual testing only).",
              file=sys.stderr, flush=True)
    uvicorn.run(app, host=config.ENGINE_HOST, port=config.ENGINE_PORT, log_level="warning")


if __name__ == "__main__":
    main()
