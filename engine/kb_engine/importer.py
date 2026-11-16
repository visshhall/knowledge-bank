"""
importer.py — Phase 1: brings PDFs and images into the knowledge bank.

WHAT:  1. add_paths(): accepts files and/or folders (folders are searched
          recursively), fingerprints each file (SHA-256) and either
          registers it as a new source or records it as an exact duplicate
          of a file already in the bank.
       2. A single background worker then extracts every pending source:
            Sheet→ Excel (.xlsx/.xlsm) or CSV: each sheet is one "page"; the
                   exact grid is kept (doc_tables) plus a readable text form.
            PDF  → page by page: text layer; if a page has almost no text it
                   is rendered and OCR'd (scanned page); pictures embedded in
                   the page are OCR'd too (diagram/screenshot labels) — since
                   v0.8.1 in a SECOND pass after all files' text is in, so
                   files are usable in seconds (_worker, _picture_step).
            Image→ OCR'd as a one-page source.
          Each page's text is cut into passages (chunking.py) and stored
          with its file and page number, so everything stays citable.
       3. Watched folders: every few minutes, new files appearing in the
          owner's chosen folders are imported automatically.
       4. remove_source(): takes a file out of the bank (its pages,
          passages and images go with it). The original file is untouched.
       6. reread_all(): when the way files are READ changes (EXTRACT_VERSION,
          v0.6.2: tables kept, OCR rows rebuilt), re-reads every original
          file still in place; others are re-organised from stored text.
       5. rechunk_all(): when the passage rules change (CHUNKER_VERSION in
          chunking.py), rebuilds every passage from the page text already
          stored — no PDF is read again.

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
import json
import re
import os
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import time
from pathlib import Path

import pymupdf

from . import chunking, cleaning, db, ocr, relevance, titles

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TABLE_EXTENSIONS = {".xlsx", ".xlsm", ".csv"}   # spreadsheets (v0.6)
# v0.9: Word, PowerPoint, saved web pages, text and Markdown (officefiles.py)
DOC_EXTENSIONS = {".docx", ".pptx", ".html", ".htm", ".txt", ".md", ".markdown"}
SUPPORTED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | TABLE_EXTENSIONS | DOC_EXTENSIONS

# Spreadsheet safety limits: a sheet bigger than this is cut (with a note),
# so one giant export can't stall the import or flood the bank.
MAX_SHEET_ROWS = 5000
MAX_SHEET_COLS = 60

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
    # v0.8.1: pictures inside text pages are read in a second pass
    "phase": None,            # "text" (files) | "pictures" (diagrams inside them)
    "pictures_left": 0,       # pictures still waiting to be read, all files
    "pictures_done": 0,       # read in this run
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
    snapshot["ocr_device"] = ocr.device  # "graphics card" / "processor" (v0.8.1)
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


def _file_type(path: Path) -> str:
    """'pdf', 'table' (Excel/CSV) or 'image', from the file extension."""
    ext = path.suffix.lower()
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in TABLE_EXTENSIONS:
        return "table"
    if ext in DOC_EXTENSIONS:
        return "doc"
    return "image"


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


def _removed_before(conn, path: Path, size: int, sha: str | None = None) -> bool:
    """Did the owner remove this file (same path+size, or same bytes)?"""
    if conn.execute("SELECT 1 FROM removed_files WHERE path = ? AND size_bytes = ?",
                    (str(path), size)).fetchone():
        return True
    return bool(sha and conn.execute("SELECT 1 FROM removed_files WHERE sha256 = ?", (sha,)).fetchone())


def add_paths(paths: list[str], picked: bool = False, urls: dict | None = None,
              names: dict | None = None, keep: bool = False) -> dict:
    """
    Register files/folders for import, then make sure the worker is running.

    RETURNS: {"added": n, "duplicates": n, "already_in_bank": n,
              "unsupported": n, "errors": [..]}
      added            new sources queued for extraction
      duplicates       exact copies (different path, same bytes) of a file
                       already in the bank — recorded, not imported twice
      already_in_bank  the very same file path was added before
      unsupported      files that aren't PDFs or images (ignored)
      removed_before   files the owner removed earlier (v0.8.2) — skipped

    picked (v0.8.2): True when the owner chose these paths in the window.
      A removed file comes back ONLY if the owner picked that exact file
      (Add files / drag-and-drop of the file itself). Watched-folder scans
      and folder adds always skip removed files — this is what stops
      "files I removed keep coming back".

    v0.13 (used by crawler.py and add_text):
      urls   {path: web address} — stored in sources.url for pages copied from the web.
      names  {path: readable name} — shown instead of the copy's file name.
      keep   True = the owner asked for this content himself, so the "is it about
             cybersecurity?" check is skipped (that check is for files dropped in bulk).
    """
    files, unsupported = _expand(paths)
    direct = {str(Path(p)) for p in paths if picked and Path(p).is_file()}
    result = {"added": 0, "duplicates": 0, "already_in_bank": 0,
              "unsupported": unsupported, "removed_before": 0, "errors": []}

    for fp in files:
        try:
            size = fp.stat().st_size
            chosen = str(fp) in direct
            with db.connect() as conn:
                if _already_known(conn, fp, size):
                    result["already_in_bank"] += 1
                    continue
                if not chosen and _removed_before(conn, fp, size):
                    result["removed_before"] += 1
                    continue
            sha = _sha256_file(fp)  # outside the DB transaction: can take a while
            with db.connect() as conn:
                if chosen:
                    conn.execute("DELETE FROM removed_files WHERE sha256 = ? OR path = ?", (sha, str(fp)))
                elif _removed_before(conn, fp, size, sha):
                    result["removed_before"] += 1  # a renamed/moved copy of a removed file
                    continue
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
                    "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, url, keep_anyway) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sha, (names or {}).get(str(fp)) or fp.name, str(fp), _file_type(fp), size,
                     (urls or {}).get(str(fp)), 1 if keep else 0),
                )
                result["added"] += 1
        except OSError as exc:
            result["errors"].append(f"{fp.name}: {exc.strerror or exc}")

    if result["added"]:
        _ensure_worker()
    return result


def add_text(title: str, text: str) -> dict:
    """
    v0.13: put pasted text into the bank (notes, an email, a product description, anything).
    The text is saved as a Markdown copy in the data folder (…/notes/) and imported like a file,
    with the title as its first line. RETURNS the add_paths result plus {"ok"} or {"ok": False, "message"}.
    The cybersecurity check is skipped: he pasted it himself.
    """
    text = (text or "").strip()
    title = " ".join((title or "").split())[:120]
    if len(text) < 20:
        return {"ok": False, "message": "Paste some text first (at least a sentence)."}
    if len(text) > 2_000_000:
        return {"ok": False, "message": "That is too long to paste. Save it as a file and add the file instead."}
    from . import config
    title = title or " ".join(text.split())[:60]
    folder = config.DATA_DIR / "notes"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "note"
    path = folder / f"{slug}-{hashlib.sha256(text.encode()).hexdigest()[:8]}.md"
    path.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    r = add_paths([str(path)], picked=True, names={str(path): title}, keep=True)
    r["ok"] = True
    if not r["added"]:
        r["message"] = "That text is already in the bank." if (r["duplicates"] or r["already_in_bank"]) else "Nothing was added."
    return r


def _own_copy(path: str) -> bool:
    """True for a copy the app itself made (web pages, pasted notes) — those are deleted with their source."""
    from . import config
    try:
        p = Path(path).resolve()
        return any(p.is_relative_to((config.DATA_DIR / d).resolve()) for d in ("web", "notes"))
    except (OSError, ValueError):
        return False


def _clean_up_after_removal(conn, source_ids: list[int], touched_topics: set[int]) -> dict:
    """
    v0.9.2: take every trace of removed files out of what was built from them.
    WHY: deleting a file's pages/passages (database cascade) left its content
    alive in topics, written articles, lessons, flashcards and saved answers,
    so "removed" PDFs still showed up. HOW:
      - a topic with no passages left is deleted (its cards keep their review
        history but lose the topic link — db.py cards.topic_id ON DELETE SET NULL);
      - a topic that lost some passages gets its article, summary, citations
        and lesson cleared and is marked 'stale' — it no longer shows the
        removed text, and "Write remaining" writes it again from what is left;
      - flashcards made from a removed passage are deleted;
      - saved answers that cited a removed file are deleted.
    RETURNS counts for the message shown to the owner.
    """
    gone_topics = changed_topics = 0
    for t in touched_topics:
        if not conn.execute("SELECT 1 FROM topics WHERE id = ?", (t,)).fetchone():
            continue
        left = conn.execute("SELECT COUNT(*) FROM topic_passages WHERE topic_id = ?", (t,)).fetchone()[0]
        if left == 0:
            conn.execute("DELETE FROM topics WHERE id = ?", (t,))
            gone_topics += 1
        else:
            conn.execute(
                "UPDATE topics SET status = 'stale', body_markdown = NULL, summary = NULL, citations = NULL, "
                "updated_at = datetime('now') WHERE id = ? AND kind != 'data'", (t,))
            conn.execute("DELETE FROM lessons WHERE topic_id = ?", (t,))
            changed_topics += 1
    cards = conn.execute(
        "DELETE FROM cards WHERE point_id IS NOT NULL AND point_id NOT IN (SELECT id FROM passages)").rowcount
    answers = 0
    removed_ids = {int(x) for x in source_ids}
    for r in conn.execute("SELECT id, sources_json FROM answers").fetchall():
        # A saved answer keeps its sources as {"1": {..., "source_id": 7}, "2": {...}}
        # (answers.py). v0.9.2 iterated that dict as if it were a list, so it never
        # matched and no answer was ever deleted; v0.11 reads the values.
        if removed_ids & _cited_source_ids(r["sources_json"]):
            conn.execute("DELETE FROM answers WHERE id = ?", (r["id"],))
            answers += 1
    # v0.11: saved chats keep their conversation, but an answer that quoted a
    # removed file is cleared so none of that file's text remains anywhere.
    from . import chat
    chats = chat.forget_sources(conn, removed_ids)
    return {"topics_removed": gone_topics, "topics_cleared": changed_topics, "cards": cards,
            "answers": answers, "chat_answers": chats}


def _cited_source_ids(sources_json: str | None) -> set[int]:
    """
    Source-file ids named in a saved answer's or chat message's `sources_json`.

    Accepts both shapes: a dict of numbered entries (what answers.py and
    chat.py save) and a plain list of entries. Anything unreadable gives an
    empty set, so a damaged row is never mistaken for a match.
    """
    try:
        data = json.loads(sources_json or "{}")
    except (TypeError, ValueError):
        return set()
    entries = data.values() if isinstance(data, dict) else data
    found = set()
    for x in entries:
        if isinstance(x, dict) and x.get("source_id") is not None:
            try:
                found.add(int(x["source_id"]))
            except (TypeError, ValueError):
                pass
    return found


def remove_sources(source_ids: list[int]) -> dict:
    """
    Remove one or many files from the bank, together with everything built
    from them (see _clean_up_after_removal). The original files on disk are
    NOT touched. A file being extracted right now is skipped (try again in a
    moment). Each removed file is remembered so watched folders and folder
    adds never bring it back; "Add files" on that exact file undoes this.
    """
    removed, busy = [], 0
    touched: set[int] = set()
    copies: list[str] = []  # the app's own copies (web pages, notes) — deleted so no text is left behind
    with db.connect() as conn:
        for sid in dict.fromkeys(source_ids):
            row = conn.execute("SELECT status FROM sources WHERE id = ?", (sid,)).fetchone()
            if not row:
                continue
            if row["status"] == "extracting":
                busy += 1
                continue
            touched.update(r[0] for r in conn.execute(
                "SELECT DISTINCT tp.topic_id FROM topic_passages tp JOIN passages p ON p.id = tp.passage_id "
                "WHERE p.source_id = ?", (sid,)))
            own = conn.execute("SELECT original_path FROM sources WHERE id = ?", (sid,)).fetchone()
            if own and _own_copy(own["original_path"]):
                copies.append(own["original_path"])
            conn.execute(
                "INSERT OR REPLACE INTO removed_files(sha256, path, size_bytes) "
                "SELECT sha256, original_path, size_bytes FROM sources WHERE id = ?", (sid,))
            conn.execute(
                "INSERT OR REPLACE INTO removed_files(sha256, path, size_bytes) "
                "SELECT sha256, path, size_bytes FROM duplicate_files WHERE source_id = ?", (sid,))
            conn.execute("DELETE FROM sources WHERE id = ?", (sid,))
            removed.append(sid)
        cleaned = _clean_up_after_removal(conn, removed, touched) if removed else {}
    for c in copies:
        try:
            Path(c).unlink()
        except OSError:
            pass
    try:
        from . import datapages
        datapages.rebuild_data_topics()  # a removed spreadsheet takes its data topic with it
    except Exception:
        pass
    if not removed:
        return {"ok": False, "removed": 0,
                "message": "Those files are being imported right now — try again in a moment." if busy else "Not found."}
    parts = [f"Removed {len(removed)} file{'s' if len(removed) != 1 else ''} and their content."]
    if cleaned.get("topics_removed"):
        parts.append(f"{cleaned['topics_removed']} topic{'s' if cleaned['topics_removed'] != 1 else ''} that only came from them "
                     f"{'were' if cleaned['topics_removed'] != 1 else 'was'} deleted.")
    if cleaned.get("topics_cleared"):
        parts.append(f"{cleaned['topics_cleared']} topic{'s' if cleaned['topics_cleared'] != 1 else ''} lost part of their content — "
                     f"press Write remaining to write {'them' if cleaned['topics_cleared'] != 1 else 'it'} again.")
    if busy:
        parts.append(f"{busy} still importing, not removed.")
    parts.append("They won't be imported again; the original files are untouched.")
    return {"ok": True, "removed": len(removed), "busy": busy, **cleaned, "message": " ".join(parts)}


def remove_source(source_id: int) -> dict:
    """One file — see remove_sources()."""
    return remove_sources([source_id])


def keep_anyway(source_id: int) -> dict:
    """
    v0.8.2: the owner overrides the relevance check for one set-aside file.
    It is queued again and imported in full, without being checked.
    """
    with db.connect() as conn:
        n = conn.execute("UPDATE sources SET keep_anyway = 1, status = 'pending', error = NULL "
                         "WHERE id = ? AND status = 'set_aside'", (source_id,)).rowcount
    if n:
        _ensure_worker()
    return {"ok": bool(n), "message": "Importing it in full." if n else "Not found."}


def _retire(conn, sid: int) -> None:
    """
    Take an already-imported file's content out of the bank but keep its row
    as 'set_aside' (v0.8.2). Topics that lose passages are marked 'stale'
    (Write remaining refreshes them); topics left empty are deleted.
    """
    touched = [r[0] for r in conn.execute(
        "SELECT DISTINCT tp.topic_id FROM topic_passages tp JOIN passages p ON p.id = tp.passage_id "
        "WHERE p.source_id = ?", (sid,))]
    conn.execute("DELETE FROM pages WHERE source_id = ?", (sid,))
    conn.execute("DELETE FROM images WHERE source_id = ?", (sid,))
    conn.execute("DELETE FROM doc_tables WHERE source_id = ?", (sid,))
    conn.execute("UPDATE sources SET status = 'set_aside' WHERE id = ?", (sid,))
    # v0.9.2: same clean-up as a removal, so a set-aside/replaced file leaves no text in articles
    _clean_up_after_removal(conn, [sid], set(touched))


def _name_key(name: str) -> str:
    """'RDP Guide v2 (final).pdf' → 'rdp guide' — for comparing versions."""
    stem = Path(name).stem.lower()
    stem = re.sub(r"\b(v|ver|version|rev)\s*\d+(\.\d+)*\b|\b(final|draft|copy|updated|new|latest|old)\b", " ", stem)
    stem = re.sub(r"\(\d+\)|\b\d{1,4}([-_.]\d{1,2}){0,2}\b|[^a-z]+", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def _replace_older(sid: int) -> bool:
    """
    v0.9: after a file is read, check whether it is a NEWER VERSION of a
    file already in the bank (see OLD_SHARE_*). If so:
      1. the old file is retired (status 'set_aside', reason "older version —
         replaced by <new>", replaced_by = new id; Keep anyway restores it),
      2. the new file is queued to be read again, now in full: its paragraphs
         that were skipped as "already in the bank" belonged to the old file,
         so they must be stored in the new one before the old one goes.
    RETURNS True when the new file was re-queued.
    """
    matches = _last_matches.pop(sid, {})
    if not matches or not dedupe_on():
        return False
    import difflib
    with db.connect() as conn:
        me = conn.execute("SELECT file_name, title FROM sources WHERE id = ?", (sid,)).fetchone()
        for old_id, shared in sorted(matches.items(), key=lambda kv: -kv[1]):
            old = conn.execute("SELECT file_name, title, status, keep_anyway FROM sources WHERE id = ?",
                               (old_id,)).fetchone()
            if not old or old["status"] != "extracted" or old["keep_anyway"]:
                continue
            real = conn.execute("SELECT COUNT(*) FROM passages WHERE source_id = ? AND "
                                "length(text) - length(replace(text, ' ', '')) >= ?",
                                (old_id, MIN_REPEAT_WORDS - 1)).fetchone()[0]
            if not real:
                continue
            share = shared / real
            a = _name_key(me["title"] or me["file_name"])
            b = _name_key(old["title"] or old["file_name"])
            alike = bool(a and b and (a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75))
            if share >= (OLD_SHARE_SAME_NAME if alike else OLD_SHARE_ANY_NAME):
                info = {"verdict": "replaced", "replaced_by": sid,
                        "reason": f"older version — replaced by {me['title'] or me['file_name']} "
                                  f"({round(share * 100)}% of its content is in the newer file)"}
                conn.execute("UPDATE sources SET relevance_json = ?, replaced_by = ? WHERE id = ?",
                             (json.dumps(info), sid, old_id))
                _retire(conn, old_id)
                conn.execute("UPDATE sources SET status = 'pending' WHERE id = ?", (sid,))
                return True
    return False


def _name_and_tag(sid: int) -> None:
    """
    v0.9: give a file with an unhelpful name ("1733744110377.pdf") a title
    read from its content, and tag every file with up to 2 categories.
    Display only: the file on disk is never renamed. Never fails an import.
    """
    try:
        with db.connect() as conn:
            src = conn.execute("SELECT file_name, original_path, file_type FROM sources WHERE id = ?",
                               (sid,)).fetchone()
            first = conn.execute("SELECT section FROM passages WHERE source_id = ? AND section IS NOT NULL "
                                 "ORDER BY page_number, ordinal LIMIT 1", (sid,)).fetchone()
            page1 = conn.execute("SELECT text FROM pages WHERE source_id = ? ORDER BY page_number LIMIT 1",
                                 (sid,)).fetchone()
            sample = " ".join(r[0] for r in conn.execute(
                "SELECT text FROM passages WHERE source_id = ? ORDER BY page_number, ordinal LIMIT 80", (sid,)))
        if not src:
            return
        title = None
        if titles.needs_title(src["file_name"]):
            meta = None
            if src["file_type"] == "pdf":
                try:
                    with pymupdf.open(src["original_path"]) as d:
                        meta = (d.metadata or {}).get("title")
                except Exception:
                    meta = None
            title = titles.guess_title(src["file_name"], meta, first[0] if first else None,
                                       page1[0] if page1 else None)
        cats = titles.categorise(sample)
        with db.connect() as conn:
            conn.execute("UPDATE sources SET title = ?, categories = ? WHERE id = ?",
                         (title, json.dumps(cats), sid))
    except Exception as exc:
        _set(last_error=f"naming a file failed: {exc}")


def name_existing() -> int:
    """v0.9, once per bank: titles and categories for files already imported."""
    if db.get_setting("titles_done"):
        return 0
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM sources WHERE status = 'extracted'")]
    for sid in ids:
        _name_and_tag(sid)
    db.set_setting("titles_done", True)
    return len(ids)


def clean_existing() -> int:
    """
    v0.9, once per bank: remove passages of files imported before junk
    cleaning existed that are pure junk — passages on blank / promotion /
    contents / cover pages, page-number or promo-only passages, gibberish
    passages, and passages made only of lines repeated at the top/bottom of
    most pages. In the remaining passages, header/footer/page-number/promo
    lines are taken out IN PLACE — passages are NOT renumbered, so topics and
    article citations stay valid.
    Topics that lose passages are marked 'stale'; empty topics are removed.
    RETURNS how many passages were removed.
    """
    if db.get_setting("junk_cleaned"):
        return 0
    removed = trimmed = 0
    with db.connect() as conn:
        sids = [r[0] for r in conn.execute("SELECT id FROM sources WHERE status = 'extracted' AND file_type = 'pdf'")]
        for sid in sids:
            pages = conn.execute("SELECT page_number, text FROM pages WHERE source_id = ? ORDER BY page_number",
                                 (sid,)).fetchall()
            boiler = cleaning.boilerplate([p["text"] for p in pages])
            junk_pages = {p["page_number"] for p in pages
                          if cleaning.clean_page(p["text"], p["page_number"], len(pages), boiler)[1]}
            doomed = []
            for row in conn.execute("SELECT id, page_number, text FROM passages WHERE source_id = ?", (sid,)).fetchall():
                t = row["text"]
                lines = [l.strip() for l in t.splitlines() if l.strip()]
                only_boiler = boiler and lines and all(
                    len(l.split()) <= 12 and cleaning._norm(l) in boiler for l in lines)
                if ((row["page_number"] in junk_pages and not t.startswith("[Image"))
                        or cleaning.is_junk_passage(t) or only_boiler or cleaning.is_garbled(t)):
                    doomed.append(row["id"])
                    continue
                # Same passage id, junk lines taken out (headers, footers,
                # page numbers, promo lines) — citations stay valid.
                kept = [l for l in t.splitlines()
                        if not (l.strip() and len(l.split()) <= 15 and (
                            cleaning._PAGE_NO.match(l.strip())
                            or (cleaning._PROMO.search(l) and len(l.split()) <= 15)
                            or (boiler and len(l.split()) <= 12 and cleaning._norm(l.strip()) in boiler)))]
                new = "\n".join(kept).strip()
                if new and new != t:
                    conn.execute("UPDATE passages SET text = ?, token_count = ?, content_hash = ? WHERE id = ?",
                                 (new, chunking.approx_tokens(new), chunking.fingerprint(new), row["id"]))
                    trimmed += 1
            if not doomed:
                continue
            touched = {r[0] for r in conn.execute(
                "SELECT DISTINCT topic_id FROM topic_passages WHERE passage_id IN (%s)" % ",".join("?" * len(doomed)),
                doomed)}
            conn.execute("DELETE FROM passages WHERE id IN (%s)" % ",".join("?" * len(doomed)), doomed)
            for t in touched:
                left = conn.execute("SELECT COUNT(*) FROM topic_passages WHERE topic_id = ?", (t,)).fetchone()[0]
                if left == 0:
                    conn.execute("DELETE FROM topics WHERE id = ?", (t,))
                else:
                    conn.execute("UPDATE topics SET status = 'stale', updated_at = datetime('now') "
                                 "WHERE id = ? AND status = 'written'", (t,))
            removed += len(doomed)
    db.set_setting("junk_cleaned", True)
    return removed + trimmed


def check_existing_duplicates() -> int:
    """
    v0.8.2, once per bank: files imported earlier whose paragraphs are
    (almost) all already in an OLDER file are set aside as "Same content as
    X" (the oldest copy stays). Files that only share some paragraphs are
    left alone — topic building already merges repeated paragraphs, and
    deleting single paragraphs would break citations in written articles.
    RETURNS how many files were set aside.
    """
    if db.get_setting("duplicates_checked") or not dedupe_on():
        return 0
    aside = 0
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM sources WHERE status = 'extracted' AND keep_anyway = 0 ORDER BY id")]
        for sid in ids:
            rows = conn.execute("SELECT text, content_hash FROM passages WHERE source_id = ?", (sid,)).fetchall()
            real = [r for r in rows if len(r["text"].split()) >= MIN_REPEAT_WORDS]
            if not real:
                continue
            owners: dict[int, int] = {}
            for r in real:
                o = conn.execute(
                    "SELECT p.source_id FROM passages p JOIN sources s ON s.id = p.source_id "
                    "WHERE p.content_hash = ? AND p.source_id < ? AND s.status = 'extracted' LIMIT 1",
                    (r["content_hash"], sid)).fetchone()
                if o:
                    owners[o[0]] = owners.get(o[0], 0) + 1
            repeat = sum(owners.values())
            if not repeat or (len(real) - repeat) / len(real) >= NEW_SHARE_TO_KEEP:
                continue
            same = max(owners, key=owners.get)
            name = conn.execute("SELECT file_name FROM sources WHERE id = ?", (same,)).fetchone()[0]
            info = {"verdict": "duplicate", "same_as": same, "repeats_skipped": repeat,
                    "reason": f"same content as {name} ({repeat} of {len(real)} paragraphs already in the bank)"}
            conn.execute("UPDATE sources SET relevance_json = ? WHERE id = ?", (json.dumps(info), sid))
            _retire(conn, sid)
            aside += 1
    db.set_setting("duplicates_checked", True)
    return aside


def check_existing_relevance() -> int:
    """
    v0.8.2, once per bank: banks imported before the relevance check may
    already hold unrelated files. Each file's stored text (no file is read
    again, no OCR) is checked; unrelated ones are set aside — their pages,
    passages and pictures are removed, the row stays for "Keep anyway".
    Topics that lost passages are marked 'stale' (Write remaining refreshes
    them) and topics left with no passages are deleted.
    RETURNS how many files were set aside.
    """
    if db.get_setting("relevance_checked") or not relevance_filter_on():
        return 0
    aside = 0
    with db.connect() as conn:
        rows = conn.execute("SELECT id FROM sources WHERE status = 'extracted' AND keep_anyway = 0").fetchall()
    for row in rows:
        sid = row["id"]
        with db.connect() as conn:
            parts = [r[0] for r in conn.execute(
                "SELECT text FROM pages WHERE source_id = ? ORDER BY page_number LIMIT ?",
                (sid, SAMPLE_TEXT_PAGES))]
            result = relevance.assess("\n".join(parts))
            conn.execute("UPDATE sources SET relevance_json = ? WHERE id = ?", (json.dumps(result), sid))
            if result["verdict"] != "not":
                continue
            _retire(conn, sid)
            aside += 1
    db.set_setting("relevance_checked", True)
    return aside


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
            SELECT s.id, s.file_name, s.original_path, s.file_type, s.size_bytes, s.url,
                   s.page_count, s.status, s.error, s.added_at, s.processed_at,
                   s.relevance_json, s.keep_anyway, s.title, s.categories, s.replaced_by,
                   (SELECT COUNT(*) FROM passages p WHERE p.source_id = s.id)          AS passages,
                   (SELECT COUNT(*) FROM pages g WHERE g.source_id = s.id AND g.ocr_used = 1) AS ocr_pages,
                   (SELECT COUNT(*) FROM images i WHERE i.source_id = s.id)            AS images,
                   (SELECT COUNT(*) FROM images i WHERE i.source_id = s.id
                      AND i.ocr_text IS NULL AND i.xref IS NOT NULL)                   AS pictures_waiting,
                   (SELECT COUNT(*) FROM duplicate_files d WHERE d.source_id = s.id)   AS duplicate_copies
            FROM sources s ORDER BY s.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:  # the relevance check's verdict and reason, for Library (v0.8.2)
            d["relevance"] = json.loads(d.pop("relevance_json") or "null")
        except ValueError:
            d["relevance"] = None
        try:  # v0.9 categories
            d["categories"] = json.loads(d.get("categories") or "[]")
        except ValueError:
            d["categories"] = []
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Extraction worker
# ---------------------------------------------------------------------------

def _ensure_worker() -> None:
    """Start the extraction thread if it isn't already running.
    (The worker itself pre-loads OCR when there is work — see _worker.)"""
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
    Background loop, in two passes (v0.8.1 — owner: "import is too slow"):
      1. TEXT: every waiting file, one at a time, page by page. Text pages
         take ~20 ms; scanned pages are OCR'd here because the picture IS
         the page. Pictures inside text pages are only recorded.
         → Each file is "In the bank" (searchable, groupable) in seconds.
      2. PICTURES: the recorded diagrams/screenshots are read one by one
         (~1–3 s each on a processor, much less on the graphics card).
         Their text joins the right page as extra passages.
    A newly added file always jumps ahead of waiting pictures: the loop
    checks for files before every picture. Topics are updated after the
    text pass (so new files reach topics quickly) and again at the end.
    One file/picture at a time keeps memory use predictable.
    """
    global _worker_running
    _set(state="running", files_done=0, pictures_done=0, last_error=None, phase="text")
    docs: dict = {}            # PDFs kept open during the picture pass
    text_updated = False       # topics refreshed after the text pass?
    if _next_pending()[0] or _pictures_waiting():
        ocr.prewarm()  # load OCR in the background while text pages are read
    try:
        while True:
            source, queued = _next_pending()
            if source:
                _set(phase="text", current_file=source["file_name"], current_page=0,
                     page_count=0, files_queued=queued)
                _process_source(source)
                with _lock:
                    _progress["files_done"] += 1
                text_updated = False
                continue
            if not text_updated:
                text_updated = True
                _auto_update_topics()
            if _picture_step(docs):
                continue
            break
    finally:
        for d in docs.values():
            try:
                d.close()
            except Exception:
                pass
        with _lock:
            _worker_running = False
            _progress.update(state="idle", phase=None, current_file=None, current_page=0,
                             page_count=0, files_queued=0, pictures_left=0)
        # Race guard: a file added in the instant between "nothing pending"
        # and this thread stopping would otherwise wait for the next add.
        if _next_pending()[0]:
            _ensure_worker()
        else:
            _auto_update_topics()


