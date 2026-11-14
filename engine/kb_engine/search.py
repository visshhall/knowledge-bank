"""
search.py — instant exact-word search across every imported passage.

WHAT:  search(query) → the best-matching passages, each with its file name,
       page number and a short snippet with the matched words marked.

WHY:   Lets the owner find anything in the bank the moment it's imported
       (Phase 1), before the AI-written topic pages exist. It uses SQLite's
       built-in FTS5 index (kept up to date automatically by triggers in
       db.py), so results come back in milliseconds even across thousands
       of pages. Phase 4 adds meaning-based search and generated answer
       pages on top of this.

WHEN:  Every time the owner types in the Library search box
       (server.py → GET /search?q=...).

CONNECTED TO: db.py (passages, passages_fts, sources), server.py,
       app/src/Library.jsx.
"""

import re

from . import db

# Characters the window uses to highlight matches. Control characters
# never appear in real text, so they can't clash with document content,
# and the window turns them into highlights without using raw HTML.
MARK_START = "\u0002"
MARK_END = "\u0003"

_TERM = re.compile(r"[\w.\-:/\\]+", re.UNICODE)


def _to_fts_query(query: str) -> str | None:
    """
    Convert what the owner typed into a safe FTS5 query.

    HOW:  Every word becomes a quoted phrase (so characters like - : . in
          "4625", "T1110.001" or "SigninLogs" can't be misread as search
          operators), and all words must appear (AND). A trailing * on the
          last word allows prefix matching while typing ("lateral mov*").
    RETURNS None if there's nothing searchable.
    """
    terms = _TERM.findall(query)
    if not terms:
        return None
    parts = ['"' + t.replace('"', "") + '"' for t in terms]
    if not query.rstrip().endswith((" ", '"')) and len(terms[-1]) >= 2:
        parts[-1] = parts[-1] + "*"
    return " AND ".join(parts)


def _filters(source_id, topic_id, kind, category) -> tuple[str, list]:
    """SQL conditions for the v0.9 search filters (all optional)."""
    where, args = [], []
    if source_id:
        where.append("p.source_id = ?")
        args.append(int(source_id))
    if topic_id:
        where.append("EXISTS (SELECT 1 FROM topic_passages tp WHERE tp.passage_id = p.id AND tp.topic_id = ?)")
        args.append(int(topic_id))
    if kind == "picture":
        where.append("p.text LIKE '[Image on page%'")
    elif kind == "scanned":
        where.append("pg.ocr_used = 1 AND p.text NOT LIKE '[Image on page%'")
    elif kind == "text":
        where.append("pg.ocr_used = 0 AND p.text NOT LIKE '[Image on page%'")
    if category:
        where.append("s.categories LIKE ?")
        args.append(f'%"{category}"%')
    return ("".join(f" AND {w}" for w in where)), args


def _any_word_query(query: str) -> str | None:
    """Fallback when no passage has ALL the words: any of them (OR)."""
    terms = [t for t in _TERM.findall(query) if len(t) >= 2]
    return " OR ".join('"' + t.replace('"', "") + '"' for t in terms) if len(terms) >= 2 else None


def search(query: str, limit: int = 40, source_id: int | None = None, topic_id: int | None = None,
           kind: str | None = None, category: str | None = None) -> dict:
    """
    Run a search. RETURNS {"query", "total", "results": [{passage_id,
    source_id, file_name, page_number, section, snippet, topic_id,
    topic_title}], "partial": bool, "facets": {"files": [...], "topics": [...]}}.

    v0.9 (owner chose "better search"):
      - Filters: one file, one topic, kind of text (typed text / scanned
        page / text read from a picture) and file category.
      - Better ranking: BM25 (the standard relevance formula) is adjusted —
        the exact phrase you typed ranks ×1.6, a match in the document part
        heading or the file's title ×1.25.
      - If no passage has ALL your words, passages with SOME of them are
        shown instead, marked partial=True ("showing close matches").
      - Facets: how many hits each file and topic has, for filter chips.
    """
    fts = _to_fts_query(query or "")
    empty = {"query": query, "total": 0, "results": [], "partial": False, "facets": {"files": [], "topics": []}}
    if not fts:
        return empty
    cond, args = _filters(source_id, topic_id, kind, category)
    sql = f"""
        SELECT p.id AS passage_id, p.source_id, COALESCE(s.title, s.file_name) AS file_name, p.page_number,
               p.section, p.text, bm25(passages_fts) AS rank,
               snippet(passages_fts, 0, '{MARK_START}', '{MARK_END}', '…', 28) AS snippet,
               (SELECT t.id FROM topic_passages tp JOIN topics t ON t.id = tp.topic_id
                 WHERE tp.passage_id = p.id LIMIT 1) AS topic_id,
               (SELECT t.title FROM topic_passages tp JOIN topics t ON t.id = tp.topic_id
                 WHERE tp.passage_id = p.id LIMIT 1) AS topic_title
        FROM passages_fts
        JOIN passages p ON p.id = passages_fts.rowid
        JOIN sources s  ON s.id = p.source_id
        LEFT JOIN pages pg ON pg.id = p.page_id
        WHERE passages_fts MATCH ?{cond}
        ORDER BY bm25(passages_fts)
        LIMIT 300"""
    partial = False
    with db.connect() as conn:
        try:
            rows = [dict(r) for r in conn.execute(sql, (fts, *args)).fetchall()]
            if not rows:
                alt = _any_word_query(query)
                if alt:
                    rows = [dict(r) for r in conn.execute(sql, (alt, *args)).fetchall()]
                    partial = bool(rows)
        except Exception:
            # A query FTS5 still can't parse: report no results, never crash.
            return empty
    phrase = " ".join(_TERM.findall(query.lower()))
    words = [w for w in _TERM.findall(query.lower()) if len(w) >= 3]
    for r in rows:
        score = -float(r["rank"])  # bm25: lower is better → flip
        text = " ".join(r["text"].lower().split())
        if len(phrase.split()) >= 2 and phrase in text:
            score *= 1.6
        head = f"{r['section'] or ''} {r['file_name'] or ''}".lower()
        if words and any(w in head for w in words):
            score *= 1.25
        r["score"] = score
    rows.sort(key=lambda r: -r["score"])
    files: dict = {}
    topics: dict = {}
    for r in rows:
        f = files.setdefault(r["source_id"], {"id": r["source_id"], "name": r["file_name"], "count": 0})
        f["count"] += 1
        if r["topic_id"]:
            t = topics.setdefault(r["topic_id"], {"id": r["topic_id"], "name": r["topic_title"], "count": 0})
            t["count"] += 1
    results = [{k: r[k] for k in ("passage_id", "source_id", "file_name", "page_number", "section",
                                  "snippet", "topic_id", "topic_title")} for r in rows[:limit]]
    return {"query": query, "total": len(rows), "results": results, "partial": partial,
            "facets": {"files": sorted(files.values(), key=lambda f: -f["count"])[:12],
                       "topics": sorted(topics.values(), key=lambda t: -t["count"])[:12]}}
