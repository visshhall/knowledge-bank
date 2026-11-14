"""
importer.py — Phase 1: brings PDFs and images into the knowledge bank.

WHAT:  1. add_paths(): accepts files and/or folders (folders are searched
          recursively), fingerprints each file (SHA-256) and either
          registers it as a new source or records it as an exact duplicate
          of a file already in the bank.
       2. A single background worker then extracts every pending source:
            PDF  → page by page: text layer; if a page has almost no text it
                   is rendered and OCR'd (scanned page); pictures embedded in
                   the page are OCR'd too (diagram/screenshot labels).
            Image→ OCR'd as a one-page source.
          Each page's text is cut into passages (chunking.py) and stored
          with its file and page number, so everything stays citable.
       3. Watched folders: every few minutes, new files appearing in the
          owner's chosen folders are imported automatically.
       4. remove_source(): takes a file out of the bank (its pages,
          passages and images go with it). The original file is untouched.

WHY:   Import is the foundation of everything else: distilling (Phase 2),
       topic writing (Phase 3) and search all work on the passages created
       here. Design choices:
         - Page-by-page processing → a 2,000-page PDF never loads into
           memory at once and progress shows per page.
         - One page = one database transaction → closing the app mid-import
           loses at most one page of work; on next start, any half-done file
           is cleanly restarted (resume_interrupted()).
         - Originals are only READ, never modified, moved or copied.
         - Fingerprinting the bytes means a renamed copy is still detected.

WHEN:  - add_paths(): when the owner adds files/folders (server.py →
         POST /library/add) and from the watched-folder scanner.
       - start(): once at engine startup — resumes interrupted work and
         starts the watched-folder scanner.

CONNECTED TO: db.py (sources, pages, passages, images, duplicate_files,
       settings), chunking.py, ocr.py, server.py (/library/*, /import/*,
       /settings/watch), app/src/Library.jsx (the owner's screen).
"""

import hashlib
import os
import threading
import time
from pathlib import Path

import pymupdf

from . import chunking, db, ocr

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS

# A PDF page with fewer characters than this is treated as scanned → OCR.
SCANNED_PAGE_CHAR_THRESHOLD = 40

# Pages are rendered at this resolution for OCR. 200 dpi reads small print
# reliably without making OCR slow.
OCR_RENDER_DPI = 200

# Embedded pictures smaller than this (in either dimension) are skipped —
# they're bullets, logos and icons, not diagrams.
MIN_EMBEDDED_IMAGE_PX = 160

# OCR'd text from an embedded picture is only kept if it has at least this
# many words (filters out stray letters read from photos/logos).
MIN_IMAGE_WORDS = 4

# How often watched folders are checked for new files (seconds).
WATCH_INTERVAL_SECONDS = 180

# ---------------------------------------------------------------------------
# Live progress, read by the window via GET /import/status
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_worker_running = False
_progress = {
    "state": "idle",          # idle | running
    "current_file": None,     # name of the file being processed
    "current_page": 0,
    "page_count": 0,
    "files_done": 0,          # finished in this run
    "files_queued": 0,        # still waiting (including the current one)
    "last_error": None,
    "last_scan": None,        # time of the last watched-folder scan
}


def _set(**changes) -> None:
    """Thread-safe update of the progress dict."""
    with _lock:
        _progress.update(changes)


def status() -> dict:
    """
    Snapshot of import progress (polled by the window ~every 1.5 s).
    Includes ocr_error if the OCR engine has failed (see ocr.py).
    """
    with _lock:
        snapshot = dict(_progress)
    snapshot["ocr_error"] = ocr.last_error
    return snapshot