def _pictures_waiting() -> int:
    """How many pictures are still waiting to be read (all files)."""
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM images WHERE ocr_text IS NULL "
                            "AND xref IS NOT NULL").fetchone()[0]


def _picture_step(docs: dict) -> bool:
    """
    Read the next few waiting pictures (images rows with xref set and
    ocr_text NULL) — as many at once as there are OCR engines.
    RETURNS False when no picture is waiting.

    HOW: reopens the PDF (kept open in `docs` for the next batch), pulls
         each picture by its xref, checks it is still the same picture (its
         SHA-256), OCRs them side by side (or reuses the text of an
         identical picture read before), then saves the text and adds it as
         "[Image on page N]" passages after that page's own passages.
    A picture that can't be read any more (file moved/changed) is marked
    read with empty text, so it never blocks the queue. Batches are small,
    so a newly added file still jumps ahead within a few seconds.
    """
    width = ocr.workers()
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT i.id, i.source_id, i.page_number, i.sha256, i.xref, s.original_path, s.file_name "
            "FROM images i JOIN sources s ON s.id = i.source_id "
            "WHERE i.ocr_text IS NULL AND i.xref IS NOT NULL AND s.status = 'extracted' "
            "ORDER BY i.source_id, i.page_number, i.id LIMIT ?", (width,))]
    if not rows:
        return False
    rows = [r for r in rows if r["source_id"] == rows[0]["source_id"]]  # one PDF per batch
    first = rows[0]
    _set(phase="pictures", current_file=first["file_name"], current_page=first["page_number"],
         pictures_left=_pictures_waiting())
    # 1. pull the picture bytes (PyMuPDF: this thread only)
    jobs: list[tuple[dict, bytes | None, str | None]] = []
    for r in rows:
        known = _known_image_text(r["sha256"])
        data = None
        if known is None:
            try:
                doc = docs.get(r["source_id"])
                if doc is None:
                    for d in docs.values():  # one PDF open at a time keeps memory low
                        d.close()
                    docs.clear()
                    doc = pymupdf.open(r["original_path"])
                    docs[r["source_id"]] = doc
                raw = doc.extract_image(r["xref"])["image"]
                data = raw if hashlib.sha256(raw).hexdigest() == r["sha256"] else None
            except Exception:
                data = None  # moved, changed or locked: skip, never stall
            known = None if data is not None else ""
        jobs.append((r, data, known))
    # 2. read them side by side
    with ThreadPoolExecutor(max_workers=max(1, len(jobs)), thread_name_prefix="kb-ocr") as pool:
        futures = [pool.submit(ocr.read_text, data) if data is not None else None for _r, data, _k in jobs]
        texts = [f.result() if f is not None else k for f, (_r, _d, k) in zip(futures, jobs)]
    # 3. store, in page order
    with db.connect() as conn:
        for (r, _d, _k), text in zip(jobs, texts):
            text = text or ""
            conn.execute("UPDATE images SET ocr_text = ? WHERE id = ?", (text, r["id"]))
            if len(text.split()) < MIN_IMAGE_WORDS:
                continue
            page = conn.execute("SELECT id FROM pages WHERE source_id = ? AND page_number = ?",
                                (r["source_id"], r["page_number"])).fetchone()
            if not page:
                continue  # page gone (file re-read meanwhile): keep the text, add no passage
            last = conn.execute(
                "SELECT ordinal, section FROM passages WHERE source_id = ? AND page_number = ? "
                "ORDER BY ordinal DESC LIMIT 1", (r["source_id"], r["page_number"])).fetchone()
            ordinal = (int(last["ordinal"]) + 1) if last else 0
            section = last["section"] if last else None
            for passage in chunking.split_passages(text):
                if (dedupe_on() and len(passage.split()) >= MIN_REPEAT_WORDS and conn.execute(
                        "SELECT 1 FROM passages WHERE content_hash = ? AND source_id != ? LIMIT 1",
                        (chunking.fingerprint(passage), r["source_id"])).fetchone()):
                    continue  # v0.8.2: this diagram's text is already in another file
                labelled = f"[Image on page {r['page_number']}] {passage}"
                conn.execute(
                    "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                    "token_count, content_hash, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (r["source_id"], page["id"], r["page_number"], ordinal,
                     labelled, chunking.approx_tokens(labelled), chunking.fingerprint(passage), section))
                ordinal += 1
    with _lock:
        _progress["pictures_done"] += len(jobs)
    return True


