"""
db.py — creates and opens the Knowledge Bank database.

WHAT:  Defines the structure (schema) of the single SQLite file that stores
       everything the app knows, and provides `connect()` for other modules.

WHY:   SQLite is one file on disk, needs no separate server, is extremely
       fast for this data size (5–6 GB of PDFs becomes far less as text), and
       has built-in full-text search (FTS5) for instant exact-word search.

WHEN:  `init_db()` runs every time the engine starts (server.py). It is safe
       to run repeatedly: tables are only created if missing, and future
       schema changes are applied step by step via SCHEMA_VERSION.

CONNECTED TO:
       - config.py   → DB_PATH (where the file lives)
       - server.py   → calls init_db() on startup and reads stats
       - Phase 1+ import/distil/write modules will read and write these tables

HOW THE TABLES FIT TOGETHER (the "distillation" chain):

    sources ──< pages ──< passages ──< topic_passages >── topics
       │                     │                               │
       ├──< images           └── passages_fts (search)       ├──< topic_links
       └──< duplicate_files                                  └──< conflicts
    jobs      (progress of long-running background work)
    settings  (app preferences, e.g. watched folders)

    1. A PDF/image the owner adds = one row in `sources`.
    2. Each page's text = one row in `pages`.
    3. Pages are cut into readable chunks = `passages` (each remembers its
       source file and page → this is how every line stays traceable).
    4. Passages saying the same thing are grouped and written up as one
       merged article = `topics`. `topic_passages` records exactly which
       passages fed each topic → this is the "nothing missed" coverage check:
       any passage with no row here is not yet covered.
    5. `topic_links` = the connections drawn on the Knowledge Map.
    6. `conflicts` = places where sources disagree, shown to the owner.
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

# Increase this number whenever the schema changes, and add a matching
# step in _MIGRATIONS. Existing databases are upgraded in place — the
# owner never loses data because of an app update.
SCHEMA_VERSION = 14

# Each entry: (version it upgrades TO, list of SQL statements).
# Version 1 = the initial Phase 0 schema.
# Version 2 = Phase 1 (import): settings + duplicate_files tables.
# Version 3 = Phase 2 (distil): topic_passages.fit — how well each passage
#             fits its topic (cosine similarity to the topic centre).
# Version 4 = Phase 3 (articles): topics.citations (JSON map from the
#             article's [n] markers to passage ids) and topics.written_at.
# Version 5 = Lessons (v0.6): spreadsheets as a source type ('table'),
#             doc_tables (the real rows/columns of each sheet) and lessons
#             (one automatically designed lesson per topic). Rebuilding the
#             sources table needs foreign keys switched off, which SQLite
#             only allows outside a transaction — see _migrate_v5().
_MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            # Small key/value table holding the schema version itself.
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            # One row per imported file. sha256 = fingerprint of the file's
            # bytes: two identical files share it, which is how exact
            # duplicates are detected without comparing content by hand.
            """
            CREATE TABLE IF NOT EXISTS sources (
                id            INTEGER PRIMARY KEY,
                sha256        TEXT NOT NULL UNIQUE,
                file_name     TEXT NOT NULL,
                original_path TEXT NOT NULL,
                file_type     TEXT NOT NULL CHECK (file_type IN ('pdf','image')),
                size_bytes    INTEGER NOT NULL,
                page_count    INTEGER,
                status        TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','extracting',
                                                'extracted','failed')),
                error         TEXT,
                added_at      TEXT NOT NULL DEFAULT (datetime('now')),
                processed_at  TEXT
            )
            """,
            # Text of each page. ocr_used = 1 when the text came from OCR
            # (scanned page) rather than the PDF's own text layer.
            """
            CREATE TABLE IF NOT EXISTS pages (
                id          INTEGER PRIMARY KEY,
                source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                text        TEXT NOT NULL DEFAULT '',
                ocr_used    INTEGER NOT NULL DEFAULT 0,
                char_count  INTEGER NOT NULL DEFAULT 0,
                UNIQUE (source_id, page_number)
            )
            """,
            # Chunks of page text — the basic unit that gets searched,
            # grouped and cited. content_hash detects repeated passages
            # (e.g. the same paragraph copied into several PDFs).
            # embedding = the meaning-vector (filled in Phase 2).
            # cluster_id = which "same meaning" group it belongs to (Phase 2).
            """
            CREATE TABLE IF NOT EXISTS passages (
                id           INTEGER PRIMARY KEY,
                source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                page_id      INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                page_number  INTEGER NOT NULL,
                ordinal      INTEGER NOT NULL,
                text         TEXT NOT NULL,
                token_count  INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL,
                cluster_id   INTEGER,
                embedding    BLOB
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_passages_source ON passages(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_passages_hash ON passages(content_hash)",
            "CREATE INDEX IF NOT EXISTS idx_passages_cluster ON passages(cluster_id)",
            # Full-text search index over passages (exact words, instant).
            # content='passages' means it indexes the passages table without
            # storing a second copy of the text — saves disk space.
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
                text,
                content='passages',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 2'
            )
            """,
            # Triggers keep the search index in sync automatically whenever
            # passages are added, deleted or edited — no code can forget to.
            """
            CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
                INSERT INTO passages_fts(rowid, text) VALUES (new.id, new.text);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
                INSERT INTO passages_fts(passages_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS passages_au AFTER UPDATE OF text ON passages BEGIN
                INSERT INTO passages_fts(passages_fts, rowid, text)
                VALUES ('delete', old.id, old.text);
                INSERT INTO passages_fts(rowid, text) VALUES (new.id, new.text);
            END
            """,
            # Images: standalone image files and pictures found inside PDFs.
            # ocr_text = words read from the image; description = what the
            # vision model says the diagram shows (makes diagrams searchable).
            """
            CREATE TABLE IF NOT EXISTS images (
                id          INTEGER PRIMARY KEY,
                source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                page_number INTEGER,
                sha256      TEXT NOT NULL,
                ocr_text    TEXT,
                description TEXT
            )
            """,
            # Knowledge Topics: the merged articles that replace reading PDFs.
            # body_markdown holds the article; every claim in it carries
            # passage references so the app can show the exact source.
            """
            CREATE TABLE IF NOT EXISTS topics (
                id            INTEGER PRIMARY KEY,
                slug          TEXT NOT NULL UNIQUE,
                title         TEXT NOT NULL,
                summary       TEXT,
                body_markdown TEXT,
                status        TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft','written','stale')),
                model_used    TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            # Which passages fed which topic. The coverage check is simply:
            # "passages with no row in this table" = not yet covered.
            """
            CREATE TABLE IF NOT EXISTS topic_passages (
                topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                passage_id INTEGER NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
                PRIMARY KEY (topic_id, passage_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tp_passage ON topic_passages(passage_id)",
            # Connections between topics — drawn as lines on the Knowledge Map.
            """
            CREATE TABLE IF NOT EXISTS topic_links (
                from_topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                to_topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                relation      TEXT NOT NULL DEFAULT 'related',
                weight        REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (from_topic_id, to_topic_id, relation)
            )
            """,
            # Disagreements between sources, never silently resolved.
            """
            CREATE TABLE IF NOT EXISTS conflicts (
                id           INTEGER PRIMARY KEY,
                topic_id     INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                description  TEXT NOT NULL,
                passage_a_id INTEGER REFERENCES passages(id) ON DELETE SET NULL,
                passage_b_id INTEGER REFERENCES passages(id) ON DELETE SET NULL,
                resolved     INTEGER NOT NULL DEFAULT 0
            )
            """,
            # Long background jobs (import, distil, write). The window polls
            # this to show progress bars, and a job interrupted by closing the
            # app can resume from where it stopped.
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY,
                kind        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued','running','paused',
                                              'done','failed')),
                progress    INTEGER NOT NULL DEFAULT 0,
                total       INTEGER NOT NULL DEFAULT 0,
                message     TEXT,
                started_at  TEXT,
                finished_at TEXT
            )
            """,
        ],
    ),
    (
        2,
        [
            # Simple key/value store for app preferences. Values are JSON
            # text. Example: key 'watch_folders' → '["C:\\Users\\me\\PDFs"]'.
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            # Files that turned out to be exact copies of a file already in
            # the bank (same SHA-256 fingerprint). Recorded so that:
            #   - the owner can see what was skipped and why, and
            #   - the watched-folder scan doesn't re-fingerprint them every time.
            # Deleting the original source deletes these records too.
            """
            CREATE TABLE IF NOT EXISTS duplicate_files (
                path       TEXT PRIMARY KEY,
                sha256     TEXT NOT NULL,
                source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                size_bytes INTEGER NOT NULL,
                found_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sources_path ON sources(original_path)",
            "CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)",
            "CREATE INDEX IF NOT EXISTS idx_images_sha ON images(sha256)",
        ],
    ),
    (
        3,
        [
            # 1.0 = the passage is exactly on-topic; low values (< 0.45) are
            # shown as "loose fits" for the owner to review.
            "ALTER TABLE topic_passages ADD COLUMN fit REAL NOT NULL DEFAULT 1.0",
            "CREATE INDEX IF NOT EXISTS idx_tp_topic ON topic_passages(topic_id)",
        ],
    ),
    (
        4,
        [
            # {"1": 812, "2": 77, ...}: article marker [1] → passage 812, so
            # every line of a written article can show its exact file + page.
            "ALTER TABLE topics ADD COLUMN citations TEXT",
            "ALTER TABLE topics ADD COLUMN written_at TEXT",
        ],
    ),
]


def _migrate_v5() -> None:
    """
    Schema v5. Two parts:

    1. `sources.file_type` had CHECK (file_type IN ('pdf','image')). SQLite
       can't change a CHECK in place, so the table is rebuilt with 'table'
       allowed (for Excel/CSV). Child tables (pages, passages, images,
       duplicate_files) point at `sources` by name, so the rebuild runs with
       foreign keys OFF — otherwise dropping the old table would cascade-
       delete every page. foreign_key_check confirms nothing is orphaned
       before committing; any problem rolls the whole step back.
    2. New tables doc_tables and lessons.
    """
    conn = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        conn.execute("""
            CREATE TABLE sources_v5 (
                id            INTEGER PRIMARY KEY,
                sha256        TEXT NOT NULL UNIQUE,
                file_name     TEXT NOT NULL,
                original_path TEXT NOT NULL,
                file_type     TEXT NOT NULL CHECK (file_type IN ('pdf','image','table')),
                size_bytes    INTEGER NOT NULL,
                page_count    INTEGER,
                status        TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','extracting','extracted','failed')),
                error         TEXT,
                added_at      TEXT NOT NULL DEFAULT (datetime('now')),
                processed_at  TEXT
            )""")
        conn.execute("INSERT INTO sources_v5 SELECT id, sha256, file_name, original_path, file_type, "
                     "size_bytes, page_count, status, error, added_at, processed_at FROM sources")
        conn.execute("DROP TABLE sources")
        conn.execute("ALTER TABLE sources_v5 RENAME TO sources")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_path ON sources(original_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)")
        # The real grid of each spreadsheet sheet: rows as a JSON list of
        # lists. Lessons draw tables from here — never from AI text — so the
        # numbers shown are always exactly the owner's numbers.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_tables (
                id          INTEGER PRIMARY KEY,
                source_id   INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                name        TEXT NOT NULL,
                rows_json   TEXT NOT NULL
            )""")
        # One designed lesson per topic: spec_json is the validated lesson
        # (steps, visuals, quiz); checks_json records what the fact checker
        # removed, so the owner can see the lesson was verified.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lessons (
                topic_id    INTEGER PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
                spec_json   TEXT NOT NULL,
                checks_json TEXT,
                model_used  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"Upgrade check failed ({len(problems)} broken links); nothing was changed.")
        conn.execute("UPDATE schema_meta SET value = '5' WHERE key = 'schema_version'")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _open() -> sqlite3.Connection:
    """
    Open a raw connection with the settings this app relies on.

    HOW / WHY of each setting:
      - row_factory=Row       → rows can be read by column name (row["title"]).
      - foreign_keys=ON       → deleting a source also deletes its pages,
                                passages etc. (no orphaned leftovers).
      - journal_mode=WAL      → the window can read while a background job
                                writes, without either waiting on the other.
      - synchronous=NORMAL    → safe with WAL and noticeably faster imports.
      - busy_timeout=10000    → wait up to 10 s for a lock instead of erroring.
    """
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    # v0.9 (big libraries): a larger page cache (≈64 MB), temporary sort
    # space in memory and memory-mapped reads (256 MB) make searches and
    # topic pages on a 1,000+ file bank noticeably faster.
    conn.execute("PRAGMA cache_size = -65536")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """
    The way every other module should talk to the database.

    USAGE:  with db.connect() as conn:
                conn.execute(...)
    WHAT:   Opens a connection, commits if the block finished without error,
            rolls back if it raised (so a crash mid-import never leaves
            half-written data), and always closes the connection.
    CALLED BY: server.py now; import/distil modules in later phases.
    """
    conn = _open()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_v6() -> None:
    """
    Schema v6 (KB v0.6.1): `passages.section` — the document part a passage
    belongs to (e.g. "Use Case 7: Insider Data Theft"), so a passage that
    starts at "Step 3" is shown with its context. Filled by chunking v3
    (importer.rechunk_all re-organises existing banks on next start).
    """
    with connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(passages)")}
        if "section" not in cols:
            conn.execute("ALTER TABLE passages ADD COLUMN section TEXT")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '6') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v7() -> None:
    """
    Schema v7 (KB v0.7.0):
      answers       — saved answer pages (Phase 4): question, cited Markdown
                      answer, the numbered sources, fact-check results.
      cards         — flashcards (Phase 5), made from each topic's lesson.
                      `card_key` (a hash of front+back) identifies a card, so
                      review progress survives topic rebuilds and lesson
                      regeneration; topic_id is cleared (not deleted) when a
                      topic disappears.
      card_reviews  — every review (rating 1–4), for streaks and progress.
    """
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                id            INTEGER PRIMARY KEY,
                question      TEXT NOT NULL,
                body_markdown TEXT NOT NULL,
                sources_json  TEXT NOT NULL,
                checks_json   TEXT,
                model_used    TEXT,
                seconds       REAL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id          INTEGER PRIMARY KEY,
                card_key    TEXT NOT NULL UNIQUE,
                topic_id    INTEGER REFERENCES topics(id) ON DELETE SET NULL,
                topic_title TEXT,
                kind        TEXT NOT NULL,
                front       TEXT NOT NULL,
                back        TEXT NOT NULL,
                options     TEXT,
                point_id    INTEGER,
                due         TEXT NOT NULL DEFAULT (date('now')),
                interval    REAL NOT NULL DEFAULT 0,
                ease        REAL NOT NULL DEFAULT 2.5,
                reps        INTEGER NOT NULL DEFAULT 0,
                lapses      INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS card_reviews (
                id          INTEGER PRIMARY KEY,
                card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
                reviewed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )""")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '7') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v8() -> None:
    """
    Schema v8 (KB v0.8.0): topics.kind — 'subject' (grouped by meaning, written
    by AI) or 'data' (one per spreadsheet, calculated by datapages.py);
    topics.checks_json — what the article fact check removed.
    """
    with connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(topics)")}
        if "kind" not in cols:
            conn.execute("ALTER TABLE topics ADD COLUMN kind TEXT NOT NULL DEFAULT 'subject'")
        if "checks_json" not in cols:  # the article's fact-check results (v0.8)
            conn.execute("ALTER TABLE topics ADD COLUMN checks_json TEXT")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '8') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v9() -> None:
    """
    Schema v9 (KB v0.8.1): images.xref — where a picture sits inside its PDF.
    WHY: pictures inside text pages are now read in a SECOND pass after
         every file's text is in, so files become usable in seconds instead
         of waiting for slow picture OCR. A row with xref set and ocr_text
         NULL is "waiting to be read"; the xref lets the importer find the
         picture again later, even after the app was closed (importer.py
         _picture_pass). Idempotent: safe to run on every start.
    """
    with connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)")}
        if "xref" not in cols:
            conn.execute("ALTER TABLE images ADD COLUMN xref INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_pending ON images(source_id) "
                     "WHERE ocr_text IS NULL AND xref IS NOT NULL")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '9') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v10() -> None:
    """
    Schema v10 (KB v0.8.2). Owner: "PDFs not related to cybersecurity should
    be removed automatically" and "files I remove keep coming back".

    1. sources.status may now be 'set_aside' — a file judged NOT about
       cybersecurity (relevance.py). Its text is not kept in the bank, but
       the row stays so the file is never re-imported and the owner can
       press "Keep anyway". SQLite can't change a CHECK in place, so the
       table is rebuilt exactly like _migrate_v5 (foreign keys OFF during
       the swap, foreign_key_check before commit, full rollback on error).
       New columns: relevance_json (the check's result, shown in Library)
       and keep_anyway (1 = the owner overrode the check).
    2. removed_files: every file the owner removed (by fingerprint, path
       and size). Watched-folder scans and folder adds skip these, so a
       removed file stays removed. Picking that exact file again with
       "Add files" brings it back (importer.add_paths).
    Runs only when the CHECK doesn't allow 'set_aside' or 'doc' yet; the
    table part is idempotent.
    """
    conn = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sources'").fetchone()[0]
        conn.execute("""
            CREATE TABLE IF NOT EXISTS removed_files (
                sha256      TEXT NOT NULL,
                path        TEXT NOT NULL,
                size_bytes  INTEGER NOT NULL,
                removed_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (sha256, path)
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_removed_path ON removed_files(path, size_bytes)")
        # Rebuilt when the CHECKs lack 'set_aside' (v0.8.2) or the 'doc' file
        # type (v0.9: Word, PowerPoint, web pages, text and Markdown files).
        if "set_aside" not in sql or "'doc'" not in sql:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN")
            conn.execute("""
                CREATE TABLE sources_v10 (
                    id             INTEGER PRIMARY KEY,
                    sha256         TEXT NOT NULL UNIQUE,
                    file_name      TEXT NOT NULL,
                    original_path  TEXT NOT NULL,
                    file_type      TEXT NOT NULL CHECK (file_type IN ('pdf','image','table','doc')),
                    size_bytes     INTEGER NOT NULL,
                    page_count     INTEGER,
                    status         TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending','extracting','extracted','failed','set_aside')),
                    error          TEXT,
                    added_at       TEXT NOT NULL DEFAULT (datetime('now')),
                    processed_at   TEXT,
                    relevance_json TEXT,
                    keep_anyway    INTEGER NOT NULL DEFAULT 0,
                    title          TEXT,
                    categories     TEXT,
                    replaced_by    INTEGER
                )""")
            # Copy every column both tables have (older banks lack the newer ones).
            old_cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
            new_cols = [r[1] for r in conn.execute("PRAGMA table_info(sources_v10)")]
            common = ", ".join(c for c in new_cols if c in old_cols)
            conn.execute(f"INSERT INTO sources_v10({common}) SELECT {common} FROM sources")
            conn.execute("DROP TABLE sources")
            conn.execute("ALTER TABLE sources_v10 RENAME TO sources")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_path ON sources(original_path)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)")
            problems = conn.execute("PRAGMA foreign_key_check").fetchall()
            if problems:
                raise RuntimeError(f"Upgrade check failed ({len(problems)} broken links); nothing was changed.")
            conn.execute("COMMIT")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '10') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def _migrate_v11() -> None:
    """
    Schema v11 (KB v0.9). New columns on sources (idempotent, every start):
      title       — a readable name read from the file's content, for files
                    named like "1733744110377.pdf" (titles.py). Shown in
                    Library and in citations; the file on disk is untouched.
      categories  — JSON list such as ["SIEM & Detection", "Identity"]
                    (titles.categorise), for the Library filter.
      replaced_by — id of the newer version of this file that took over
                    (importer: "Replace old versions automatically").
    """
    with connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
        for name, kind in (("title", "TEXT"), ("categories", "TEXT"), ("replaced_by", "INTEGER")):
            if name not in cols:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {kind}")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '11') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v12() -> None:
    """
    Schema v12 (KB v0.9.1). New table fact_verdicts (idempotent, every start):
    the local AI's answer for a borderline pair of statements — "are these the
    same fact?" — so each pair is judged once and never asked again.
      key     SHA-1 of the two normalised statements (order-independent)
      verdict SAME | SUBSET | DIFFERENT | CONFLICT
    Used only by facts.py.
    """
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS fact_verdicts (key TEXT PRIMARY KEY, verdict TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '12') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v13() -> None:
    """
    Schema v13 (KB v0.10). New table point_roles (idempotent, every start): what
    the local AI decided about a point — its role (definition / how_it_works /
    step / detection / response / example / note) and what it is about —
    keyed by a hash of the point's text, so a point is analysed once and the
    answer survives topic rebuilds and hand edits. Used only by understand.py.
    """
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS point_roles (key TEXT PRIMARY KEY, role TEXT NOT NULL, about TEXT)")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '13') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _migrate_v14() -> None:
    """
    Schema v14 (KB v0.11). Two new tables for the Chat screen (idempotent,
    every start):
      chats          one row per saved conversation (title, timestamps)
      chat_messages  every turn: role ('user' | 'assistant'), the text, the
                     sources an answer cited (JSON, same shape as `answers`),
                     whether part of it came from general knowledge rather
                     than the owner's files, the model and the seconds taken.
    Messages are deleted with their chat. Used only by chat.py.
    """
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chats ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
            "updated_at TEXT NOT NULL DEFAULT (datetime('now')))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE, "
            "role TEXT NOT NULL, content TEXT NOT NULL, sources_json TEXT, checks_json TEXT, "
            "general INTEGER NOT NULL DEFAULT 0, model_used TEXT, seconds REAL, "
            "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id, id)")
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', '14') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )


