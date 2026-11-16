"""
brain.py — v0.21 the live learning view: every file and web page becomes a dot, and each new one is related to what is already there.

WHAT:  1. A MEANING-VECTOR PER FILE. The average of a few of its passages (up to 4, spread through the file), made by the
          embedding model (config.EMBED_MODEL, the same one "Build topics" uses; vectors are stored on the passages too, so
          that step reuses them). When the model is not available, a "shared key words" vector is used instead and is
          replaced by the real one later, so the screen works from day one.
       2. LINKS. When a file gets its vector it is compared with every other file (after removing the direction all text
          shares — without this every cybersecurity passage looks 0.7 alike) and joined to its closest matches
          (up to 4, if alike enough). Stored in source_links.
       3. EVENTS. Each first appearance is logged (brain_events) with who it linked to, in the owner's words:
          "‘KQL join cheatsheet’ relates closely to ‘Sentinel analytics rules’ and ‘Detection tuning’". The Brain screen
          animates these arrivals and lists them as text.
       4. A GRAPH for the screen: dots (newest and biggest first, capped), the links among them, and recent events.
WHY:   The owner wanted to SEE the AI being trained: a new dot appears when something new is found and connects to related
       data, and incoming data correlates with what is already there — "more and more visual, text only as a companion".
WHEN:  A background loop (start(), every 15 s) vectorises up to 8 new files or pages per round while the AI is not writing an
       answer; "Link new files now" does up to 60 at once; graph() runs every ~4 s while the Brain screen is open.
LIMITS: only files of the same method are compared (embed with embed, terms with terms), so while old files are being
       upgraded from key words to meaning, some links are missing until the upgrade finishes. Links are made when a file
       first appears; they are not re-worked when later files change the average direction (a full re-link is a rebuild).
CONNECTED TO: db.py (source_vectors, source_links, brain_events — schema v22; passages.embedding), distill.py (same vector
       format, prefix and size limits, reused vectors), ollama_client.py (embed, is_running, has_model), config.py (EMBED_MODEL),
       chat.py (status: pauses while an answer is being written), importer.py/learner.py (create the files), taxonomy.py (tokens,
       categories), server.py (/brain/*, start()), Brain.jsx.
"""
from __future__ import annotations

import json
import math
import threading
import time
import zlib
from collections import Counter

from . import config, db, ollama_client

DOC_PREFIX = "search_document: "     # same as distill.py (the model expects it on stored passages)
EMBED_MAX_CHARS = 2000
SAMPLE_PASSAGES = 4                  # passages averaged into one file vector
TERM_DIMS = 256                      # size of the shared-key-words vector
NEIGHBOURS = 4                       # links per new file
MIN_SIM = {"embed": 0.30, "terms": 0.25}   # centred cosine needed for a link
STRONG, CLOSE = 0.60, 0.42           # wording of a link: "closely" / "related" / "loosely"
LOOP_SECONDS = 15
ROUND_FILES = 8
MAX_NODES = 300
EVENT_LIMIT = 40

np = None                            # numpy loads on first use, like distill.py (a numpy fault must not stop the engine)
_lock = threading.Lock()
_wake = threading.Event()
_started = False
_state = {"message": "Waiting for new files.", "last": None}


def _np():
    global np
    if np is None:
        import numpy
        np = numpy
    return np


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------

def _unit(v):
    v = _np().asarray(v, dtype=_np().float32)
    n = float(_np().linalg.norm(v))
    return v / n if n > 1e-9 else v


def _blob(v) -> bytes:
    return _np().asarray(v, dtype=_np().float32).tobytes()


def _from_blob(b: bytes):
    return _np().frombuffer(b, dtype=_np().float32)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """The embedding model (replaceable in tests)."""
    return ollama_client.embed(config.EMBED_MODEL, [DOC_PREFIX + t[:EMBED_MAX_CHARS] for t in texts])


def embedding_available() -> bool:
    """The embedding model can be used right now (Ollama running, model downloaded, no answer being written)."""
    try:
        from . import chat
        if chat.status().get("state") == "running":
            return False
        return ollama_client.is_running() and ollama_client.has_model(config.EMBED_MODEL)
    except Exception:
        return False