def _auto_update_topics() -> None:
    """
    Phase 7: after new files finish importing, add their passages to the
    existing topics automatically (distill.start_update) — only when topics
    already exist, there are new passages, and the AI engine is running.
    Otherwise the Topics screen offers "Update topics" by hand.
    """
    try:
        from . import distill, ollama_client  # late import: distill is heavier and imports numpy lazily

        with db.connect() as conn:
            has_topics = conn.execute("SELECT 1 FROM topics LIMIT 1").fetchone()
        if has_topics and distill.pending_count() and ollama_client.is_running():
            distill.start_update()
    except Exception:
        pass  # never let this affect importing


def _process_source(source: dict) -> None:
    """Extract one source; mark it extracted or failed (with a readable reason)."""
    sid = source["id"]
    with db.connect() as conn:
        conn.execute("UPDATE sources SET status = 'extracting', error = NULL WHERE id = ?", (sid,))
        conn.execute("DELETE FROM pages WHERE source_id = ?", (sid,))   # clear any partial run
        conn.execute("DELETE FROM images WHERE source_id = ?", (sid,))
        conn.execute("DELETE FROM doc_tables WHERE source_id = ?", (sid,))
    try:
        path = Path(source["original_path"])
        if not path.exists():
            raise FileNotFoundError("The original file was moved or deleted. Add it again from its new location.")
        _dup_start(sid)
        if source["file_type"] == "pdf":
            page_count = _extract_pdf(sid, path)
        elif source["file_type"] == "table":
            page_count = _extract_table(sid, path)
        elif source["file_type"] == "doc":
            page_count = _extract_doc(sid, path)
        else:
            page_count = _extract_image(sid, path)
        duplicate = _dup_verdict(sid)
        if duplicate:
            raise SetAside(duplicate)  # nothing new in this file (v0.8.2)
        with db.connect() as conn:
            conn.execute(
                "UPDATE sources SET status = 'extracted', page_count = ?, "
                "processed_at = datetime('now') WHERE id = ?",
                (page_count, sid),
            )
        _name_and_tag(sid)  # v0.9: readable title + categories
        if _replace_older(sid):
            return  # re-queued to be read again in full (see _replace_older)
        if source["file_type"] == "table":
            # A spreadsheet becomes its own calculated topic at once — no AI
            # needed, visible on the Topics screen straight after import (v0.8).
            try:
                from . import datapages
                datapages.ensure_data_topic(sid)
            except Exception as exc:
                _set(last_error=f"{source['file_name']}: couldn't build its data page ({exc})")
    except SetAside as aside:
        # Not about cybersecurity, or nothing new in it (v0.8.2): keep only
        # the row (so it is never imported again and can be kept with one
        # click), drop any text.
        _dups.pop(sid, None)
        _stats.pop(sid, None)
        with db.connect() as conn:
            conn.execute("DELETE FROM pages WHERE source_id = ?", (sid,))
            conn.execute("DELETE FROM images WHERE source_id = ?", (sid,))
            conn.execute("DELETE FROM doc_tables WHERE source_id = ?", (sid,))
            conn.execute("UPDATE sources SET status = 'set_aside', error = NULL, "
                         "processed_at = datetime('now'), relevance_json = ? WHERE id = ?",
                         (json.dumps(aside.result), sid))
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        _set(last_error=f"{source['file_name']}: {message}")
        with db.connect() as conn:
            conn.execute("UPDATE sources SET status = 'failed', error = ? WHERE id = ?",
                         (message, sid))