# ---------------------------------------------------------------------------
# Adding files
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Fingerprint a file by streaming it in 1 MB blocks (any size, low memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _expand(paths: list[str]) -> tuple[list[Path], int]:
    """
    Turn the owner's selection into a flat list of supported files.
    Folders are walked recursively. RETURNS (files, unsupported_count).
    """
    files: list[Path] = []
    unsupported = 0
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for root, _dirs, names in os.walk(p):
                for name in names:
                    fp = Path(root) / name
                    if fp.suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(fp)
                    elif not name.startswith("."):
                        unsupported += 1
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(p)
            else:
                unsupported += 1
    return files, unsupported


def _already_known(conn, path: Path, size: int) -> bool:
    """
    Cheap check before fingerprinting: is this exact path (with the same
    size) already a source or a recorded duplicate? Saves re-hashing
    gigabytes on every watched-folder scan.
    """
    sp = str(path)
    if conn.execute("SELECT 1 FROM sources WHERE original_path = ? AND size_bytes = ?",
                    (sp, size)).fetchone():
        return True
    return bool(conn.execute("SELECT 1 FROM duplicate_files WHERE path = ? AND size_bytes = ?",
                             (sp, size)).fetchone())


def add_paths(paths: list[str]) -> dict:
    """
    Register files/folders for import, then make sure the worker is running.

    RETURNS: {"added": n, "duplicates": n, "already_in_bank": n,
              "unsupported": n, "errors": [..]}
      added            new sources queued for extraction
      duplicates       exact copies (different path, same bytes) of a file
                       already in the bank — recorded, not imported twice
      already_in_bank  the very same file path was added before
      unsupported      files that aren't PDFs or images (ignored)
    """
    files, unsupported = _expand(paths)
    result = {"added": 0, "duplicates": 0, "already_in_bank": 0,
              "unsupported": unsupported, "errors": []}

    for fp in files:
        try:
            size = fp.stat().st_size
            with db.connect() as conn:
                if _already_known(conn, fp, size):
                    result["already_in_bank"] += 1
                    continue
            sha = _sha256_file(fp)  # outside the DB transaction: can take a while
            with db.connect() as conn:
                existing = conn.execute("SELECT id FROM sources WHERE sha256 = ?", (sha,)).fetchone()
                if existing:
                    conn.execute(
                        "INSERT OR REPLACE INTO duplicate_files(path, sha256, source_id, size_bytes) "
                        "VALUES (?, ?, ?, ?)",
                        (str(fp), sha, existing["id"], size),
                    )
                    result["duplicates"] += 1
                    continue
                conn.execute(
                    "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sha, fp.name, str(fp),
                     "pdf" if fp.suffix.lower() in PDF_EXTENSIONS else "image", size),
                )
                result["added"] += 1
        except OSError as exc:
            result["errors"].append(f"{fp.name}: {exc.strerror or exc}")

    if result["added"]:
        _ensure_worker()
    return result


def remove_source(source_id: int) -> dict:
    """
    Remove one file from the bank. Its pages, passages, images and duplicate
    records are deleted automatically (database cascade). The original file
    on disk is NOT touched. A file being extracted right now can't be
    removed until it finishes (avoids a half-deleted state).
    """
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "Not found."}
        if row["status"] == "extracting":
            return {"ok": False, "message": "This file is being imported right now — try again in a moment."}
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return {"ok": True, "message": "Removed from the knowledge bank. The original file is untouched."}


def retry_failed() -> dict:
    """Put every failed source back in the queue (e.g. after closing the PDF in another program)."""
    with db.connect() as conn:
        n = conn.execute(
            "UPDATE sources SET status = 'pending', error = NULL WHERE status = 'failed'"
        ).rowcount
    if n:
        _ensure_worker()
    return {"ok": True, "message": f"{n} file(s) queued again."}


def library(limit: int = 2000) -> list[dict]:
    """
    List sources for the Library screen, newest first, with per-file counts
    (pages, passages, OCR'd pages, embedded images, duplicate copies found).
    """
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.file_name, s.original_path, s.file_type, s.size_bytes,
                   s.page_count, s.status, s.error, s.added_at, s.processed_at,
                   (SELECT COUNT(*) FROM passages p WHERE p.source_id = s.id)          AS passages,
                   (SELECT COUNT(*) FROM pages g WHERE g.source_id = s.id AND g.ocr_used = 1) AS ocr_pages,
                   (SELECT COUNT(*) FROM images i WHERE i.source_id = s.id)            AS images,
                   (SELECT COUNT(*) FROM duplicate_files d WHERE d.source_id = s.id)   AS duplicate_copies
            FROM sources s ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Extraction worker
# ---------------------------------------------------------------------------

def _ensure_worker() -> None:
    """Start the extraction thread if it isn't already running."""
    global _worker_running
    with _lock:
        if _worker_running:
            return
        _worker_running = True
    threading.Thread(target=_worker, name="kb-import", daemon=True).start()


