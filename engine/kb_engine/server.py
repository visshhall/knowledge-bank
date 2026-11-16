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
         POST /library/add-text        — import pasted text (v0.13)
         GET  /memory · POST /memory/add · /memory/update · /memory/delete · /memory/clear · /memory/enable
              · /memory/suggest {chat_id} · GET /memory/suggest/status   (v0.14 memory about the owner)
         POST /crawl/start · GET /crawl/status · POST /crawl/stop — read a web page, section or site (v0.13)
         POST /library/remove          — take one file out of the bank
         POST /library/remove-many     — take several files out (and everything built from them)
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
         POST /answer/ask {question}   — write a cited answer (v0.7, background)
         GET  /answer/status · /answers · /answer?id · POST /answer/delete
         GET  /chat/list[?q] · /chat/get?id · /chat/status · POST /chat/new · /chat/rename
              · /chat/delete · /chat/send {chat_id, text, general, mode, persona_id} · /chat/stop   (v0.11 Chat;
              mode = library | both | free is v0.12)
         POST /chat/undo {chat_id} (v0.15 Regenerate / Edit)
         GET  /chat/personas · POST /chat/persona/save {id?, name, prompt} · /chat/persona/delete {id}   (v0.12 personas)
         GET  /models/choices · /models/compare/status · POST /models/select · /models/download
              · /models/compare/start · /models/compare/cancel           (v0.11 model picker)
         POST /backup/create · /backup/restore {path, password} · GET /backup/status
         POST /distill/update          — add new passages to existing topics (Phase 7)
         POST /tools/iocs {text} · GET /tools/bank-iocs · /tools/mitre · /tools/queries
         GET  /learn/summary · /learn/session[?topic_id] · POST /learn/review
         GET  /source?id=...           — an imported file's path (open at page)
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
       importer.py, search.py, distill.py, writer.py, lessons.py, updates.py,
       chat.py, modelpick.py, personas.py;
       called by
       app/electron/main.js (which relays requests from the window).
