"""
topicedit.py — the owner's own changes to topics (v0.9).

WHAT:  rename(topic, title)           — new name (article and lesson kept)
       merge(target, others)          — the other topics' points move into
                                        the target; the others are removed
       move_points(topic, points, to) — chosen points go to another topic
       split(topic, points, title)    — chosen points become a NEW topic
       Every point is a "repeat group" (passages.cluster_id, or the passage
       itself) exactly as the Source points tab shows it, so moving a point
       moves every copy of it.

WHY:   Owner chose "edit topics by hand" (15 Nov 2026): automatic grouping is
       good but not perfect, and until now the only fix was "Rebuild topics"
       for the whole bank.

HOW:   Only topic_passages (which point belongs to which topic) and topics
       rows change; passages are never touched, so search, citations and
       flashcards keep working. Topics whose content changed are marked
       'stale' and their lesson is cleared — "Write remaining" rewrites
       exactly those. A topic left with no points is removed. Links between
       topics (Related) are kept; links to removed topics go with them.
       Spreadsheet (data) topics are calculated, so they can be renamed but
       not merged, split or have points moved.

WHEN:  POST /topics/rename, /topics/merge, /topics/move, /topics/split
       (server.py), from the topic page (Topics.jsx).

NOTE:  "Rebuild topics" regroups everything from scratch and replaces hand
       edits — the Topics screen says so next to the button.

CONNECTED TO: db.py (topics, topic_passages, lessons), distill.py
       (_slugify, topic_detail), Topics.jsx.
"""

from . import db


def _is_data(conn, topic_id: int) -> bool:
    row = conn.execute("SELECT kind FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return bool(row and row["kind"] == "data")


def _changed(conn, topic_id: int) -> None:
    """Content changed: article must be rewritten, lesson rebuilt."""
    left = conn.execute("SELECT COUNT(*) FROM topic_passages WHERE topic_id = ?", (topic_id,)).fetchone()[0]
    if left == 0:
        conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        return
    conn.execute("UPDATE topics SET status = CASE WHEN status = 'written' THEN 'stale' ELSE status END, "
                 "updated_at = datetime('now') WHERE id = ?", (topic_id,))
    conn.execute("DELETE FROM lessons WHERE topic_id = ?", (topic_id,))


def _passages_of(conn, topic_id: int, point_ids: list[int]) -> list[int]:
    """All passages in this topic that belong to the given points."""
    if not point_ids:
        return []
    marks = ",".join("?" * len(point_ids))
    return [r[0] for r in conn.execute(
        f"SELECT p.id FROM topic_passages tp JOIN passages p ON p.id = tp.passage_id "
        f"WHERE tp.topic_id = ? AND COALESCE(p.cluster_id, p.id) IN ({marks})", (topic_id, *point_ids))]


def _move(conn, from_id: int, to_id: int, passage_ids: list[int]) -> int:
    for pid in passage_ids:
        fit = conn.execute("SELECT fit FROM topic_passages WHERE topic_id = ? AND passage_id = ?",
                           (from_id, pid)).fetchone()
        conn.execute("DELETE FROM topic_passages WHERE topic_id = ? AND passage_id = ?", (from_id, pid))
        conn.execute("INSERT OR IGNORE INTO topic_passages(topic_id, passage_id, fit) VALUES (?, ?, ?)",
                     (to_id, pid, fit[0] if fit else 0.5))
    return len(passage_ids)


def rename(topic_id: int, title: str) -> dict:
    title = " ".join((title or "").split())[:120]
    if not title:
        return {"ok": False, "message": "Type a name first."}
    with db.connect() as conn:
        n = conn.execute("UPDATE topics SET title = ?, updated_at = datetime('now') WHERE id = ?",
                         (title, topic_id)).rowcount
    return {"ok": bool(n), "message": "Renamed." if n else "Topic not found."}


def merge(target_id: int, other_ids: list[int]) -> dict:
    others = [o for o in dict.fromkeys(other_ids) if o != target_id]
    if not others:
        return {"ok": False, "message": "Choose a topic to merge in."}
    with db.connect() as conn:
        if any(_is_data(conn, t) for t in [target_id, *others]):
            return {"ok": False, "message": "Spreadsheet topics are calculated and can't be merged."}
        moved = 0
        for o in others:
            pids = [r[0] for r in conn.execute("SELECT passage_id FROM topic_passages WHERE topic_id = ?", (o,))]
            moved += _move(conn, o, target_id, pids)
            # keep the merged topic's links on the target
            conn.execute("UPDATE OR IGNORE topic_links SET from_topic_id = ? WHERE from_topic_id = ?", (target_id, o))
            conn.execute("UPDATE OR IGNORE topic_links SET to_topic_id = ? WHERE to_topic_id = ?", (target_id, o))
            conn.execute("DELETE FROM topic_links WHERE from_topic_id = to_topic_id")
            conn.execute("DELETE FROM topics WHERE id = ?", (o,))
        _changed(conn, target_id)
    return {"ok": True, "message": f"Merged — {moved} passages moved. The article will be rewritten by "
                                   f"\"Write remaining\"."}


def move_points(topic_id: int, point_ids: list[int], to_topic_id: int) -> dict:
    if topic_id == to_topic_id:
        return {"ok": False, "message": "That is the same topic."}
    with db.connect() as conn:
        if _is_data(conn, topic_id) or _is_data(conn, to_topic_id):
            return {"ok": False, "message": "Spreadsheet topics are calculated; their points can't be moved."}
        if not conn.execute("SELECT 1 FROM topics WHERE id = ?", (to_topic_id,)).fetchone():
            return {"ok": False, "message": "Topic not found."}
        moved = _move(conn, topic_id, to_topic_id, _passages_of(conn, topic_id, point_ids))
        _changed(conn, to_topic_id)
        _changed(conn, topic_id)
    return {"ok": bool(moved), "message": f"Moved {len(point_ids)} point(s)." if moved else "Nothing to move."}


def split(topic_id: int, point_ids: list[int], title: str) -> dict:
    from .distill import _slugify
    title = " ".join((title or "").split())[:120]
    if not title:
        return {"ok": False, "message": "Name the new topic first."}
    with db.connect() as conn:
        if _is_data(conn, topic_id):
            return {"ok": False, "message": "Spreadsheet topics are calculated and can't be split."}
        pids = _passages_of(conn, topic_id, point_ids)
        if not pids:
            return {"ok": False, "message": "Tick the points that should form the new topic."}
        slug = base = _slugify(title) or "topic"
        n = 2
        while conn.execute("SELECT 1 FROM topics WHERE slug = ?", (slug,)).fetchone():
            slug, n = f"{base}-{n}", n + 1
        cur = conn.execute("INSERT INTO topics(slug, title, summary, status, kind) VALUES (?, ?, ?, 'draft', 'subject')",
                           (slug, title, f"Split from another topic by hand ({len(point_ids)} points)."))
        new_id = cur.lastrowid
        _move(conn, topic_id, new_id, pids)
        conn.execute("INSERT OR IGNORE INTO topic_links(from_topic_id, to_topic_id, relation, weight) "
                     "VALUES (?, ?, 'related', 0.5)", (new_id, topic_id))
        _changed(conn, topic_id)
    return {"ok": True, "topic_id": new_id,
            "message": f"New topic \"{title}\" made from {len(point_ids)} point(s). \"Write remaining\" writes it."}


def topic_list() -> list[dict]:
    """Small list for the 'move to / merge with' pickers."""
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, title, kind FROM topics ORDER BY title COLLATE NOCASE")]