def _sample(conn, sid: int) -> list[dict]:
    rows = conn.execute("SELECT id, text, embedding FROM passages WHERE source_id = ? ORDER BY page_number, ordinal", (sid,)).fetchall()
    if len(rows) <= SAMPLE_PASSAGES:
        return [dict(r) for r in rows]
    step = (len(rows) - 1) / (SAMPLE_PASSAGES - 1)
    return [dict(rows[round(i * step)]) for i in range(SAMPLE_PASSAGES)]


def _terms_vector(title: str, texts: list[str]):
    """Shared-key-words vector: hashed counts of words and word pairs (title counts triple), sub-linear, unit length."""
    from . import taxonomy
    counts: Counter = Counter()
    for weight, text in ((3, title), (1, " ".join(texts))):
        toks = taxonomy._tokens(text)
        for g in toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]:
            counts[zlib.crc32(g.encode()) % TERM_DIMS] += weight
    v = _np().zeros(TERM_DIMS, dtype=_np().float32)
    for k, c in counts.items():
        v[k] = 1 + math.log(c)
    return _unit(v)


def make_vector(sid: int, allow_embed: bool):
    """(method, vector, passages used) for one source, or None when it has no text."""
    with db.connect() as conn:
        samp = _sample(conn, sid)
        row = conn.execute("SELECT COALESCE(title, file_name) AS t FROM sources WHERE id = ?", (sid,)).fetchone()
    if not samp:
        return None
    have = [s for s in samp if s["embedding"]]
    missing = [s for s in samp if not s["embedding"]]
    vecs = [_unit(_from_blob(s["embedding"])) for s in have]
    if missing and allow_embed:
        try:
            new = [_unit(v) for v in _embed_texts([s["text"] for s in missing])]
            with db.connect() as conn:
                conn.executemany("UPDATE passages SET embedding = ? WHERE id = ?", [(_blob(v), s["id"]) for v, s in zip(new, missing)])
            vecs += new
        except Exception:
            pass
    if vecs and len(vecs) * 2 >= len(samp):                          # at least half the sample has real meaning-vectors
        return "embed", _unit(_np().mean(vecs, axis=0)), len(vecs)
    return "terms", _terms_vector(row["t"] if row else "", [s["text"] for s in samp]), len(samp)


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------

def _neighbours(conn, sid: int, method: str, vec) -> list[tuple[int, float]]:
    """Closest other files of the same method, by cosine after removing the shared direction."""
    rows = conn.execute("SELECT v.source_id, v.vec FROM source_vectors v JOIN sources s ON s.id = v.source_id "
                        "WHERE v.method = ? AND v.source_id != ? AND s.status = 'extracted' AND s.replaced_by IS NULL",
                        (method, sid)).fetchall()
    if not rows:
        return []
    ids = [r["source_id"] for r in rows]
    mat = _np().vstack([_from_blob(r["vec"]) for r in rows] + [vec])
    mat = mat - mat.mean(axis=0)
    norms = _np().linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / _np().maximum(norms, 1e-9)
    sims = mat[:-1] @ mat[-1]
    order = _np().argsort(-sims)[:NEIGHBOURS]
    return [(ids[i], float(sims[i])) for i in order if sims[i] >= MIN_SIM[method]]