# ---------------------------------------------------------------------------
# Content already in the bank (v0.8.2, owner: "2 different PDFs with the same
# content … the content should be added only if not present, otherwise
# nothing").
#   - Paragraph level: a passage whose fingerprint (chunking.fingerprint —
#     same words, ignoring case/spacing/punctuation) already exists in ANOTHER
#     file is not added again. Its page text is still stored, so "Read in
#     context" shows the whole page. Very short passages (< MIN_REPEAT_WORDS,
#     e.g. a heading like "Overview") are always kept — they carry structure,
#     not content.
#   - File level: when a file brings (almost) nothing new — under
#     NEW_SHARE_TO_KEEP of its paragraphs — it is set aside as "Same content
#     as X" (Library shows it; "Keep anyway" imports it in full).
#   - Scans: if the 3 sample pages read for the relevance check are already
#     in the bank, the scan is set aside before reading the other pages.
# ---------------------------------------------------------------------------
MIN_REPEAT_WORDS = 8
NEW_SHARE_TO_KEEP = 0.05
_dups: dict[int, dict] = {}   # source id → {"on", "new", "repeat", "matches": {sid: n}}
_last_matches: dict[int, dict] = {}  # after a read: which files its repeats came from (v0.9)

# v0.9 "Replace old versions automatically": an existing file is treated as
# an OLDER VERSION of a newly read file when most of its paragraphs reappear
# in the new one — at least OLD_SHARE_SAME_NAME when the names/titles look
# alike ("Guide v1" / "Guide v2", "Playbook" / "Playbook (final)"), or
# OLD_SHARE_ANY_NAME when they don't (numeric LinkedIn downloads).
OLD_SHARE_SAME_NAME = 0.6
OLD_SHARE_ANY_NAME = 0.85