def _next_pending():
    """The oldest source still waiting, plus how many are waiting in total."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM sources WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()
        queued = conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'pending'").fetchone()[0]
    return (dict(row) if row else None), int(queued)


def _worker() -> None:
    """
    Background loop: process pending sources one at a time until none are
    left. One file at a time keeps memory use predictable and lets each
    file show page-by-page progress.
    """
    global _worker_running
    _set(state="running", files_done=0, last_error=None)
    try:
        while True:
            source, queued = _next_pending()
            if not source:
                break
            _set(current_file=source["file_name"], current_page=0, page_count=0,
                 files_queued=queued)
            _process_source(source)
            with _lock:
                _progress["files_done"] += 1
    finally:
        with _lock:
            _worker_running = False
            _progress.update(state="idle", current_file=None, current_page=0,
                             page_count=0, files_queued=0)
        # Race guard: a file added in the instant between "nothing pending"
        # and this thread stopping would otherwise wait for the next add.
        if _next_pending()[0]:
            _ensure_worker()


def _process_source(source: dict) -> None:
    """Extract one source; mark it extracted or failed (with a readable reason)."""
    sid = source["id"]
    with db.connect() as conn:
        conn.execute("UPDATE sources SET status = 'extracting', error = NULL WHERE id = ?", (sid,))
        conn.execute("DELETE FROM pages WHERE source_id = ?", (sid,))   # clear any partial run
        conn.execute("DELETE FROM images WHERE source_id = ?", (sid,))
    try:
        path = Path(source["original_path"])
        if not path.exists():
            raise FileNotFoundError("The original file was moved or deleted. Add it again from its new location.")
        if source["file_type"] == "pdf":
            page_count = _extract_pdf(sid, path)
        else:
            page_count = _extract_image(sid, path)
        with db.connect() as conn:
            conn.execute(
                "UPDATE sources SET status = 'extracted', page_count = ?, "
                "processed_at = datetime('now') WHERE id = ?",
                (page_count, sid),
            )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        _set(last_error=f"{source['file_name']}: {message}")
        with db.connect() as conn:
            conn.execute("UPDATE sources SET status = 'failed', error = ? WHERE id = ?",
                         (message, sid))


def _store_page(sid: int, page_number: int, text: str, ocr_used: bool,
                image_records: list[dict]) -> None:
    """
    Save one page (text + passages + embedded-image records) in a single
    transaction, so a crash can never leave a page half-stored.
    image_records: [{"sha256", "ocr_text"}] for pictures found on this page.
    """
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO pages(source_id, page_number, text, ocr_used, char_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, page_number, text, int(ocr_used), len(text)),
        )
        page_id = cur.lastrowid
        ordinal = 0
        for passage in chunking.split_passages(text):
            conn.execute(
                "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                "token_count, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, page_id, page_number, ordinal, passage,
                 chunking.approx_tokens(passage), chunking.fingerprint(passage)),
            )
            ordinal += 1
        for img in image_records:
            conn.execute(
                "INSERT INTO images(source_id, page_number, sha256, ocr_text) VALUES (?, ?, ?, ?)",
                (sid, page_number, img["sha256"], img["ocr_text"]),
            )
            # Text read from a diagram becomes its own passage so it is
            # searchable and citable like any other text on the page.
            if len(img["ocr_text"].split()) >= MIN_IMAGE_WORDS:
                for passage in chunking.split_passages(img["ocr_text"]):
                    labelled = f"[Image on page {page_number}] {passage}"
                    conn.execute(
                        "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                        "token_count, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (sid, page_id, page_number, ordinal, labelled,
                         chunking.approx_tokens(labelled), chunking.fingerprint(passage)),
                    )
                    ordinal += 1


def _known_image_text(sha: str) -> str | None:
    """
    If this exact picture was already OCR'd (same bytes in any file), reuse
    its text instead of OCR'ing it again — common for repeated diagrams.
    """
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ocr_text FROM images WHERE sha256 = ? AND ocr_text IS NOT NULL LIMIT 1", (sha,)
        ).fetchone()
    return row["ocr_text"] if row else None


def _embedded_images(doc, page) -> list[dict]:
    """
    OCR the meaningful pictures on a PDF page (diagrams, screenshots).
    The same picture repeated on one page (e.g. a logo) is handled once.
    """
    records: list[dict] = []
    seen: set[int] = set()
    for info in page.get_images(full=True):
        xref = info[0]
        if xref in seen:
            continue
        seen.add(xref)
        try:
            extracted = doc.extract_image(xref)
        except Exception:
            continue  # unusual image encodings — skip rather than fail the page
        if not extracted or min(extracted.get("width", 0), extracted.get("height", 0)) < MIN_EMBEDDED_IMAGE_PX:
            continue
        data = extracted["image"]
        sha = hashlib.sha256(data).hexdigest()
        text = _known_image_text(sha)
        if text is None:
            text = ocr.read_text(data)
        records.append({"sha256": sha, "ocr_text": text})
    return records


def _extract_pdf(sid: int, path: Path) -> int:
    """
    Extract a PDF page by page. RETURNS the page count.
    RAISES a readable error for password-protected or unreadable PDFs.
    """
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"Not a readable PDF ({exc}).") from exc
    with doc:
        if doc.needs_pass:
            raise PermissionError("This PDF is password-protected. Remove the password and add it again.")
        total = doc.page_count
        _set(page_count=total)
        for index, page in enumerate(doc):
            _set(current_page=index + 1)
            text = page.get_text("text")
            ocr_used = False
            images: list[dict] = []
            if len(text.strip()) < SCANNED_PAGE_CHAR_THRESHOLD:
                # Scanned page: read the whole rendered page instead.
                pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
                text = ocr.read_text(pix.tobytes("png"))
                ocr_used = True
            else:
                images = _embedded_images(doc, page)
            _store_page(sid, index + 1, text, ocr_used, images)
        return total


def _extract_image(sid: int, path: Path) -> int:
    """OCR a standalone image as a one-page source. RETURNS 1."""
    _set(page_count=1, current_page=1)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    text = ocr.read_text(data)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO images(source_id, page_number, sha256, ocr_text) VALUES (?, 1, ?, ?)",
            (sid, sha, text),
        )
    _store_page(sid, 1, text, True, [])
    return 1


# ---------------------------------------------------------------------------
# Watched folders
# ---------------------------------------------------------------------------

def watch_folders() -> list[str]:
    """The folders the owner asked to watch (saved in settings)."""
    return db.get_setting("watch_folders", [])


def set_watch_folders(folders: list[str]) -> dict:
    """
    Replace the watched-folder list. Folders that don't exist are rejected
    with a message rather than saved. An immediate scan follows, so files
    already in a newly watched folder are imported straight away.
    """
    valid = [str(Path(f)) for f in folders if Path(f).is_dir()]
    rejected = [f for f in folders if not Path(f).is_dir()]
    db.set_setting("watch_folders", sorted(set(valid)))
    threading.Thread(target=scan_watched_folders, daemon=True).start()
    message = "Saved." if not rejected else f"Saved. Not found, ignored: {', '.join(rejected)}"
    return {"ok": True, "folders": sorted(set(valid)), "message": message}


def scan_watched_folders() -> dict:
    """Import any new files found in watched folders (known files are skipped cheaply)."""
    folders = [f for f in watch_folders() if Path(f).is_dir()]
    result = add_paths(folders) if folders else {"added": 0}
    _set(last_scan=time.strftime("%Y-%m-%d %H:%M:%S"))
    return result


def _watch_loop() -> None:
    """Background loop: scan watched folders every WATCH_INTERVAL_SECONDS."""
    while True:
        try:
            scan_watched_folders()
        except Exception as exc:  # never let the watcher die silently
            _set(last_error=f"Watched-folder scan: {exc}")
        time.sleep(WATCH_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def resume_interrupted() -> int:
    """
    A file left in 'extracting' means the app was closed mid-import.
    Put it back to 'pending' (its partial pages are cleared when it restarts).
    RETURNS how many files were resumed.
    """
    with db.connect() as conn:
        return conn.execute(
            "UPDATE sources SET status = 'pending' WHERE status = 'extracting'"
        ).rowcount


def start() -> None:
    """
    Called once when the engine starts (server.py lifespan): resume any
    interrupted import, process anything still pending, and start the
    watched-folder scanner.
    """
    resume_interrupted()
    _ensure_worker()
    threading.Thread(target=_watch_loop, name="kb-watch", daemon=True).start()