def process_source(sid: int, allow_embed: bool) -> dict | None:
    """Give one file its vector, links and an event. RETURNS the event detail, or None when it has no text."""
    made = make_vector(sid, allow_embed)
    if not made:
        return None
    method, vec, used = made
    with db.connect() as conn:
        old = conn.execute("SELECT method FROM source_vectors WHERE source_id = ?", (sid,)).fetchone()
        near = _neighbours(conn, sid, method, vec)
        conn.execute("INSERT INTO source_vectors(source_id, method, vec, n_passages) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(source_id) DO UPDATE SET method = excluded.method, vec = excluded.vec, "
                     "n_passages = excluded.n_passages, updated_at = datetime('now')", (sid, method, _blob(vec), used))
        conn.execute("DELETE FROM source_links WHERE a = ? OR b = ?", (sid, sid))
        for other, sim in near:
            a, b = (sid, other) if sid < other else (other, sid)
            conn.execute("INSERT OR REPLACE INTO source_links(a, b, sim) VALUES (?, ?, ?)", (a, b, round(sim, 4)))
        detail = {"method": method, "links": [{"id": o, "sim": round(s, 3)} for o, s in near]}
        if not old:                                                  # an upgrade (terms → embed) is not a new arrival
            conn.execute("INSERT INTO brain_events(source_id, kind, detail_json) VALUES (?, 'new', ?)", (sid, json.dumps(detail)))
    return detail


def _pending(conn, upgrade: bool, limit: int) -> list[int]:
    ids = [r["id"] for r in conn.execute(
        "SELECT s.id FROM sources s LEFT JOIN source_vectors v ON v.source_id = s.id "
        "WHERE s.status = 'extracted' AND s.replaced_by IS NULL AND v.source_id IS NULL ORDER BY s.id DESC LIMIT ?", (limit,))]
    if upgrade and len(ids) < limit:
        ids += [r["id"] for r in conn.execute(
            "SELECT source_id AS id FROM source_vectors WHERE method = 'terms' ORDER BY source_id DESC LIMIT ?", (limit - len(ids),))]
    return ids


def pending_count() -> int:
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM sources s LEFT JOIN source_vectors v ON v.source_id = s.id "
                            "WHERE s.status = 'extracted' AND s.replaced_by IS NULL AND v.source_id IS NULL").fetchone()[0]