"""

import hmac
import os
import sys
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import (__version__, answers, backup, chat, config, crawler, datapages, coverage, db, distill, gpu, storage, topicedit, importer, learn, learner, lessons, taxonomy, mistakes, meaning, memory, modelpick, personas, search, setup_manager, system_check, tools, training, updates, websearch, writer)

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
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if backup.apply_pending_restore():  # a checked restore waits for this start (Phase 7)
        print("[engine] restored the bank from a backup", flush=True)
    version = db.init_db()
    print(f"[engine] database ready at {config.DB_PATH} (schema v{version})", flush=True)
    importer.start()  # resume interrupted imports + start watched-folder scanner
    taxonomy.start()  # v0.19: categories that grow (idle until files fit no category)
    learner.start()  # v0.16: web learning loop (does nothing until the owner turns it on in Learning)
    # v0.8: spreadsheets imported before data topics existed get their charts,
    # checks and Subnet Lab now, without the owner pressing "Rebuild topics".
    # Runs in a thread so a large bank never delays the '[engine] ready' line.
    def _data_topics():
        try:
            n = datapages.rebuild_data_topics()
            if n:
                print(f"[engine] built {n} spreadsheet topic(s)", flush=True)
        except Exception as exc:  # never block startup over a bad sheet
            print(f"[engine] spreadsheet topics skipped: {exc}", flush=True)
    threading.Thread(target=_data_topics, daemon=True).start()
    # v0.8.2: Windows — turn on Ollama's memory savers once (gpu.py).
    def _gpu_settings():
        try:
            if gpu.apply_ollama_settings():
                print("[engine] Ollama memory savers turned on", flush=True)
        except Exception as exc:
            print(f"[engine] Ollama settings skipped: {exc}", flush=True)
    threading.Thread(target=_gpu_settings, daemon=True).start()
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


class SourcesRequest(BaseModel):
    source_ids: list[int]


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
    # picked=True: the owner chose these in the window, so a removed file
    # picked directly comes back (folder adds still skip removed files).
    return importer.add_paths(body.paths, picked=True)


# --- v0.9: editing topics by hand (topicedit.py) ---------------------------------

class RenameRequest(BaseModel):
    topic_id: int
    title: str


class MergeRequest(BaseModel):
    topic_id: int
    others: list[int]


class MovePointsRequest(BaseModel):
    topic_id: int
    points: list[int]
    to_topic_id: int | None = None
    title: str | None = None


@app.get("/storage", dependencies=[Depends(require_token)])
def storage_report() -> dict:
    """v0.9: disk space used by the bank and what a clean-up would free."""
    return storage.report()


@app.post("/storage/cleanup", dependencies=[Depends(require_token)])
def storage_cleanup() -> dict:
    return storage.start_cleanup()


@app.get("/topics/names", dependencies=[Depends(require_token)])
def topics_names() -> dict:
    return {"topics": topicedit.topic_list()}


@app.post("/topics/rename", dependencies=[Depends(require_token)])
def topics_rename(body: RenameRequest) -> dict:
    return topicedit.rename(body.topic_id, body.title)


@app.post("/topics/merge", dependencies=[Depends(require_token)])
def topics_merge(body: MergeRequest) -> dict:
    return topicedit.merge(body.topic_id, body.others)


@app.post("/topics/move", dependencies=[Depends(require_token)])
def topics_move(body: MovePointsRequest) -> dict:
    return topicedit.move_points(body.topic_id, body.points, body.to_topic_id or 0)


@app.post("/topics/split", dependencies=[Depends(require_token)])
def topics_split(body: MovePointsRequest) -> dict:
    return topicedit.split(body.topic_id, body.points, body.title or "")


@app.get("/gpu/status", dependencies=[Depends(require_token)])
def gpu_status() -> dict:
    """v0.8.2: graphics card, model split, speeds, advice (Setup screen)."""
    return gpu.report()


@app.post("/gpu/tune", dependencies=[Depends(require_token)])
def gpu_tune() -> dict:
    """v0.8.2: measure and choose the fastest graphics-card placement."""
    return gpu.start_tune()


@app.post("/library/keep", dependencies=[Depends(require_token)])
def library_keep(body: SourceRequest) -> dict:
    """v0.8.2: import a set-aside (not-cybersecurity) file anyway."""
    return importer.keep_anyway(body.source_id)


class FlagRequest(BaseModel):
    on: bool


@app.get("/library/filter", dependencies=[Depends(require_token)])
def library_filter_get() -> dict:
    return {"on": importer.relevance_filter_on(), "dedupe": importer.dedupe_on()}


@app.post("/library/dedupe", dependencies=[Depends(require_token)])
def library_dedupe_set(body: FlagRequest) -> dict:
    """v0.8.2: the 'Skip content already in the bank' switch in Library."""
    db.set_setting("dedupe_filter", bool(body.on))
    return {"on": bool(body.on)}


@app.post("/library/filter", dependencies=[Depends(require_token)])
def library_filter_set(body: FlagRequest) -> dict:
    """v0.8.2: the 'Only keep cybersecurity files' switch in Library."""
    db.set_setting("relevance_filter", bool(body.on))
    return {"on": bool(body.on)}


@app.post("/library/remove", dependencies=[Depends(require_token)])
def library_remove(body: SourceRequest) -> dict:
    return importer.remove_source(body.source_id)


@app.post("/library/remove-many", dependencies=[Depends(require_token)])
def library_remove_many(body: SourcesRequest) -> dict:
    return importer.remove_sources(body.source_ids)


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
def search_passages(q: str = "", source_id: int | None = None, topic_id: int | None = None,
                    kind: str | None = None, category: str | None = None) -> dict:
    """Word search with v0.9 filters (file, topic, kind of text, category)."""
    return search.search(q, source_id=source_id, topic_id=topic_id, kind=kind or None,
                         category=category or None)


# ---------------------------------------------------------------------------
# Topics (Phase 2 — see distill.py)
# ---------------------------------------------------------------------------

@app.post("/distill/start", dependencies=[Depends(require_token)])
def distill_start() -> dict:
    return distill.start()


@app.post("/distill/update", dependencies=[Depends(require_token)])
def distill_update() -> dict:
    """Phase 7: add new passages to existing topics (no full rebuild)."""
    return distill.start_update()


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


@app.post("/write/topic", dependencies=[Depends(require_token)])
def write_topic_now(body: TopicRequest) -> dict:
    """"Write this topic now": jump the queue, or start with just this topic (v0.8)."""
    return writer.write_now(body.topic_id)



# --- v0.7: answer pages, original files --------------------------------------

class AskRequest(BaseModel):
    question: str


class IdRequest(BaseModel):
    id: int


class RuleToggleRequest(BaseModel):
    id: int
    on: bool


@app.post("/answer/ask", dependencies=[Depends(require_token)])
def answer_ask(body: AskRequest) -> dict:
    """Start writing a cited answer from the best passages (background)."""
    return answers.ask(body.question)


@app.get("/answer/status", dependencies=[Depends(require_token)])
def answer_status() -> dict:
    return answers.status()


@app.get("/answers", dependencies=[Depends(require_token)])
def answers_recent() -> dict:
    return answers.recent()


@app.get("/answer", dependencies=[Depends(require_token)])
def answer_get(id: int) -> dict:
    data = answers.get(id)
    if data is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return data


@app.post("/answer/delete", dependencies=[Depends(require_token)])
def answer_delete(body: IdRequest) -> dict:
    return answers.delete(body.id)


# --- v0.14: memory about the owner (memory.py) --------------------------------------

class MemoryAddRequest(BaseModel):
    text: str
    pinned: bool = False


class MemoryUpdateRequest(BaseModel):
    id: int
    text: str | None = None
    pinned: bool | None = None


class EnableRequest(BaseModel):
    on: bool


class MemorySuggestRequest(BaseModel):
    chat_id: int


@app.get("/memory", dependencies=[Depends(require_token)])
def memory_list() -> dict:
    return memory.list_all()


@app.post("/memory/add", dependencies=[Depends(require_token)])
def memory_add(body: MemoryAddRequest) -> dict:
    return memory.add(body.text, body.pinned)


@app.post("/memory/update", dependencies=[Depends(require_token)])
def memory_update(body: MemoryUpdateRequest) -> dict:
    return memory.update(body.id, body.text, body.pinned)


@app.post("/memory/delete", dependencies=[Depends(require_token)])
def memory_delete(body: IdRequest) -> dict:
    return memory.delete(body.id)


@app.post("/memory/clear", dependencies=[Depends(require_token)])
def memory_clear() -> dict:
    return memory.clear()


@app.post("/memory/enable", dependencies=[Depends(require_token)])
def memory_enable(body: EnableRequest) -> dict:
    return memory.set_enabled(body.on)


@app.post("/memory/suggest", dependencies=[Depends(require_token)])
def memory_suggest(body: MemorySuggestRequest) -> dict:
    return memory.suggest(body.chat_id)


@app.get("/memory/suggest/status", dependencies=[Depends(require_token)])
def memory_suggest_status() -> dict:
    return memory.suggest_status()


# --- v0.13: add pages from the web and pasted text ----------------------------------

class CrawlStartRequest(BaseModel):
    """Body of POST /crawl/start: a web address, how far to follow links, and the page limit."""
    url: str
    scope: str = "section"          # "page" | "section" | "site"
    max_pages: int = 30
    depth: int | None = None


class AddTextRequest(BaseModel):
    """Body of POST /library/add-text: text the owner pasted."""
    title: str = ""
    text: str


@app.post("/crawl/start", dependencies=[Depends(require_token)])
def crawl_start(body: CrawlStartRequest) -> dict:
    return crawler.start(body.url, body.scope, body.max_pages, body.depth)


@app.get("/crawl/status", dependencies=[Depends(require_token)])
def crawl_status() -> dict:
    return crawler.status()


@app.post("/crawl/stop", dependencies=[Depends(require_token)])
def crawl_stop() -> dict:
    return crawler.stop()


@app.post("/library/add-text", dependencies=[Depends(require_token)])
def library_add_text(body: AddTextRequest) -> dict:
    return importer.add_text(body.title, body.text)


# --- v0.11: Chat (saved conversations with the library) and the model picker --

class ChatSendRequest(BaseModel):
    """Body of POST /chat/send. chat_id None starts a new chat."""
    chat_id: int | None = None
    text: str
    general: bool = False          # v0.11 way of asking for mode "both"
    mode: str | None = None        # v0.12: "library" | "both" | "free"
    persona_id: int | None = None  # v0.12: who answers in Free mode (None = the Assistant)


class ChatUndoRequest(BaseModel):
    """Body of POST /chat/undo: take back the last question and answer. reason: "regen" or "edit"."""
    chat_id: int
    reason: str = "regen"


class SignalRequest(BaseModel):
    """Body of POST /training/signal: a reaction to an answer (up, down, copy)."""
    message_id: int
    signal: str


class CorrectRequest(BaseModel):
    """Body of POST /training/correct: the answer the owner wanted instead."""
    message_id: int
    text: str


class ExampleStatusRequest(BaseModel):
    id: int
    status: str


class LearnToggleRequest(BaseModel):
    on: bool


class LearnLimitsRequest(BaseModel):
    daily_pages: int | None = None
    round_gap_min: int | None = None


class LearnTopicRequest(BaseModel):
    topic: str


class LearnWatchRequest(BaseModel):
    url: str
    scope: str = "section"
    max_pages: int = 30


class IdRequest(BaseModel):
    id: int


class PersonaSaveRequest(BaseModel):
    """Body of POST /chat/persona/save. id None creates a new persona of the owner's own."""
    id: int | None = None
    name: str
    prompt: str


