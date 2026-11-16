"""
insights.py — v0.20 the numbers behind the Insights screen (knowledge map, coverage heatmap, mistake trends, timeline).

WHAT:  Read-only summaries, nothing is written. all_insights(weeks) returns:
         map      one node per category (files, passages, learned pages, coverage score, whether the app added it) and
                  one link per pair of categories that share files (weight = shared files), so related areas sit together;
         heatmap  per category and per week (last `weeks`, this week last): files added and times answers cited it;
         mistakes per week: how many answers went wrong by kind (thumbs-down, Regenerate, Correct, facts removed),
                  how many answers were given, the share that went wrong, and the weeks lessons were added;
         timeline newest-first list of what the app did on its own (pages learned, categories and sub-categories added,
                  lessons added, topics it queued, sites it stopped reading) plus a 30-day activity series.
WHY:   The owner asked for "visualization, animations, everything" so that patterns the app finds can be seen, not just
       listed. This module only prepares the data; Insights.jsx draws and animates it.
WHEN:  Called when the Insights screen opens and every 15 s while it stays open (cheap queries, one pass each).
LIMITS: weeks are rolling 7-day blocks ending now (week 0 = the last 7 days). Citations are counted from saved answers, so a
       category shows "used" only after answers citing its files were saved.
CONNECTED TO: db.py (sources, chat_messages, mistake_log, lesson_rules, learn_topics, taxonomy, site_stats),
       coverage.py (scores, citation parsing), taxonomy.py (categories), importer.py (_cited_source_ids),
       server.py (GET /insights/all), Insights.jsx.
"""
from __future__ import annotations

import datetime as _dt
import json

from . import coverage, db, taxonomy

MAX_WEEKS = 26
TIMELINE_LIMIT = 60


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _when(ts: str | None) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("T", " ")[:19])
    except ValueError:
        return None


def _bucket(ts: str | None, weeks: int, now: _dt.datetime) -> int | None:
    """0 = the last 7 days, 1 = the 7 before that … None when older than `weeks` or unreadable."""
    t = _when(ts)
    if not t:
        return None
    idx = max(0, (now - t).days) // 7
    return idx if idx < weeks else None


def _cats(raw: str | None) -> list[str]:
    try:
        return [c for c in json.loads(raw or "[]") if isinstance(c, str)]
    except ValueError:
        return []


# ---------------------------------------------------------------------------

def knowledge_map() -> dict:
    cov = {c["category"]: c for c in coverage.categories()}
    tax = {c["name"]: c for c in taxonomy.status()["categories"]}
    nodes = []
    for name, t in tax.items():
        c = cov.get(name, {})
        nodes.append({"id": name, "files": t["files"], "passages": c.get("passages", 0), "learned": c.get("learned", 0),
                      "score": c.get("score", 0), "weak": bool(c.get("weak")), "grown": t["grown"],
                      "subs": [s["name"] for s in t["subs"]]})
    pairs: dict[tuple[str, str], int] = {}
    with db.connect() as conn:
        for r in conn.execute("SELECT categories FROM sources WHERE status = 'extracted' AND replaced_by IS NULL"):
            cs = sorted(set(_cats(r["categories"])))
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    pairs[(a, b)] = pairs.get((a, b), 0) + 1
    links = [{"a": a, "b": b, "weight": w} for (a, b), w in sorted(pairs.items(), key=lambda x: -x[1])]
    return {"nodes": nodes, "links": links}


def heatmap(weeks: int, now: _dt.datetime) -> dict:
    names = taxonomy.all_top()
    added = {n: [0] * weeks for n in names}
    used = {n: [0] * weeks for n in names}
    with db.connect() as conn:
        cat_of: dict[int, list[str]] = {}
        for r in conn.execute("SELECT id, categories, added_at FROM sources WHERE status = 'extracted' AND replaced_by IS NULL"):
            cs = _cats(r["categories"])
            cat_of[r["id"]] = cs
            b = _bucket(r["added_at"], weeks, now)
            if b is not None:
                for c in cs:
                    if c in added:
                        added[c][b] += 1
        from .importer import _cited_source_ids
        for r in conn.execute("SELECT sources_json, created_at FROM chat_messages WHERE role = 'assistant' "
                              "AND sources_json IS NOT NULL AND sources_json != '{}'"):
            b = _bucket(r["created_at"], weeks, now)
            if b is None:
                continue
            for sid in _cited_source_ids(r["sources_json"]):
                for c in cat_of.get(int(sid), []):
                    if c in used:
                        used[c][b] += 1
    # Oldest week first, so the picture reads left (past) to right (now).
    rows = [{"category": n, "added": added[n][::-1], "used": used[n][::-1],
             "total": sum(added[n]) + sum(used[n])} for n in names]
    rows.sort(key=lambda r: -r["total"])
    return {"weeks": weeks, "rows": rows}