def dedupe_on() -> bool:
    """Owner's switch in Library (default ON): skip content already in the bank."""
    return bool(db.get_setting("dedupe_filter", True))


def _dup_start(sid: int) -> None:
    _stats.pop(sid, None)  # fresh junk/garbled counts for this read
    with db.connect() as conn:
        row = conn.execute("SELECT keep_anyway FROM sources WHERE id = ?", (sid,)).fetchone()
    _dups[sid] = {"on": dedupe_on() and not (row and row["keep_anyway"]),
                  "new": 0, "repeat": 0, "matches": {}}


def _already_present(conn, sid: int, passage: str, fp: str) -> bool:
    """Is this passage already in another file of the bank? (counts it)"""
    d = _dups.get(sid)
    if not d or not d["on"] or len(passage.split()) < MIN_REPEAT_WORDS:
        # Short lines (headings, a cover page title) are kept but don't
        # count as "new content" — a re-exported copy with a new cover is
        # still a copy.
        return False
    row = conn.execute("SELECT source_id FROM passages WHERE content_hash = ? AND source_id != ? LIMIT 1",
                       (fp, sid)).fetchone()
    if row:
        d["repeat"] += 1
        d["matches"][row["source_id"]] = d["matches"].get(row["source_id"], 0) + 1
        return True
    d["new"] += 1
    return False


def _dup_verdict(sid: int) -> dict | None:
    """After a file is read: a 'duplicate' result if it brought (almost)
    nothing new, else None. Also records how many repeats were skipped."""
    d = _dups.pop(sid, None)
    if not d:
        return None
    _last_matches[sid] = dict(d["matches"]) if d["on"] else {}
    total = d["new"] + d["repeat"]
    with db.connect() as conn:
        row = conn.execute("SELECT relevance_json FROM sources WHERE id = ?", (sid,)).fetchone()
        info = json.loads(row["relevance_json"] or "{}") if row else {}
        info["repeats_skipped"] = d["repeat"]
        info.update(_stats.pop(sid, {}))  # v0.9: junk pages / garbled pages
        conn.execute("UPDATE sources SET relevance_json = ? WHERE id = ?", (json.dumps(info), sid))
        if not d["on"] or total == 0 or d["repeat"] == 0 or d["new"] / total >= NEW_SHARE_TO_KEEP:
            return None
        same = max(d["matches"], key=d["matches"].get)
        name = conn.execute("SELECT file_name FROM sources WHERE id = ?", (same,)).fetchone()
    name = name["file_name"] if name else "another file"
    return {"verdict": "duplicate", "same_as": same, "repeats_skipped": d["repeat"],
            "reason": f"same content as {name} ({d['repeat']} of {total} paragraphs already in the bank)"}