class ChatNewRequest(BaseModel):
    title: str | None = None


class ChatRenameRequest(BaseModel):
    id: int
    title: str


class ModelRequest(BaseModel):
    model: str


class CompareRequest(BaseModel):
    """Body of POST /models/compare/start: 2–3 installed models, optional own questions."""
    models: list[str]
    questions: list[str] | None = None


@app.get("/chat/list", dependencies=[Depends(require_token)])
def chat_list(q: str = "") -> dict:
    return chat.list_chats(q)


@app.post("/chat/new", dependencies=[Depends(require_token)])
def chat_new(body: ChatNewRequest) -> dict:
    return chat.new_chat(body.title)


@app.get("/chat/get", dependencies=[Depends(require_token)])
def chat_get(id: int) -> dict:
    data = chat.get_chat(id)
    if data is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return data


@app.post("/chat/rename", dependencies=[Depends(require_token)])
def chat_rename(body: ChatRenameRequest) -> dict:
    return chat.rename_chat(body.id, body.title)


@app.post("/chat/delete", dependencies=[Depends(require_token)])
def chat_delete(body: IdRequest) -> dict:
    return chat.delete_chat(body.id)


@app.post("/chat/send", dependencies=[Depends(require_token)])
def chat_send(body: ChatSendRequest) -> dict:
    return chat.send(body.chat_id, body.text, body.general, body.mode, body.persona_id)