def mistakes(weeks: int, now: _dt.datetime) -> dict:
    kinds = ("down", "regen", "correct", "removed")
    series = {k: [0] * weeks for k in kinds}
    answers = [0] * weeks
    lessons = []
    with db.connect() as conn:
        for r in conn.execute("SELECT kind, created_at FROM mistake_log"):
            b = _bucket(r["created_at"], weeks, now)
            if b is not None and r["kind"] in series:
                series[r["kind"]][b] += 1
        for r in conn.execute("SELECT created_at FROM chat_messages WHERE role = 'assistant'"):
            b = _bucket(r["created_at"], weeks, now)
            if b is not None:
                answers[b] += 1
        for r in conn.execute("SELECT text, created_at, status, verdict FROM lesson_rules"):
            b = _bucket(r["created_at"], weeks, now)
            if b is not None:
                lessons.append({"week": weeks - 1 - b, "text": r["text"], "status": r["status"], "verdict": r["verdict"]})
    total = [sum(series[k][i] for k in kinds) for i in range(weeks)]
    rate = [round(total[i] / answers[i], 3) if answers[i] else None for i in range(weeks)]
    return {"weeks": weeks, "kinds": {k: v[::-1] for k, v in series.items()}, "answers": answers[::-1],
            "total": total[::-1], "rate": rate[::-1], "lessons": lessons}


def timeline(now: _dt.datetime) -> dict:
    events: list[dict] = []
    with db.connect() as conn:
        for r in conn.execute(
                "SELECT date(added_at) AS d, COALESCE(learn_topic, '') AS topic, COUNT(*) AS n FROM sources "
                "WHERE origin = 'learned' GROUP BY d, topic ORDER BY d DESC LIMIT 40"):
            events.append({"at": r["d"] + " 12:00:00", "kind": "learned",
                           "text": f"Read {r['n']} web page{'s' if r['n'] != 1 else ''}" + (f" about “{r['topic']}”" if r["topic"] else "")})
        for r in conn.execute("SELECT name, parent, created_at FROM taxonomy WHERE origin = 'auto' ORDER BY id DESC LIMIT 40"):
            events.append({"at": r["created_at"], "kind": "category",
                           "text": f"Added sub-category “{r['name']}” under {r['parent']}" if r["parent"] else f"Added category “{r['name']}”"})
        for r in conn.execute("SELECT text, source, created_at FROM lesson_rules ORDER BY id DESC LIMIT 40"):
            events.append({"at": r["created_at"], "kind": "lesson", "text": f"Learned a lesson: {r['text']}"})
        for r in conn.execute("SELECT topic, origin, created_at FROM learn_topics WHERE origin IN ('gap', 'coverage') "
                              "ORDER BY id DESC LIMIT 40"):
            why = "to fill a gap in the library" if r["origin"] == "coverage" else "from a question your files could not answer"
            events.append({"at": r["created_at"], "kind": "topic", "text": f"Queued “{r['topic']}” {why}"})
        for r in conn.execute("SELECT host, updated_at FROM site_stats WHERE blocked = 1 AND manual = 0 ORDER BY updated_at DESC LIMIT 20"):
            events.append({"at": r["updated_at"], "kind": "site", "text": f"Stopped reading {r['host']} (mostly thin pages)"})
        daily = {}
        since = (now - _dt.timedelta(days=29)).strftime("%Y-%m-%d")
        for table, col, key, where in (("sources", "added_at", "files", "(origin IS NULL OR origin != 'learned') AND replaced_by IS NULL"),
                                       ("sources", "added_at", "learned", "origin = 'learned' AND replaced_by IS NULL"),
                                       ("mistake_log", "created_at", "mistakes", "1 = 1")):
            for r in conn.execute(f"SELECT date({col}) AS d, COUNT(*) AS n FROM {table} WHERE {where} AND date({col}) >= ? GROUP BY d", (since,)):
                daily.setdefault(r["d"], {})[key] = r["n"]
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    days = []
    for i in range(29, -1, -1):
        d = (now - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        v = daily.get(d, {})
        days.append({"date": d, "files": v.get("files", 0), "learned": v.get("learned", 0), "mistakes": v.get("mistakes", 0)})
    return {"events": events[:TIMELINE_LIMIT], "days": days}


def all_insights(weeks: int = 12) -> dict:
    weeks = max(4, min(MAX_WEEKS, int(weeks or 12)))
    now = _now()
    return {"weeks": weeks, "map": knowledge_map(), "heatmap": heatmap(weeks, now),
            "mistakes": mistakes(weeks, now), "timeline": timeline(now)}
