"""
learn.py — Phase 5 Learn mode: flashcards with spaced repetition and progress.

WHAT:  - sync_cards(): turns every topic's lesson into flashcards — no extra
         AI work, the lesson is already fact-checked:
           quiz question  → "quiz" card (front = question, back = correct
                            answer, options kept for multiple choice)
           lesson step    → "concept" card (front = step title, back = its
                            short explanation)
         A card is identified by a hash of its front + back (card_key), so
         review progress survives topic rebuilds and lesson regeneration.
         Cards whose lesson changed and were never reviewed are tidied away;
         reviewed ones are kept.
       - session(): the cards due today (oldest first), plus up to
         NEW_PER_DAY new cards a day; or all cards of one topic to practise.
       - review(card, rating): schedules the card's next showing with a
         simplified SM-2 algorithm (the one behind Anki/SuperMemo):
           1 Again → again today, ease −0.2
           2 Hard  → interval × 1.2, ease −0.15
           3 Good  → 1 day, then 3 days, then interval × ease
           4 Easy  → longer than Good, ease +0.15
       - summary(): due today, new available, reviewed today, day streak,
         last 14 days of activity, and mastery per topic (a card counts as
         mastered once its interval reaches 21 days).
WHY:   Reading once doesn't make knowledge stick; reviewing just before you
       would forget does. The owner asked for the app to "teach like a
       teacher" — this is the part that makes it last.
WHEN:  GET /learn/summary, GET /learn/session, POST /learn/review
       (server.py), from the Learn screen (Learn.jsx). sync_cards() also runs
       after each lesson is built (lessons.build_lesson).
CONNECTED TO: db.py (cards, card_reviews, lessons, topics — schema v7),
       lessons.py (lesson specs), Learn.jsx.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from . import db

NEW_PER_DAY = 15      # new cards introduced per day (keeps reviews manageable)
MASTERED_DAYS = 21    # interval at which a card counts as mastered
SKIP_STEP_PREFIXES = ("From your spreadsheet", "From your document", "Try it")  # interactive/table steps make poor cards


def _today() -> dt.date:
    return dt.date.today()


def _key(kind: str, front: str, back: str) -> str:
    return hashlib.sha1(f"{kind}|{front.strip().lower()}|{back.strip().lower()}".encode()).hexdigest()


def _cards_from_lesson(spec: dict) -> list[dict]:
    """Derive cards from one lesson spec (steps + quiz)."""
    cites = spec.get("citations") or {}
    out = []
    for step in spec.get("steps", []):
        title, text = (step.get("title") or "").strip(), (step.get("text") or "").strip()
        if not title or len(text) < 25 or title.startswith(SKIP_STEP_PREFIXES):
            continue
        n = (step.get("cites") or [None])[0]
        out.append({"kind": "concept", "front": title, "back": text[:500], "options": None,
                    "passage": cites.get(str(n)) if n is not None else None})
    for item in spec.get("quiz", []):
        opts = item.get("options") or []
        a = item.get("answer")
        if not item.get("q") or not isinstance(a, int) or not (0 <= a < len(opts)):
            continue
        out.append({"kind": "quiz", "front": item["q"].strip(), "back": str(opts[a]).strip(),
                    "options": json.dumps(opts), "passage": cites.get(str(item.get("cite")))})
    return out


def sync_cards() -> int:
    """
    Make sure every lesson's cards exist and point at their current topic.
    RETURNS the number of cards created.
    """
    created = 0
    with db.connect() as conn:
        lessons = conn.execute(
            "SELECT l.topic_id, l.spec_json, t.title FROM lessons l JOIN topics t ON t.id = l.topic_id").fetchall()
        current: set[str] = set()
        for row in lessons:
            spec = json.loads(row["spec_json"])
            for c in _cards_from_lesson(spec):
                key = _key(c["kind"], c["front"], c["back"])
                current.add(key)
                point = None
                if c["passage"]:
                    r = conn.execute("SELECT COALESCE(cluster_id, id) AS pid FROM passages WHERE id = ?",
                                     (c["passage"],)).fetchone()
                    point = r["pid"] if r else None
                cur = conn.execute(
                    "INSERT OR IGNORE INTO cards(card_key, topic_id, topic_title, kind, front, back, options, point_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, row["topic_id"], row["title"], c["kind"], c["front"], c["back"], c["options"], point))
                if cur.rowcount:
                    created += 1
                else:
                    conn.execute("UPDATE cards SET topic_id = ?, topic_title = ?, point_id = ? WHERE card_key = ?",
                                 (row["topic_id"], row["title"], point, key))
        # Cards no lesson produces any more: keep the ones with progress.
        for r in conn.execute("SELECT id, card_key, reps FROM cards").fetchall():
            if r["card_key"] not in current and r["reps"] == 0:
                conn.execute("DELETE FROM cards WHERE id = ?", (r["id"],))
    return created


def _card(r) -> dict:
    return {"id": r["id"], "kind": r["kind"], "front": r["front"], "back": r["back"],
            "options": json.loads(r["options"]) if r["options"] else None,
            "topic_id": r["topic_id"], "topic_title": r["topic_title"], "point_id": r["point_id"],
            "reps": r["reps"], "interval": r["interval"], "ease": r["ease"],
            "preview": {str(k): _preview(r, k) for k in (1, 2, 3, 4)}}


def _schedule(reps: int, interval: float, ease: float, rating: int) -> tuple[int, float, float]:
    """SM-2-style next (reps, interval days, ease) for a rating 1–4."""
    if rating == 1:
        return 0, 0.0, max(1.3, ease - 0.2)
    if rating == 2:
        return reps + 1, max(1.0, interval * 1.2), max(1.3, ease - 0.15)
    if rating == 3:
        nxt = 1.0 if reps == 0 else 3.0 if reps == 1 else interval * ease
        return reps + 1, nxt, ease
    nxt = 3.0 if reps == 0 else max(4.0, interval * ease * 1.3)
    return reps + 1, nxt, ease + 0.15


def _preview(r, rating: int) -> str:
    """What each button means for this card, e.g. "now", "1 day", "2 weeks"."""
    _, days, _ = _schedule(r["reps"], r["interval"], r["ease"], rating)
    d = round(days)
    if d == 0:
        return "now"
    if d < 14:
        return f"{d} day{'s' if d > 1 else ''}"
    if d < 60:
        return f"{round(d / 7)} weeks"
    return f"{round(d / 30)} months"


def session(topic_id: int | None = None, limit: int = 30) -> dict:
    """Cards to study now: due reviews + today's new cards, or one topic's cards."""
    sync_cards()
    today = _today().isoformat()
    with db.connect() as conn:
        if topic_id:
            rows = conn.execute("SELECT * FROM cards WHERE topic_id = ? ORDER BY due, id LIMIT ?",
                                (topic_id, limit)).fetchall()
        else:
            due = conn.execute("SELECT * FROM cards WHERE reps > 0 AND due <= ? ORDER BY due, id LIMIT ?",
                               (today, limit)).fetchall()
            new_today = conn.execute(
                "SELECT COUNT(DISTINCT r.card_id) FROM card_reviews r JOIN cards c ON c.id = r.card_id "
                "WHERE date(r.reviewed_at) = ? AND c.reps <= 1", (today,)).fetchone()[0]
            room = max(0, min(NEW_PER_DAY - new_today, limit - len(due)))
            new = conn.execute("SELECT * FROM cards WHERE reps = 0 ORDER BY topic_id, id LIMIT ?",
                               (room,)).fetchall()
            rows = list(due) + list(new)
    return {"cards": [_card(r) for r in rows]}


def review(card_id: int, rating: int) -> dict:
    """Record a review and schedule the card. RETURNS the card's new state."""
    if rating not in (1, 2, 3, 4):
        return {"ok": False, "message": "Rating must be 1–4."}
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not r:
            return {"ok": False, "message": "Card not found."}
        reps, interval, ease = _schedule(r["reps"], r["interval"], r["ease"], rating)
        due = (_today() + dt.timedelta(days=round(interval))).isoformat()
        conn.execute("UPDATE cards SET reps = ?, interval = ?, ease = ?, due = ?, lapses = lapses + ? WHERE id = ?",
                     (reps, interval, ease, due, 1 if rating == 1 else 0, card_id))
        conn.execute("INSERT INTO card_reviews(card_id, rating) VALUES (?, ?)", (card_id, rating))
    return {"ok": True, "due": due, "interval": interval, "again": rating == 1}