@app.post("/chat/undo", dependencies=[Depends(require_token)])
def chat_undo(body: ChatUndoRequest) -> dict:
    return chat.undo_last(body.chat_id, body.reason)


# --- v0.16: learning from use (training.py) and learning from the web (learner.py) ----------------

@app.post("/training/signal", dependencies=[Depends(require_token)])
def training_signal(body: SignalRequest) -> dict:
    return training.record(body.message_id, body.signal)


@app.post("/training/correct", dependencies=[Depends(require_token)])
def training_correct(body: CorrectRequest) -> dict:
    return training.correct(body.message_id, body.text)


@app.get("/training/status", dependencies=[Depends(require_token)])
def training_status() -> dict:
    return training.status()


@app.get("/training/examples", dependencies=[Depends(require_token)])
def training_examples(status: str = "new", limit: int = 40, offset: int = 0) -> dict:
    return training.examples(status, limit, offset)


@app.post("/training/example/status", dependencies=[Depends(require_token)])
def training_example_status(body: ExampleStatusRequest) -> dict:
    return training.set_status(body.id, body.status)


@app.post("/training/export", dependencies=[Depends(require_token)])
def training_export() -> dict:
    return training.export()


# --- v0.18: coverage, gaps and site quality (coverage.py) -------------------------------------

class SiteRequest(BaseModel):
    host: str
    action: str


class PruneRequest(BaseModel):
    days: int = 45


@app.get("/coverage/status", dependencies=[Depends(require_token)])
def coverage_status() -> dict:
    return coverage.status()


@app.post("/coverage/plan", dependencies=[Depends(require_token)])
def coverage_plan() -> dict:
    return coverage.plan_topics(force=True)


@app.post("/coverage/auto", dependencies=[Depends(require_token)])
def coverage_auto(body: LearnToggleRequest) -> dict:
    return coverage.set_auto(body.on)


@app.post("/coverage/site", dependencies=[Depends(require_token)])
def coverage_site(body: SiteRequest) -> dict:
    return coverage.set_site(body.host, body.action)