def process_pending(limit: int = ROUND_FILES) -> dict:
    """One round: vectorise and link up to `limit` files (new ones first, then upgrade key-word ones when the model is ready)."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "done": 0, "message": "Already linking."}
    done = 0
    try:
        allow = embedding_available()
        with db.connect() as conn:
            ids = _pending(conn, allow, limit)
        for sid in ids:
            if process_source(sid, allow) is not None:
                done += 1
        left = pending_count()
        _state.update(message=(f"Linking new files ({left} waiting)…" if left else "Everything is linked."),
                      last=time.strftime("%H:%M:%S"))
    except Exception as exc:
        _state.update(message=f"Linking paused: {exc}")
        return {"ok": False, "done": done, "message": str(exc)}
    finally:
        _lock.release()
    return {"ok": True, "done": done, "message": _state["message"]}


# ---------------------------------------------------------------------------
# What the screen reads
# ---------------------------------------------------------------------------

def _strength(sim: float) -> str:
    return "closely to" if sim >= STRONG else "to" if sim >= CLOSE else "loosely to"


def _title(row) -> str:
    t = (row["title"] or row["file_name"] or "Untitled").strip()
    return t if len(t) <= 60 else t[:57] + "…"


def _first_cat(raw) -> str:
    try:
        c = json.loads(raw or "[]")
    except ValueError:
        c = []
    return c[0] if c else "Uncategorised"


def _sentence(conn, ev) -> dict:
    s = conn.execute("SELECT title, file_name, origin, categories FROM sources WHERE id = ?", (ev["source_id"],)).fetchone()
    if not s:
        return {}
    detail = json.loads(ev["detail_json"] or "{}")
    links = detail.get("links", [])
    names = []
    for l in links[:3]:
        r = conn.execute("SELECT title, file_name FROM sources WHERE id = ?", (l["id"],)).fetchone()
        if r:
            names.append((_title(r), l["sim"]))
    what = "Read a web page" if s["origin"] == "learned" else "Added a file"
    if names:
        text = f"{what}: “{_title(s)}” relates {_strength(names[0][1])} " + ", ".join(f"“{n}”" for n, _ in names) + "."
    else:
        text = f"{what}: “{_title(s)}” — nothing related yet, so it starts a new area."
    return {"id": ev["id"], "source_id": ev["source_id"], "at": ev["at"], "text": text, "category": _first_cat(s["categories"]),
            "links": [{"id": l["id"], "sim": l["sim"]} for l in links], "learned": s["origin"] == "learned"}


def graph(limit: int = MAX_NODES, since: str | None = None) -> dict:
    """
    The dots, links and recent events for Brain.jsx.
    since = the "now" the screen got last time; dots that first appeared after it have "new": true.
    """
    limit = max(20, min(MAX_NODES, int(limit or MAX_NODES)))
    with db.connect() as conn:
        now = conn.execute("SELECT datetime('now') AS n").fetchone()["n"]
        rows = conn.execute(
            "SELECT s.id, s.title, s.file_name, s.origin, s.categories, v.method, v.created_at, "
            "(SELECT COUNT(*) FROM passages p WHERE p.source_id = s.id) AS passages "
            "FROM source_vectors v JOIN sources s ON s.id = v.source_id WHERE s.status = 'extracted' AND s.replaced_by IS NULL "
            "ORDER BY v.created_at DESC, s.id DESC LIMIT ?", (limit,)).fetchall()
        ids = {r["id"] for r in rows}
        nodes = [{"id": r["id"], "title": _title(r), "category": _first_cat(r["categories"]), "learned": r["origin"] == "learned",
                  "passages": r["passages"], "at": r["created_at"], "method": r["method"],
                  "new": bool(since and r["created_at"] > since)} for r in rows]
        links = [{"a": r["a"], "b": r["b"], "sim": r["sim"]} for r in conn.execute("SELECT a, b, sim FROM source_links")
                 if r["a"] in ids and r["b"] in ids]
        events = [e for e in (_sentence(conn, ev) for ev in conn.execute(
            "SELECT id, source_id, detail_json, at FROM brain_events ORDER BY id DESC LIMIT ?", (EVENT_LIMIT,))) if e]
        methods = {r["method"]: r["n"] for r in conn.execute("SELECT method, COUNT(*) AS n FROM source_vectors GROUP BY method")}
        total = conn.execute("SELECT COUNT(*) FROM source_vectors").fetchone()[0]
    return {"now": now, "nodes": nodes, "links": links, "events": events, "total": total,
            "status": {"pending": pending_count(), "methods": methods, "message": _state["message"],
                       "model_ready": embedding_available(), "model": config.EMBED_MODEL}}


def related(sid: int, limit: int = 8) -> dict:
    """The files most related to one file (for the side panel)."""
    with db.connect() as conn:
        s = conn.execute("SELECT title, file_name, origin, categories FROM sources WHERE id = ?", (sid,)).fetchone()
        if not s:
            return {"ok": False, "message": "Unknown file."}
        rows = conn.execute(
            "SELECT CASE WHEN a = ? THEN b ELSE a END AS other, sim FROM source_links WHERE a = ? OR b = ? ORDER BY sim DESC LIMIT ?",
            (sid, sid, sid, limit)).fetchall()
        out = []
        for r in rows:
            o = conn.execute("SELECT id, title, file_name, origin, categories FROM sources WHERE id = ?", (r["other"],)).fetchone()
            if o:
                out.append({"id": o["id"], "title": _title(o), "category": _first_cat(o["categories"]),
                            "learned": o["origin"] == "learned", "sim": r["sim"], "how": _strength(r["sim"]).replace(" to", "")})
    return {"ok": True, "id": sid, "title": _title(s), "category": _first_cat(s["categories"]), "learned": s["origin"] == "learned",
            "related": out}


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

def _loop() -> None:
    time.sleep(30)
    while True:
        try:
            if pending_count() or _has_terms():
                from . import chat
                if chat.status().get("state") != "running":
                    process_pending(ROUND_FILES)
        except Exception:
            pass
        _wake.wait(LOOP_SECONDS)
        _wake.clear()


def _has_terms() -> bool:
    """Key-word vectors exist and the model is ready now, so they can be upgraded."""
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM source_vectors WHERE method = 'terms' LIMIT 1").fetchone():
            return False
    return embedding_available()


def start() -> None:
    """server.py lifespan: background loop (idle when nothing is new)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="brain", daemon=True).start()
