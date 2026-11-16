"""
glance.py — v0.22 the numbers for the "at a glance" pictures on Overview and Learning.

WHAT:  One read-only summary: files by kind (PDF, image, web page…), your files vs pages read from the web, files per category,
       the last 30 days (files added, web pages read), and three health figures: how much of the library is linked to related
       files (Live learning), how much sits in topics, and how many subjects are well covered.
WHY:   The owner wants pictures first and text as a companion everywhere. Library and Topics draw from data they already load;
       Overview and Learning needed these few extra numbers in one cheap call.
WHEN:  GET /glance/all, polled every 15 s by Overview.jsx and Learning.jsx while open. Writes nothing.
CONNECTED TO: db.py (sources, source_vectors, stats), taxonomy.py (categories), coverage.py (well-covered share), insights.py
       (30-day series), brain.py (pending links), server.py, viz.jsx (draws it).
"""
from __future__ import annotations

from . import brain, coverage, db, insights, taxonomy

KIND_NAMES = {"pdf": "PDF", "image": "Image", "table": "Spreadsheet", "doc": "Document", "web": "Web page", "text": "Text", "docx": "Word"}


def all_glance() -> dict:
    with db.connect() as conn:
        live = "status != 'replaced' AND replaced_by IS NULL"
        kinds = [{"type": r["t"] or "other", "label": KIND_NAMES.get((r["t"] or "other").lower(), (r["t"] or "other").title()), "n": r["n"]}
                 for r in conn.execute(f"SELECT file_type AS t, COUNT(*) AS n FROM sources WHERE {live} GROUP BY file_type ORDER BY n DESC")]
        web = conn.execute(f"SELECT COUNT(*) FROM sources WHERE {live} AND origin = 'learned'").fetchone()[0]
        total = conn.execute(f"SELECT COUNT(*) FROM sources WHERE {live}").fetchone()[0]
        status = {r["status"]: r["n"] for r in conn.execute(f"SELECT status, COUNT(*) AS n FROM sources WHERE {live} GROUP BY status")}
        extracted = conn.execute(f"SELECT COUNT(*) FROM sources WHERE {live} AND status = 'extracted'").fetchone()[0]
        linked = conn.execute("SELECT COUNT(*) FROM source_vectors").fetchone()[0]
    cats = [c for c in taxonomy.status()["categories"] if c["files"] > 0]
    cats.sort(key=lambda c: -c["files"])
    cov = [c for c in coverage.categories() if c["sources"] > 0]
    well = sum(1 for c in cov if not c["weak"])
    stats = db.stats()
    days = insights.timeline(insights._now())["days"]
    return {
        "files": {"total": total, "mine": total - web, "web": web, "kinds": kinds, "status": status},
        "categories": [{"name": c["name"], "files": c["files"], "grown": c["grown"]} for c in cats],
        "daily": [{"date": d["date"], "files": d["files"], "web": d["learned"]} for d in days],
        "health": {"linked_pct": round(100 * linked / extracted) if extracted else 0, "pending_links": brain.pending_count(),
                   "topics_pct": round(stats["coverage_percent"]), "well_covered_pct": round(100 * well / len(cov)) if cov else 0,
                   "subjects": len(cov), "weak": len(cov) - well},
    }