def _store_page(sid: int, page_number: int, text: str, ocr_used: bool,
                image_records: list[dict], sections: dict | None = None,
                clean: tuple[int, set] | None = None) -> None:
    """
    sections: one dict per document carried page to page, so each passage
    records the document part it belongs to (chunking.split_with_sections).
    Save one page (text + passages + embedded-image records) in a single
    transaction, so a crash can never leave a page half-stored.
    image_records: [{"sha256", "ocr_text"}] for pictures found on this page.
    clean (v0.9): (page count, boilerplate lines) — PDF pages are cleaned by
    cleaning.clean_page before cutting passages; a junk page (blank, promo,
    contents, cover) stores its text but gives no passages.
    """
    passage_text = text
    if clean is not None:
        passage_text, junk = cleaning.clean_page(text, page_number, clean[0], clean[1])
        if junk:
            _count(sid, "junk_pages", junk)
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO pages(source_id, page_number, text, ocr_used, char_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, page_number, text, int(ocr_used), len(text)),
        )
        page_id = cur.lastrowid
        ordinal = 0
        state = sections if sections is not None else {}
        section = None
        for passage, section in chunking.split_with_sections(passage_text, state):
            fp = chunking.fingerprint(passage)
            if _already_present(conn, sid, passage, fp):
                continue  # v0.8.2: this paragraph is already in another file
            conn.execute(
                "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                "token_count, content_hash, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, page_id, page_number, ordinal, passage,
                 chunking.approx_tokens(passage), fp, section),
            )
            ordinal += 1
        section = state.get("major") or state.get("title")
        for img in image_records:
            conn.execute(
                "INSERT INTO images(source_id, page_number, sha256, ocr_text, xref) VALUES (?, ?, ?, ?, ?)",
                (sid, page_number, img["sha256"], img["ocr_text"], img.get("xref")),
            )
            # ocr_text None = waiting for the picture pass (v0.8.1); it adds
            # the passages later (_picture_step).
            if img["ocr_text"] is None:
                continue
            # Text read from a diagram becomes its own passage so it is
            # searchable and citable like any other text on the page.
            if len(img["ocr_text"].split()) >= MIN_IMAGE_WORDS:
                for passage in chunking.split_passages(img["ocr_text"]):
                    if _already_present(conn, sid, passage, chunking.fingerprint(passage)):
                        continue  # same diagram text already in another file
                    labelled = f"[Image on page {page_number}] {passage}"
                    conn.execute(
                        "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                        "token_count, content_hash, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (sid, page_id, page_number, ordinal, labelled,
                         chunking.approx_tokens(labelled), chunking.fingerprint(passage), section),
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
    Record the meaningful pictures on a PDF page (diagrams, screenshots).
    The same picture repeated on one page (e.g. a logo) is handled once.
    v0.8.1: a picture seen before (same bytes) gets its known text now;
    any other picture is NOT read here — it is saved as waiting
    (ocr_text None + its xref) and read by the picture pass, so the file's
    text is in the bank without waiting for slow picture OCR.
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
        records.append({"sha256": sha, "ocr_text": _known_image_text(sha), "xref": xref})
    return records


def _page_text(page) -> tuple[str, list[tuple[str, list[list[str]]]]]:
    """
    A PDF page's text with its TABLES kept as tables.

    WHY (v0.6.2, owner's screenshot): plain text extraction reads a table
        cell by cell, so a "Step | Action" table came out as the headers on
        their own lines and every row run together ("1 Lock the user account
        2 Block the IP …").
    HOW:  PyMuPDF's table finder locates ruled/aligned tables. Text blocks
        mostly inside a table are left out; instead each table row is
        written as one line with cells joined by " · " (empty cells as "—"),
        placed where the table sits on the page. The exact grid is also
        returned so it can be saved to doc_tables (lessons draw it as a real
        table). Any failure falls back to plain text.
    RETURNS (text, [(table name, rows)]).
    """
    plain = page.get_text("text")
    try:
        found = [t for t in page.find_tables().tables if t.row_count >= 2 and t.col_count >= 2]
    except Exception:
        return plain, []
    if not found:
        return plain, []
    rects = [pymupdf.Rect(t.bbox) for t in found]
    tables, table_items = [], []
    for i, t in enumerate(found, start=1):
        rows = []
        for row in t.extract():
            cells = [re.sub(r"\s+", " ", c or "").strip() for c in row]
            if any(cells):
                rows.append(cells)
        if len(rows) < 2:
            continue
        tables.append((f"Table {i} on page {page.number + 1}", rows))
        table_items.append((t.bbox[1], "\n".join(" · ".join(c or "—" for c in r) for r in rows)))
    items: list[tuple[float, str]] = []
    for b in page.get_text("blocks"):
        if b[6] != 0:  # image block
            continue
        r = pymupdf.Rect(b[:4])
        area = max(r.get_area(), 1e-6)
        if any((r & tr).get_area() > 0.5 * area for tr in rects):
            continue  # this text is part of a table — written from the grid instead
        items.append((b[1], b[4].rstrip("\n")))
    # Keep the page's natural block order; slot each table in before the
    # first block that starts below it.
    for y, text in sorted(table_items):
        pos = next((k for k, (by, _t) in enumerate(items) if by > y), len(items))
        items.insert(pos, (y, text))
    return "\n".join(t for _y, t in items), tables


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
            password = _passwords.pop(sid, None)  # used once, never stored (v0.7)
            if not password:
                raise PermissionError("This PDF is password-protected. Click \"Enter password\" to open it.")
            if not doc.authenticate(password):
                raise PermissionError("Wrong password for this PDF. Click \"Enter password\" to try again.")
        total = doc.page_count
        _set(page_count=total)
        _check_pdf(sid, doc)  # v0.8.2: may raise SetAside before any slow work
        sections: dict = {}  # document part carried from page to page
        # v0.8.1: scanned pages are OCR'd SEVERAL AT A TIME (one per OCR
        # engine, see ocr.workers()) while this thread keeps reading the
        # next pages. Pages are still STORED strictly in page order, because
        # the document part ("sections") carries from one page to the next.
        # At most 2 × workers pages wait in memory at once.
        # v0.9: lines repeated at the top/bottom of most pages (headers,
        # footers, the author's name on every slide) — read from the text
        # layer up front (~1 ms/page) so every page can drop them.
        boiler = cleaning.boilerplate([doc[i].get_text("text") for i in range(min(total, 400))])
        width = ocr.workers() if (_has_scanned_pages(doc) or _has_garbled_pages(doc)) else 1
        waiting: deque = deque()  # (page_no, future-or-text, ocr_used, images, tables)

        def flush(block: bool) -> None:
            while waiting and (block or not isinstance(waiting[0][1], Future) or waiting[0][1].done()):
                page_no, text, ocr_used, images, tables = waiting.popleft()
                if isinstance(text, Future):
                    text = text.result()
                _store_page(sid, page_no, text, ocr_used, images, sections,
                            clean=(total, boiler))
                if tables:
                    with db.connect() as conn:
                        conn.executemany(
                            "INSERT INTO doc_tables(source_id, page_number, name, rows_json) VALUES (?, ?, ?, ?)",
                            [(sid, page_no, name, json.dumps(rows)) for name, rows in tables],
                        )
                _set(current_page=page_no)

        with ThreadPoolExecutor(max_workers=width, thread_name_prefix="kb-ocr") as pool:
            for index, page in enumerate(doc):
                text, tables = _page_text(page)
                if len(text.strip()) < SCANNED_PAGE_CHAR_THRESHOLD:
                    # Scanned page: read the whole rendered page instead.
                    png = page.get_pixmap(dpi=OCR_RENDER_DPI).tobytes("png")
                    waiting.append((index + 1, pool.submit(ocr.read_text, png), True, [], []))
                elif cleaning.is_garbled(text):
                    # v0.9: broken font encoding → the text layer is gibberish;
                    # read the page as a picture instead (kept only if better).
                    png = page.get_pixmap(dpi=OCR_RENDER_DPI).tobytes("png")
                    _count(sid, "garbled_pages")
                    waiting.append((index + 1, pool.submit(_ocr_instead, png, text), True, [], []))
                else:
                    waiting.append((index + 1, text, False, _embedded_images(doc, page), tables))
                flush(block=len(waiting) >= 2 * width)
            flush(block=True)
        return total


def _ocr_instead(png: bytes, original: str) -> str:
    """OCR text for a garbled page — or the original if OCR did no better."""
    text = ocr.read_text(png)
    return text if len(text.split()) >= 5 and not cleaning.is_garbled(text) else original


def _has_garbled_pages(doc, sample: int = 40) -> bool:
    """Does this PDF have gibberish text pages (so OCR engines are needed)?"""
    return any(cleaning.is_garbled(doc[i].get_text("text")) for i in range(min(sample, doc.page_count)))


_stats: dict[int, dict] = {}  # source id → {"junk_pages": n, "garbled_pages": n, "junk": {reason: n}}


def _count(sid: int, key: str, reason: str | None = None) -> None:
    d = _stats.setdefault(sid, {})
    d[key] = d.get(key, 0) + 1
    if reason:
        d.setdefault("junk", {})[reason] = d.setdefault("junk", {}).get(reason, 0) + 1


class SetAside(Exception):
    """Raised by an extractor when relevance.assess() says the file is not
    about cybersecurity; _process_source records it as 'set_aside'."""

    def __init__(self, result: dict):
        super().__init__(result.get("reason", "not about cybersecurity"))
        self.result = result


# Pages read for the relevance sample. The text layer is ~1 ms per page, so
# a generous sample costs nothing; scanned PDFs OCR at most SAMPLE_OCR_PAGES.
SAMPLE_TEXT_PAGES = 25
SAMPLE_OCR_PAGES = 3


def relevance_filter_on() -> bool:
    """Owner's switch in Library (default ON): set aside non-security files."""
    return bool(db.get_setting("relevance_filter", True))


def _check_needed(sid: int) -> bool:
    """Run the relevance check for this file? Not when the switch is off or
    the owner pressed "Keep anyway" for it."""
    if not relevance_filter_on():
        return False
    with db.connect() as conn:
        row = conn.execute("SELECT keep_anyway FROM sources WHERE id = ?", (sid,)).fetchone()
    return not (row and row["keep_anyway"])


def _judge(sid: int, text: str) -> None:
    """Record the verdict; raise SetAside when the file is not about security."""
    result = relevance.assess(text)
    with db.connect() as conn:
        conn.execute("UPDATE sources SET relevance_json = ? WHERE id = ?", (json.dumps(result), sid))
    if result["verdict"] == "not":
        raise SetAside(result)


def _check_pdf(sid: int, doc) -> None:
    """
    v0.8.2: decide BEFORE the slow work whether this PDF is about security.
    Sample = text layer of the first SAMPLE_TEXT_PAGES pages. If that is
    too short (a scanned PDF), up to SAMPLE_OCR_PAGES scanned pages spread
    through the document are OCR'd side by side and added — so an unrelated
    200-page scan costs ~3 pages of OCR instead of 200.
    """
    if not _check_needed(sid):
        return
    n = min(SAMPLE_TEXT_PAGES, doc.page_count)
    text = "\n".join(doc[i].get_text("text") for i in range(n))
    if len(text.split()) < relevance.MIN_WORDS:
        scanned = [i for i in range(doc.page_count)
                   if len(doc[i].get_text("text").strip()) < SCANNED_PAGE_CHAR_THRESHOLD]
        if scanned:
            k = min(SAMPLE_OCR_PAGES, len(scanned))
            picks = sorted({scanned[(j * len(scanned)) // k] for j in range(k)})
            _set(current_page=picks[0] + 1)
            pngs = [doc[i].get_pixmap(dpi=OCR_RENDER_DPI).tobytes("png") for i in picks]
            with ThreadPoolExecutor(max_workers=max(1, min(len(pngs), ocr.workers()))) as pool:
                page_texts = list(pool.map(ocr.read_text, pngs))
            text += "\n" + "\n".join(page_texts)
            _judge(sid, text)
            _scan_already_present(sid, page_texts, doc.page_count)
            return
    _judge(sid, text)


def _scan_already_present(sid: int, page_texts: list[str], page_count: int) -> None:
    """
    A scan whose sample pages are ALL already in one file of the same length
    is set aside before the remaining pages are OCR'd (the slow part).
    A sample page counts as present when another file has a page with the
    very same text (the same scan read again gives the same text), or when
    at least 80% of its paragraphs are already in that file.
    """
    d = _dups.get(sid)
    if not d or not d["on"]:
        return
    owners: dict[int, int] = {}
    with db.connect() as conn:
        for t in page_texts:
            if len(t.split()) < MIN_REPEAT_WORDS * 3:
                return  # too little text on a sample page to be sure
            row = conn.execute("SELECT source_id FROM pages WHERE text = ? AND source_id != ? LIMIT 1",
                               (t, sid)).fetchone()
            if row:
                owners[row[0]] = owners.get(row[0], 0) + 1
                continue
            fps = [chunking.fingerprint(p) for p, _sec in chunking.split_with_sections(t, {})
                   if len(p.split()) >= MIN_REPEAT_WORDS]
            hits: dict[int, int] = {}
            for fp in fps:
                o = conn.execute("SELECT source_id FROM passages WHERE content_hash = ? AND source_id != ? LIMIT 1",
                                 (fp, sid)).fetchone()
                if o:
                    hits[o[0]] = hits.get(o[0], 0) + 1
            best = max(hits, key=hits.get) if hits else None
            if best is None or hits[best] < 0.8 * len(fps):
                return  # this page has new content: read the whole scan
            owners[best] = owners.get(best, 0) + 1
        same = max(owners, key=owners.get)
        if owners[same] < len(page_texts):
            return  # sample pages match different files: not one copy
        other = conn.execute("SELECT file_name, page_count FROM sources WHERE id = ?", (same,)).fetchone()
    if other and other["page_count"] == page_count:
        raise SetAside({"verdict": "duplicate", "same_as": same,
                        "reason": f"same content as {other['file_name']} (scanned pages already in the bank)"})


def _has_scanned_pages(doc, sample: int = 40) -> bool:
    """Quick look (text layer only, ~1 ms/page) at the first pages: does
    this PDF need OCR at all? Avoids starting OCR engines for text PDFs."""
    for i in range(min(sample, doc.page_count)):
        if len(doc[i].get_text("text").strip()) < SCANNED_PAGE_CHAR_THRESHOLD:
            return True
    return doc.page_count > sample  # can't tell for the rest: allow it


def _extract_image(sid: int, path: Path) -> int:
    """OCR a standalone image as a one-page source. RETURNS 1."""
    _set(page_count=1, current_page=1)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    text = ocr.read_text(data)
    if _check_needed(sid):
        _judge(sid, text)  # short screenshot text is "unsure" → kept
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO images(source_id, page_number, sha256, ocr_text) VALUES (?, 1, ?, ?)",
            (sid, sha, text),
        )
    _store_page(sid, 1, text, True, [])
    return 1


def _extract_doc(sid: int, path: Path) -> int:
    """
    v0.9: Word / PowerPoint / web page / text / Markdown (officefiles.py).
    Same steps as a PDF: relevance check on a sample, junk cleaning with the
    document's own repeated lines, paragraphs already in the bank skipped,
    tables kept as tables, and pictures (slides, diagrams) read by OCR —
    several at once — with text from identical pictures reused.
    RETURNS the number of pages (slides for PowerPoint).
    """
    from . import officefiles
    try:
        pages = officefiles.read(path)
    except Exception as exc:
        raise ValueError(f"Couldn't read this file ({exc.__class__.__name__}). "
                         "If it is open in Word or PowerPoint, close it and press Retry.") from exc
    total = len(pages)
    _set(page_count=total)
    if _check_needed(sid):
        _judge(sid, "\n".join(p["text"] for p in pages[:SAMPLE_TEXT_PAGES]))
    boiler = cleaning.boilerplate([p["text"] for p in pages])
    sections: dict = {}
    for n, page in enumerate(pages, start=1):
        _set(current_page=n)
        records = []
        if page["pictures"]:
            todo = []
            for data in page["pictures"]:
                sha = hashlib.sha256(data).hexdigest()
                known = _known_image_text(sha)
                records.append({"sha256": sha, "ocr_text": known})
                if known is None:
                    todo.append((len(records) - 1, data))
            if todo:
                with ThreadPoolExecutor(max_workers=max(1, min(len(todo), ocr.workers()))) as pool:
                    for (i, _d), text in zip(todo, pool.map(ocr.read_text, [d for _i, d in todo])):
                        records[i]["ocr_text"] = text
        _store_page(sid, n, page["text"], False, records, sections, clean=(total, boiler))
        if page["tables"]:
            with db.connect() as conn:
                conn.executemany(
                    "INSERT INTO doc_tables(source_id, page_number, name, rows_json) VALUES (?, ?, ?, ?)",
                    [(sid, n, name, json.dumps(rows, ensure_ascii=False)) for name, rows in page["tables"]])
    return total


def _cell(value) -> str:
    """Spreadsheet cell → clean text (whole numbers without '.0', no None)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_sheets(path: Path) -> list[tuple[str, list[list[str]]]]:
    """
    Read every sheet as (name, rows). Values only — formulas are read as
    their last calculated result (data_only=True), which is what the owner
    sees in Excel. Completely empty rows and trailing empty columns are
    dropped. CSV files become one sheet named after the file.
    """
    if path.suffix.lower() == ".csv":
        import csv

        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = [[c.strip() for c in r[:MAX_SHEET_COLS]] for r in csv.reader(f)]
        return [(path.stem, rows[:MAX_SHEET_ROWS])]

    import openpyxl  # loaded only when a spreadsheet is imported

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            rows: list[list[str]] = []
            for r in ws.iter_rows(values_only=True, max_col=MAX_SHEET_COLS):
                cells = [_cell(v) for v in r]
                if any(cells):
                    while cells and not cells[-1]:
                        cells.pop()
                    rows.append(cells)
                if len(rows) >= MAX_SHEET_ROWS:
                    break
            sheets.append((ws.title, rows))
    finally:
        wb.close()
    return sheets


def _extract_table(sid: int, path: Path) -> int:
    """
    Import a spreadsheet: each sheet becomes one "page".
      - The exact grid is stored in doc_tables (lessons draw tables and
        compute patterns from here, never from AI text).
      - A readable text version (one line per row, cells separated by " · ")
        becomes the page text, so search, topics and articles can use it.
        Empty cells are skipped in that text, because the owner's sheets
        (like the Subnet Guide) are laid out visually with gaps.
    RETURNS the number of sheets.
    """
    sheets = _read_sheets(path)
    if not sheets:
        raise ValueError("The spreadsheet has no readable sheets.")
    _set(page_count=len(sheets))
    if _check_needed(sid):
        _judge(sid, "\n".join(" ".join(c for c in row if c) for _n, rows in sheets for row in rows[:400]))
    for n, (name, rows) in enumerate(sheets, start=1):
        _set(current_page=n)
        lines = [f"Sheet: {name}"] + [" · ".join(c for c in row if c) for row in rows]
        text = "\n".join(line for line in lines if line)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO doc_tables(source_id, page_number, name, rows_json) VALUES (?, ?, ?, ?)",
                (sid, n, name, json.dumps(rows, ensure_ascii=False)),
            )
        _store_page(sid, n, text, False, [], {"title": f"Sheet: {name}"})
    return len(sheets)


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

def rechunk_all() -> int:
    """
    Rebuild every passage from stored page text using the current chunking
    rules, then record the new CHUNKER_VERSION.

    WHY:   v0.5 changed how text is kept (bullets/queries on their own
           lines). Existing banks are upgraded without re-reading any PDF:
           page text (pages.text) and picture text (images.ocr_text) are
           already stored.
    SIDE EFFECTS: passage ids change, so meaning-vectors and topics built on
           the old passages are cleared — the owner presses "Build topics"
           again (the Topics screen says so).
    RETURNS the number of passages created.
    """
    with db.connect() as conn:
        sources = [r["id"] for r in conn.execute("SELECT id FROM sources WHERE status = 'extracted'")]
    _set(state="running", current_file="Re-organising text for easier reading", files_done=0,
         files_queued=len(sources), current_page=0, page_count=0)
    created = 0
    try:
        with db.connect() as conn:
            conn.execute("DELETE FROM topics")                 # built on old passage ids
        db.set_setting("distill_last_run", None)
        for n, sid in enumerate(sources, start=1):
            with db.connect() as conn:
                conn.execute("DELETE FROM passages WHERE source_id = ?", (sid,))
                pages = conn.execute(
                    "SELECT id, page_number, text FROM pages WHERE source_id = ? ORDER BY page_number", (sid,)
                ).fetchall()
                images = conn.execute(
                    "SELECT page_number, ocr_text FROM images WHERE source_id = ?", (sid,)
                ).fetchall()
                by_page: dict[int, list[str]] = {}
                for img in images:
                    by_page.setdefault(img["page_number"], []).append(img["ocr_text"] or "")
                sections: dict = {}  # document part, carried page to page
                for pg in pages:
                    ordinal = 0
                    pieces = [(p, p, sec) for p, sec in chunking.split_with_sections(pg["text"], sections)]
                    here = sections.get("major") or sections.get("title")
                    for ocr_text in by_page.get(pg["page_number"], []):
                        if len(ocr_text.split()) >= MIN_IMAGE_WORDS:
                            pieces += [(f"[Image on page {pg['page_number']}] {p}", p, here)
                                       for p in chunking.split_passages(ocr_text)]
                    for shown, core, sec in pieces:
                        conn.execute(
                            "INSERT INTO passages(source_id, page_id, page_number, ordinal, text, "
                            "token_count, content_hash, section) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (sid, pg["id"], pg["page_number"], ordinal, shown,
                             chunking.approx_tokens(shown), chunking.fingerprint(core), sec),
                        )
                        ordinal += 1
                        created += 1
            _set(files_done=n, files_queued=len(sources) - n)
        db.set_setting("chunker_version", chunking.CHUNKER_VERSION)
    finally:
        _set(state="idle", current_file=None, files_queued=0)
    return created


# Passwords for protected PDFs, typed by the owner in the Library (v0.7).
# Held in memory only until that one file has been read, then forgotten —
# never written to the database or to disk.
_passwords: dict[int, str] = {}


def unlock(source_id: int, password: str) -> dict:
    """Retry a password-protected PDF with the given password."""
    with db.connect() as conn:
        r = conn.execute("SELECT id, file_type, status FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not r or r["file_type"] != "pdf":
            return {"ok": False, "message": "That file isn't a PDF in the library."}
        _passwords[source_id] = password
        conn.execute("UPDATE sources SET status = 'pending', error = NULL WHERE id = ?", (source_id,))
    _ensure_worker()
    return {"ok": True, "message": "Opening the PDF with your password…"}


# Bump when the way text is READ from files changes (not just how it is cut
# into passages): existing banks then re-read their original files once.
#   2 (v0.6.2): PDF tables kept as tables; OCR rebuilds table rows and
#               repairs broken IPs/dates.
EXTRACT_VERSION = 2


def reread_all() -> int:
    """
    One-time upgrade after EXTRACT_VERSION changes.

    PDFs and images whose original file is still in place are re-read from
    scratch (marked 'pending', so the normal import worker does it, with
    progress shown in the Library). Files whose original has moved, and
    spreadsheets, keep their stored text and are only re-organised with the
    current passage rules (rechunk_all). Topics are cleared because passage
    ids change — the owner presses "Build topics" again.
    RETURNS how many files will be re-read.
    """
    with db.connect() as conn:
        conn.execute("DELETE FROM topics")
        rows = conn.execute(
            "SELECT id, original_path, file_type FROM sources WHERE status = 'extracted'").fetchall()
        again = [r["id"] for r in rows
                 if r["file_type"] in ("pdf", "image") and Path(r["original_path"]).exists()]
        for sid in again:
            conn.execute("DELETE FROM passages WHERE source_id = ?", (sid,))
            conn.execute("UPDATE sources SET status = 'pending' WHERE id = ?", (sid,))
    db.set_setting("distill_last_run", None)
    rechunk_all()  # everything not being re-read gets the current text rules
    db.set_setting("extract_version", EXTRACT_VERSION)
    return len(again)


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
    # New install → just record the version. Older bank → re-organise text
    # in the background (before any new imports run).
    with db.connect() as conn:
        has_passages = conn.execute("SELECT 1 FROM passages LIMIT 1").fetchone()
    if db.get_setting("extract_version") != EXTRACT_VERSION:
        if has_passages:
            threading.Thread(target=lambda: (reread_all(), _ensure_worker()),
                             name="kb-reread", daemon=True).start()
            threading.Thread(target=_watch_loop, name="kb-watch", daemon=True).start()
            return
        db.set_setting("extract_version", EXTRACT_VERSION)
    if db.get_setting("chunker_version") != chunking.CHUNKER_VERSION:
        if has_passages:
            threading.Thread(target=lambda: (rechunk_all(), _ensure_worker()),
                             name="kb-rechunk", daemon=True).start()
            threading.Thread(target=_watch_loop, name="kb-watch", daemon=True).start()
            return
        db.set_setting("chunker_version", chunking.CHUNKER_VERSION)
    # v0.8.2: once per bank, set aside files already imported that are not
    # about cybersecurity (stored text only — quick, no OCR).
    def _existing_checks():
        _safe_log(check_existing_relevance, "relevance check (files set aside)")
        _safe_log(check_existing_duplicates, "same-content check (files set aside)")
        _safe_log(clean_existing, "junk clean-up (passages)")
        _safe_log(name_existing, "titles and categories (files)")
    threading.Thread(target=_existing_checks, name="kb-relevance", daemon=True).start()
    _ensure_worker()
    threading.Thread(target=_watch_loop, name="kb-watch", daemon=True).start()


def _safe_log(fn, label: str) -> None:
    """Run a background helper; report a failure instead of crashing."""
    try:
        n = fn()
        if n:
            print(f"[engine] {label}: {n}", flush=True)
    except Exception as exc:
        _set(last_error=f"{label} failed: {exc}")