@app.post("/coverage/prune-unused", dependencies=[Depends(require_token)])
def coverage_prune(body: PruneRequest) -> dict:
    return coverage.prune_unused(body.days)


# --- v0.19: categories that grow (taxonomy.py) -------------------------------------------------

class CategoryRename(BaseModel):
    name: str
    new: str


class CategoryMerge(BaseModel):
    name: str
    into: str


class CategoryName(BaseModel):
    name: str


@app.get("/taxonomy/status", dependencies=[Depends(require_token)])
def taxonomy_status() -> dict:
    return taxonomy.status()


@app.post("/taxonomy/run", dependencies=[Depends(require_token)])
def taxonomy_run() -> dict:
    return taxonomy.grow()


@app.post("/taxonomy/auto", dependencies=[Depends(require_token)])
def taxonomy_auto(body: LearnToggleRequest) -> dict:
    return taxonomy.set_auto(body.on)


@app.post("/taxonomy/rename", dependencies=[Depends(require_token)])
def taxonomy_rename(body: CategoryRename) -> dict:
    return taxonomy.rename(body.name, body.new)


@app.post("/taxonomy/merge", dependencies=[Depends(require_token)])
def taxonomy_merge(body: CategoryMerge) -> dict:
    return taxonomy.merge(body.name, body.into)


@app.post("/taxonomy/delete", dependencies=[Depends(require_token)])
def taxonomy_delete(body: CategoryName) -> dict:
    return taxonomy.delete(body.name)


# --- v0.17: mistakes and lessons (mistakes.py) ---------------------------------------------------

@app.get("/lessons/status", dependencies=[Depends(require_token)])
def lessons_status() -> dict:
    return mistakes.status()


@app.post("/lessons/enable", dependencies=[Depends(require_token)])
def lessons_enable(body: LearnToggleRequest) -> dict:
    return mistakes.set_enabled(body.on)


@app.post("/lessons/run", dependencies=[Depends(require_token)])
def lessons_run() -> dict:
    return mistakes.run_patterns()


@app.post("/lessons/rule/toggle", dependencies=[Depends(require_token)])
def lessons_toggle(body: RuleToggleRequest) -> dict:
    return mistakes.set_rule(body.id, body.on)


@app.post("/lessons/rule/delete", dependencies=[Depends(require_token)])
def lessons_delete(body: IdRequest) -> dict:
    return mistakes.delete_rule(body.id)


@app.get("/learn/status", dependencies=[Depends(require_token)])
def learn_status() -> dict:
    return learner.status()


@app.post("/learn/enable", dependencies=[Depends(require_token)])
def learn_enable(body: LearnToggleRequest) -> dict:
    return learner.set_enabled(body.on)


@app.post("/learn/limits", dependencies=[Depends(require_token)])
def learn_limits(body: LearnLimitsRequest) -> dict:
    return learner.set_limits(body.daily_pages, body.round_gap_min)


@app.post("/learn/run", dependencies=[Depends(require_token)])
def learn_run() -> dict:
    return learner.run_now()


@app.post("/learn/topic/add", dependencies=[Depends(require_token)])
def learn_topic_add(body: LearnTopicRequest) -> dict:
    return learner.add_topic(body.topic)


@app.post("/learn/topic/remove", dependencies=[Depends(require_token)])
def learn_topic_remove(body: IdRequest) -> dict:
    return learner.remove_topic(body.id)


@app.post("/learn/watch/add", dependencies=[Depends(require_token)])
def learn_watch_add(body: LearnWatchRequest) -> dict:
    return learner.add_watch(body.url, body.scope, body.max_pages)


@app.post("/learn/watch/remove", dependencies=[Depends(require_token)])
def learn_watch_remove(body: IdRequest) -> dict:
    return learner.remove_watch(body.id)


@app.get("/learn/pages", dependencies=[Depends(require_token)])
def learn_pages(limit: int = 50, offset: int = 0) -> dict:
    return learner.learned_pages(limit, offset)


@app.post("/learn/remove-all", dependencies=[Depends(require_token)])
def learn_remove_all() -> dict:
    return learner.remove_all_learned()


@app.get("/chat/personas", dependencies=[Depends(require_token)])
def chat_personas() -> dict:
    return personas.list_all()


@app.post("/chat/persona/save", dependencies=[Depends(require_token)])
def chat_persona_save(body: PersonaSaveRequest) -> dict:
    return personas.save(body.id, body.name, body.prompt)


