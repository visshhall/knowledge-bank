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


def search(query: str, limit: int = 40) -> dict:
    """
    Run a search. RETURNS {"query", "total", "results": [{passage_id,
    source_id, file_name, page_number, snippet}]}, best matches first
    (ranked by BM25, the standard relevance formula built into FTS5).
    """
    fts = _to_fts_query(query or "")
    if not fts:
        return {"query": query, "total": 0, "results": []}
    with db.connect() as conn:
        try:
            rows = conn.execute(
                f"""
                SELECT p.id AS passage_id, p.source_id, s.file_name, p.page_number,
                       snippet(passages_fts, 0, '{MARK_START}', '{MARK_END}', '…', 28) AS snippet
                FROM passages_fts
                JOIN passages p ON p.id = passages_fts.rowid
                JOIN sources s  ON s.id = p.source_id
                WHERE passages_fts MATCH ?
                ORDER BY bm25(passages_fts)
                LIMIT ?
                """,
                (fts, limit),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH ?", (fts,)
            ).fetchone()[0]
        except Exception:
            # A query FTS5 still can't parse: report no results, never crash.
            return {"query": query, "total": 0, "results": []}
    return {"query": query, "total": int(total), "results": [dict(r) for r in rows]}