def _current_version(conn: sqlite3.Connection) -> int:
    """Return the schema version stored in the file (0 for a brand-new file)."""
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
    ).fetchone()
    if not has_meta:
        return 0
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    return int(row["value"]) if row else 0


def fts5_available() -> bool:
    """
    Check that this Python's SQLite includes FTS5 (full-text search).

    WHY:  Instant word search depends on it. Official Python builds for
          Windows include it, but if it were ever missing we want a clear
          message at startup instead of a confusing crash later.
    CALLED BY: init_db() and system_check.py.
    """
    try:
        probe = sqlite3.connect(":memory:")
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        probe.close()
        return True
    except sqlite3.OperationalError:
        return False


def init_db() -> int:
    """
    Create the database or upgrade it to the latest schema.

    WHEN:    Every engine startup (server.py) and before the benchmark runs.
    HOW:     Reads the stored schema version, then applies every migration
             with a higher version number, in order, inside one transaction
             each. Already-applied steps are skipped.
    RETURNS: The schema version after upgrading.
    RAISES:  RuntimeError if FTS5 is unavailable (search would not work).
    """
    if not fts5_available():
        raise RuntimeError(
            "This Python's SQLite lacks FTS5 full-text search. "
            "Install the official Python from python.org or winget."
        )
    with connect() as conn:
        version = _current_version(conn)
        for target_version, statements in _MIGRATIONS:
            if target_version <= version:
                continue  # already applied on this database
            for sql in statements:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(target_version),),
            )
            version = target_version
    # Migrations that can't run inside a normal transaction.
    if version < 5:
        _migrate_v5()
        version = 5
    if version < 6:
        _migrate_v6()
        version = 6
    if version < 7:
        _migrate_v7()
        version = 7
    _migrate_v8()  # idempotent: also repairs a pre-release bank missing a v8 column
    _migrate_v9()  # idempotent (v0.8.1: pictures read in a second pass)
    _migrate_v10()  # idempotent (v0.8.2: set-aside files, removed-files list)
    _migrate_v11()  # idempotent (v0.9: titles, categories, replaced versions)
    _migrate_v12()  # idempotent (v0.9.1: AI answers for repeated-statement pairs)
    _migrate_v13()  # idempotent (v0.10: AI roles of points)
    _migrate_v14()  # idempotent (v0.11: saved chats)
    return 14