def summary() -> dict:
    """Totals, streak, 14-day activity and per-topic mastery for the Learn screen."""
    sync_cards()
    today = _today()
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        due = conn.execute("SELECT COUNT(*) FROM cards WHERE reps > 0 AND due <= ?", (today.isoformat(),)).fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM cards WHERE reps = 0").fetchone()[0]
        days = {r["d"]: r["n"] for r in conn.execute(
            "SELECT date(reviewed_at) AS d, COUNT(*) AS n FROM card_reviews GROUP BY d")}
        topics = conn.execute(
            """SELECT topic_id, topic_title, COUNT(*) AS cards,
                      SUM(CASE WHEN interval >= ? THEN 1 ELSE 0 END) AS mastered,
                      SUM(CASE WHEN reps > 0 AND interval < ? THEN 1 ELSE 0 END) AS learning,
                      SUM(CASE WHEN reps = 0 THEN 1 ELSE 0 END) AS fresh,
                      AVG(MIN(interval / ?, 1.0)) AS strength
               FROM cards WHERE topic_id IS NOT NULL GROUP BY topic_id ORDER BY topic_title""",
            (MASTERED_DAYS, MASTERED_DAYS, float(MASTERED_DAYS))).fetchall()
        mastered = conn.execute("SELECT COUNT(*) FROM cards WHERE interval >= ?", (MASTERED_DAYS,)).fetchone()[0]
    # Streak: consecutive days with reviews, ending today (or yesterday if
    # today's reviews haven't started yet).
    streak, d = 0, today
    if today.isoformat() not in days:
        d = today - dt.timedelta(days=1)
    while d.isoformat() in days:
        streak += 1
        d -= dt.timedelta(days=1)
    activity = [{"date": (today - dt.timedelta(days=i)).isoformat(),
                 "reviews": days.get((today - dt.timedelta(days=i)).isoformat(), 0)} for i in range(13, -1, -1)]
    return {"total": total, "due": due, "new": new, "new_today": min(new, NEW_PER_DAY),
            "reviewed_today": days.get(today.isoformat(), 0), "streak": streak, "mastered": mastered,
            "activity": activity,
            "topics": [{"topic_id": t["topic_id"], "title": t["topic_title"], "cards": t["cards"],
                        "mastered": t["mastered"], "learning": t["learning"], "new": t["fresh"],
                        "strength": round(t["strength"] or 0, 3)} for t in topics]}