@app.post("/chat/persona/delete", dependencies=[Depends(require_token)])
def chat_persona_delete(body: IdRequest) -> dict:
    return personas.delete(body.id)


@app.get("/chat/status", dependencies=[Depends(require_token)])
def chat_status() -> dict:
    return chat.status()


@app.post("/chat/stop", dependencies=[Depends(require_token)])
def chat_stop() -> dict:
    return chat.stop()


@app.get("/models/choices", dependencies=[Depends(require_token)])
def models_choices() -> dict:
    return modelpick.choices()


@app.post("/models/select", dependencies=[Depends(require_token)])
def models_select(body: ModelRequest) -> dict:
    return modelpick.select(body.model)


@app.post("/models/download", dependencies=[Depends(require_token)])
def models_download(body: ModelRequest) -> dict:
    return modelpick.download(body.model)


@app.post("/models/compare/start", dependencies=[Depends(require_token)])
def models_compare_start(body: CompareRequest) -> dict:
    return modelpick.start_compare(body.models, body.questions)


@app.get("/models/compare/status", dependencies=[Depends(require_token)])
def models_compare_status() -> dict:
    return modelpick.compare_status()


@app.post("/models/compare/cancel", dependencies=[Depends(require_token)])
def models_compare_cancel() -> dict:
    return modelpick.cancel_compare()


@app.get("/source", dependencies=[Depends(require_token)])
def source_get(id: int) -> dict:
    """Where an imported file lives, so the app can open it at a page."""
    with db.connect() as conn:
        r = conn.execute("SELECT id, file_name, file_type, original_path, url FROM sources WHERE id = ?",
                         (id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="File not found")
    from pathlib import Path
    return {"id": r["id"], "file_name": r["file_name"], "file_type": r["file_type"],
            "path": r["original_path"], "exists": Path(r["original_path"]).exists(), "url": r["url"]}


# --- v0.7: analyst tools ---------------------------------------------------

class TextRequest(BaseModel):
    text: str


@app.post("/tools/iocs", dependencies=[Depends(require_token)])
def tools_iocs(body: TextRequest) -> dict:
    """Indicators in pasted text (refanged + defanged)."""
    return tools.extract_iocs(body.text[:500_000])


@app.get("/tools/bank-iocs", dependencies=[Depends(require_token)])
def tools_bank_iocs() -> dict:
    return tools.bank_iocs()


@app.get("/tools/mitre", dependencies=[Depends(require_token)])
def tools_mitre() -> dict:
    return tools.mitre()


@app.get("/tools/queries", dependencies=[Depends(require_token)])
def tools_queries() -> dict:
    return tools.queries()


class UnlockRequest(BaseModel):
    source_id: int
    password: str


@app.post("/library/password", dependencies=[Depends(require_token)])
def library_password(body: UnlockRequest) -> dict:
    """Open a password-protected PDF (password used once, never stored)."""
    return importer.unlock(body.source_id, body.password)


# --- v0.7: encrypted backup ------------------------------------------------

class BackupRequest(BaseModel):
    path: str
    password: str


@app.post("/backup/create", dependencies=[Depends(require_token)])
def backup_create(body: BackupRequest) -> dict:
    return backup.create(body.path, body.password)


@app.post("/backup/restore", dependencies=[Depends(require_token)])
def backup_restore(body: BackupRequest) -> dict:
    return backup.restore(body.path, body.password)


@app.get("/backup/status", dependencies=[Depends(require_token)])
def backup_status() -> dict:
    return backup.status()


# --- v0.7: Learn mode --------------------------------------------------------

class ReviewRequest(BaseModel):
    card_id: int
    rating: int


@app.get("/learn/summary", dependencies=[Depends(require_token)])
def learn_summary() -> dict:
    return learn.summary()


@app.get("/learn/session", dependencies=[Depends(require_token)])
def learn_session(topic_id: int | None = None) -> dict:
    return learn.session(topic_id)


@app.post("/learn/review", dependencies=[Depends(require_token)])
def learn_review(body: ReviewRequest) -> dict:
    return learn.review(body.card_id, body.rating)


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


@app.get("/topics/map", dependencies=[Depends(require_token)])
def topics_map() -> dict:
    """Topics + links for the animated topic map."""
    return distill.topic_map()


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
