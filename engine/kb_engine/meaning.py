"""
meaning.py — "search by meaning" plus exact words, for the quick search
(Ctrl+K) box.

WHAT:  quick_search(q) → the best passages for a question or phrase, each
       with its file, page, document part (section) and the topic it
       belongs to, so the app can open that topic directly.
       Two searches run together and are blended:
         1. Meaning: the question is turned into a meaning-vector by the
            local embedding model (the same nomic-embed-text that built the
            topics, with its "search_query: " prefix) and compared with
            every passage's stored vector (cosine similarity, numpy).
         2. Words: the existing exact-word search (search.py, SQLite FTS5).
       A passage found by both ranks highest. If the AI engine isn't
       running, word search alone is returned and the reply says so.
WHY:   Phase 4 — the owner wants to ask things the way he thinks of them
       ("how do I stop a hacked RDP account") and land on "Lock the user
       account …" even though no word matches. Word search alone can't do
       that; meaning search alone can miss exact IDs like "4625". Blending
       gives both.
WHEN:  GET /search/quick?q=… (server.py), called as the owner types in the
       quick-search box (debounced in QuickSearch.jsx).
COST:  One embedding call (~50 ms on the GPU) + one matrix product. The
       passage vectors are kept in memory and reloaded only when the number
       of embedded passages changes (after Build topics / imports).
CONNECTED TO: db.py (passages.embedding, topic_passages, topics),
       search.py (word search), ollama_client.py (embed), config.py
       (EMBED_MODEL), distill.py (fills the vectors), QuickSearch.jsx.
"""

from __future__ import annotations

import threading

from . import config, db, ollama_client, search

QUERY_PREFIX = "search_query: "  # nomic-embed-text's prefix for questions
MIN_MEANING = 0.45               # weaker meaning matches are not shown
_cache: dict = {"key": None, "ids": None, "mat": None}
_lock = threading.Lock()


def _vectors():
    """All passage vectors as (ids, unit-length matrix), cached until they change."""
    import numpy as np  # loaded only when meaning search is first used

    with db.connect() as conn:
        key = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM passages WHERE embedding IS NOT NULL").fetchone()
        key = (key[0], key[1])
        with _lock:
            if _cache["key"] == key:
                return _cache["ids"], _cache["mat"]
        rows = conn.execute("SELECT id, embedding FROM passages WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return None, None
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    mat = mat / np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
    with _lock:
        _cache.update(key=key, ids=ids, mat=mat)
    return ids, mat


def _details(passage_ids: list[int]) -> dict[int, dict]:
    """File, page, section, text and topic for each passage id."""
    if not passage_ids:
        return {}
    marks = ",".join("?" * len(passage_ids))
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT p.id, COALESCE(p.cluster_id, p.id) AS point_id, p.text, p.page_number, p.section, s.file_name,
                       t.id AS topic_id, t.title AS topic_title
                FROM passages p JOIN sources s ON s.id = p.source_id
                LEFT JOIN topic_passages tp ON tp.passage_id = p.id
                LEFT JOIN topics t ON t.id = tp.topic_id
                WHERE p.id IN ({marks})""",
            passage_ids,
        ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def quick_search(query: str, limit: int = 12) -> dict:
    """
    RETURNS {"query", "mode": "meaning+words" | "words", "results": [
      {passage_id, file_name, page_number, section, topic_id, topic_title,
       snippet, score, matched: ["meaning", "words"]}]}.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return {"query": q, "mode": "words", "results": []}

    scores: dict[int, float] = {}
    matched: dict[int, set] = {}
    snippets: dict[int, str] = {}

    # 1. Words (always available).
    words = search.search(q, limit=30)["results"]
    for rank, r in enumerate(words):
        pid = r["passage_id"]
        scores[pid] = scores.get(pid, 0.0) + 0.55 * (1 - rank / 30)
        matched.setdefault(pid, set()).add("words")
        snippets[pid] = r["snippet"]

    # 2. Meaning (needs the embedding model running).
    mode = "words"
    try:
        if ollama_client.is_running() and ollama_client.has_model(config.EMBED_MODEL):
            ids, mat = _vectors()
            if ids is not None:
                import numpy as np

                vec = np.asarray(ollama_client.embed(config.EMBED_MODEL, [QUERY_PREFIX + q])[0], dtype=np.float32)
                vec /= max(float(np.linalg.norm(vec)), 1e-9)
                sims = mat @ vec
                top = np.argsort(-sims)[:30]
                for i in top:
                    if sims[i] < MIN_MEANING:
                        break
                    pid = int(ids[i])
                    scores[pid] = scores.get(pid, 0.0) + float(sims[i])
                    matched.setdefault(pid, set()).add("meaning")
                mode = "meaning+words"
    except Exception:
        mode = "words"  # the AI engine stopped mid-way: words still work

    best = sorted(scores, key=lambda p: -scores[p])[:limit]
    info = _details(best)
    results = []
    for pid in best:
        d = info.get(pid)
        if not d:
            continue
        text = " ".join(d["text"].split())
        results.append({
            "passage_id": pid, "point_id": d["point_id"], "file_name": d["file_name"], "page_number": d["page_number"],
            "section": d["section"], "topic_id": d["topic_id"], "topic_title": d["topic_title"],
            "snippet": snippets.get(pid) or (text[:220] + ("…" if len(text) > 220 else "")),
            "score": round(scores[pid], 3), "matched": sorted(matched[pid]),
        })
    return {"query": q, "mode": mode, "results": results}