def stats() -> dict:
    """
    Count what the knowledge bank currently holds.

    WHAT:    Returns totals for the dashboard (sources, images, OCR'd pages,
             duplicate files skipped, repeated passages merged, pages,
             passages, topics, conflicts) plus coverage = % of passages that belong
             to at least one topic (the "nothing missed" number).
    CALLED BY: server.py → GET /stats → shown on the app's home screen.
    """
    with connect() as conn:
        def count(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        passages = count("SELECT COUNT(*) FROM passages")
        covered = count("SELECT COUNT(DISTINCT passage_id) FROM topic_passages")
        return {
            "sources": count("SELECT COUNT(*) FROM sources"),
            "images": count("SELECT COUNT(*) FROM images"),
            "ocr_pages": count("SELECT COUNT(*) FROM pages WHERE ocr_used = 1"),
            "duplicates_skipped": count("SELECT COUNT(*) FROM duplicate_files"),
            "repeats_merged": count(
                "SELECT COUNT(*) - COUNT(DISTINCT cluster_id) FROM passages WHERE cluster_id IS NOT NULL"
            ),
            "pages": count("SELECT COUNT(*) FROM pages"),
            "passages": passages,
            "topics": count("SELECT COUNT(*) FROM topics"),
            "open_conflicts": count("SELECT COUNT(*) FROM conflicts WHERE resolved = 0"),
            "coverage_percent": round(100.0 * covered / passages, 1) if passages else 0.0,
            "schema_version": _current_version(conn),
        }


def get_setting(key: str, default=None):
    """
    Read one app preference (stored as JSON). Returns `default` if unset.
    CALLED BY: importer.py (watched folders).
    """
    import json
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    """Save one app preference as JSON (insert or overwrite)."""
    import json
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
