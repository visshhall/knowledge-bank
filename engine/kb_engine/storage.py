"""
storage.py — how much space the bank uses, and a safe clean-up (v0.9).

WHAT:  report() → sizes of everything in the data folder (the bank itself,
       its journal, meaning-vectors, page text, pictures' text, reports,
       copies kept aside by restores), what is inside (files, pages,
       passages, topics) and what a clean-up would free.
       cleanup() → frees space without touching anything you use:
         1. removes rows left behind by older versions (pictures of files
            that no longer exist, topic links to removed topics…),
         2. rebuilds the word-search index tightly (FTS5 'optimize'),
         3. VACUUM — SQLite rewrites the bank file without the empty space
            left by removed files and set-aside content,
         4. deletes old benchmark reports and the "before-restore" copies
            older than 30 days (the newest one is always kept).
       Your documents on disk are never touched.

WHY:   Owner chose "built to stay fast with a big library: show how much disk
       space the bank uses, with a clean-up button" (15 Nov 2026). SQLite
       never shrinks its file by itself, so after removing files or setting
       content aside the bank stays big until it is vacuumed.

WHEN:  GET /storage (Setup → Storage card), POST /storage/cleanup.
       VACUUM needs the bank to itself: the clean-up refuses while an
       import, topic build or writing job is running.

CONNECTED TO: db.py, config.py, importer/distill/writer (busy checks),
       App.jsx StorageCard.
"""

import sqlite3
import threading
import time
from pathlib import Path

from . import config, db

_state = {"state": "idle", "message": None, "freed_mb": None}
_lock = threading.Lock()
KEEP_DAYS = 30


def _mb(n: int) -> float:
    return round(n / 2**20, 1)


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _old_files() -> list[Path]:
    """Restore leftovers and reports older than KEEP_DAYS (newest restore copy kept)."""
    cutoff = time.time() - KEEP_DAYS * 86400
    restores = sorted(config.DATA_DIR.glob("before-restore-*.sqlite3"), key=lambda p: p.stat().st_mtime)
    old = [p for p in restores[:-1] if p.stat().st_mtime < cutoff]
    old += [Path(str(p) + s) for p in old for s in ("-wal", "-shm") if Path(str(p) + s).exists()]
    if config.REPORTS_DIR.exists():
        old += [p for p in config.REPORTS_DIR.iterdir() if p.is_file() and p.stat().st_mtime < cutoff]
    return old


def report() -> dict:
    dbp = config.DB_PATH
    files = {
        "bank": _size(dbp),
        "journal": _size(Path(str(dbp) + "-wal")) + _size(Path(str(dbp) + "-shm")),
        "restore_copies": sum(_size(p) for p in config.DATA_DIR.glob("before-restore-*")),
        "reports": sum(_size(p) for p in config.REPORTS_DIR.glob("*")) if config.REPORTS_DIR.exists() else 0,
    }
    with db.connect() as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
        counts = {
            "files": conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'extracted'").fetchone()[0],
            "set_aside": conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'set_aside'").fetchone()[0],
            "pages": conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
            "passages": conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0],
            "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        }
        parts = {
            "page_text": conn.execute("SELECT COALESCE(SUM(length(text)), 0) FROM pages").fetchone()[0],
            "passages": conn.execute("SELECT COALESCE(SUM(length(text)), 0) FROM passages").fetchone()[0],
            "meaning_vectors": conn.execute("SELECT COALESCE(SUM(length(embedding)), 0) FROM passages").fetchone()[0],
            "articles": conn.execute("SELECT COALESCE(SUM(length(body_markdown)), 0) FROM topics").fetchone()[0],
        }
    old = _old_files()
    reclaim = free_pages * page_size + files["journal"] + sum(_size(p) for p in old)
    with _lock:
        job = dict(_state)
    return {
        "folder": str(config.DATA_DIR),
        "total_mb": _mb(sum(files.values())),
        "files_mb": {k: _mb(v) for k, v in files.items()},
        "parts_mb": {k: _mb(v) for k, v in parts.items()},
        "counts": counts,
        "reclaimable_mb": _mb(reclaim),
        "job": job,
    }


def _busy() -> str | None:
    from . import distill, importer, writer
    if importer.status().get("state") == "running":
        return "Files are being imported"
    if distill.status().get("state") == "running":
        return "Topics are being built"
    if writer.status().get("state") == "running":
        return "Articles are being written"
    return None


def _run() -> None:
    before = sum(_size(p) for p in [config.DB_PATH, Path(str(config.DB_PATH) + "-wal")])
    old = _old_files()
    try:
        with db.connect() as conn:
            _set(message="Removing leftovers…")
            conn.execute("DELETE FROM images WHERE source_id NOT IN (SELECT id FROM sources)")
            conn.execute("DELETE FROM topic_links WHERE from_topic_id NOT IN (SELECT id FROM topics) "
                         "OR to_topic_id NOT IN (SELECT id FROM topics)")
            conn.execute("DELETE FROM topic_passages WHERE passage_id NOT IN (SELECT id FROM passages)")
            conn.execute("DELETE FROM lessons WHERE topic_id NOT IN (SELECT id FROM topics)")
            _set(message="Tightening the word-search index…")
            conn.execute("INSERT INTO passages_fts(passages_fts) VALUES('optimize')")
        _set(message="Compacting the bank (can take a minute for a big bank)…")
        raw = sqlite3.connect(config.DB_PATH, isolation_level=None, timeout=60)
        try:
            raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            raw.execute("VACUUM")
            raw.execute("PRAGMA optimize")
        finally:
            raw.close()
        for p in old:
            try:
                p.unlink()
            except OSError:
                pass
        after = sum(_size(p) for p in [config.DB_PATH, Path(str(config.DB_PATH) + "-wal")])
        freed = before - after + sum(_size(p) for p in old)
        _set(state="done", message=f"Clean-up finished — {_mb(max(freed, 0))} MB freed.", freed_mb=_mb(max(freed, 0)))
    except Exception as exc:
        _set(state="error", message=f"Clean-up stopped: {exc}. Nothing was lost; try again later.")


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def start_cleanup() -> dict:
    reason = _busy()
    if reason:
        return {"ok": False, "message": f"{reason} — try the clean-up when it has finished."}
    with _lock:
        if _state["state"] == "running":
            return {"ok": False, "message": "Already cleaning up."}
        _state.update(state="running", message="Starting…", freed_mb=None)
    threading.Thread(target=_run, name="kb-cleanup", daemon=True).start()
    return {"ok": True, "message": "Cleaning up…"}
