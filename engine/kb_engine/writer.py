"""
writer.py — Phase 3: writes one clear, structured article per topic.

WHAT:  A background job ("Write articles") that, for every topic without an
       article, turns its points into a readable study page:

           ## Overview          2–4 plain sentences
           ## Key points        short bullets
           ## How it works      numbered steps (attack flow / process)
           ## Detection         data sources, event IDs, what to look for
           ## Queries           KQL / SPL copied exactly, in code blocks
           ## MITRE ATT&CK      technique IDs with names
           ## Response          what to do when it fires
           ## Where sources disagree

       Sections the sources don't support are left out. Every statement ends
       with citation markers like [3], which the app turns into clickable
       chips showing the exact file and page.

       Big topics (more points than fit in one request on a 4 GB GPU) are
       handled in two passes: batches of points are first boiled down to
       cited notes, then the notes are written up as one article — so every
       point is read, not just the first few.

WHY:   The owner's core request: don't make me read raw PDF text; give me
       one clean, organised page per subject, with no repeats and nothing
       missed, where every line can be traced to its source. (14 Nov 2026:
       raw passages were "one large boring box" — this is the fix.)

WHEN:  When the owner presses "Write articles" on the Topics screen
       (server.py → POST /write/start). Takes ~30–90 s per topic on the
       RTX 3050 with the 4B model, so a large library is an overnight job.
       Each finished article is saved immediately; closing the app loses at
       most the article in progress, and the next run continues where it
       stopped. "Cancel" stops after the current article.

       v0.6: after each article, lessons.build_lesson() designs the topic's
       visual lesson in the same job. Topics that already have an article
       but no lesson get only the lesson.

CONNECTED TO: db.py (topics, topic_passages, passages, sources, settings,
       lessons), ollama_client.py (generate), config.py (WRITE model),
       lessons.py (visual lessons), distill.py (topic detail reads the
       article), server.py, app/src/Topics.jsx.
"""

import json
import re
import threading
import time

from . import config, db, lessons, ollama_client

# Sized from the owner's benchmark (RTX 3050, 4 GB): a 4,096-token window
# keeps qwen3.5:4b fully on the GPU (11.6 tokens/s). 8 points × ≤800 chars ≈
# 1,600 tokens in + ≤1,300 out fits that window; 1,300 avoids the cut-off
# endings seen in the benchmark (which allowed only 700).
POINTS_PER_REQUEST = 8      # points sent per AI request
POINT_MAX_CHARS = 800       # each point is trimmed to this for the prompt
MAX_BATCHES = 12            # up to 96 points read per topic (most central first)
NUM_CTX = 4096              # model window for writing requests
MAX_OUTPUT = 1300           # cap on each answer's length (tokens)

SYSTEM = (
    "You write study articles for a cybersecurity analyst's private knowledge bank. "
    "Use ONLY facts from the numbered SOURCE POINTS. Never invent event IDs, MITRE IDs, "
    "commands, product names or numbers. Copy queries and commands exactly. "
    "End every bullet and every sentence with the source markers it came from, e.g. [2] or [1][4]. "
    "Write plainly and briefly. No introductions like 'This article…'."
)

ARTICLE_PROMPT = """Write a knowledge-bank article titled "{title}" from the SOURCE POINTS below.

Use these Markdown sections, in this order, and LEAVE OUT any section the points don't support:
## Overview
2-4 short sentences.
## Key points
- 3-8 bullets
## How it works
1. numbered steps, only if the points describe a process or attack flow
## Detection
- data sources, event IDs, fields and signals to watch
## Queries
```kql
copy each query exactly as written (use ```spl for Splunk)
```
## MITRE ATT&CK
- T1234.001 – technique name
## Response
- what to do when it is detected
## Where sources disagree
- only if two points contradict each other; say which says what

SOURCE POINTS:
{points}
"""

NOTES_PROMPT = """These SOURCE POINTS are part of the topic "{title}".
Extract every distinct fact as short bullets. Keep queries, commands, event IDs and MITRE IDs exactly.
End each bullet with its source markers, e.g. [3].

SOURCE POINTS:
{points}
"""

_lock = threading.Lock()
_running = False
_cancel = threading.Event()
_state = {"state": "idle", "done": 0, "total": 0, "current": None, "message": "",
          "started_at": None, "model": None}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def write_model() -> str:
    """
    Model used for articles: the owner's choice if saved (after the
    benchmark), otherwise the fast model, which fits the 4 GB GPU.
    """
    return db.get_setting("write_model") or config.FAST_MODEL


def status() -> dict:
    with _lock:
        snap = dict(_state)
    with db.connect() as conn:
        snap["written"] = conn.execute("SELECT COUNT(*) FROM topics WHERE status = 'written'").fetchone()[0]
        snap["topics"] = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        snap["lessons"] = conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    snap["write_model"] = write_model()
    return snap


def start(rewrite_all: bool = False, only_topic: int | None = None) -> dict:
    """
    Begin writing: missing articles and lessons (default), everything
    (rewrite_all), or just one topic's lesson (only_topic — the
    "Regenerate lesson" button).
    """
    global _running
    with _lock:
        if _running:
            return {"ok": False, "message": "The writer is busy. Try again when it finishes."}
        _running = True
    _cancel.clear()
    _set(state="running", done=0, total=0, current=None, message="Starting…",
         started_at=time.time(), model=write_model())
    threading.Thread(target=_run, args=(rewrite_all, only_topic), name="kb-writer", daemon=True).start()
    return {"ok": True, "message": "Working."}


def cancel() -> dict:
    if _state["state"] != "running":
        return {"ok": True, "message": "Nothing to cancel."}
    _cancel.set()
    _set(message="Stopping after the current article…")
    return {"ok": True, "message": "Stopping."}


# ---------------------------------------------------------------------------

def _topic_points(conn, topic_id: int) -> list[dict]:
    """
    The topic's distinct points (one per repeat group), most central first.
    Each: {"passage_id", "text"}.
    """
    rows = conn.execute(
        """
        SELECT p.id, p.cluster_id, p.text FROM topic_passages tp
        JOIN passages p ON p.id = tp.passage_id
        WHERE tp.topic_id = ? ORDER BY tp.fit DESC
        """,
        (topic_id,),
    ).fetchall()
    seen: set[int] = set()
    points: list[dict] = []
    for r in rows:
        key = r["cluster_id"] or r["id"]
        if key in seen:
            continue
        seen.add(key)
        points.append({"passage_id": key, "text": r["text"]})
    return points


def _numbered(points: list[dict], start: int) -> str:
    """Format points as [n] blocks for the prompt, numbering from `start`."""
    return "\n\n".join(
        f"[{start + i}] {p['text'][:POINT_MAX_CHARS]}" for i, p in enumerate(points)
    )


def _ask(prompt: str) -> str:
    r = ollama_client.generate(write_model(), prompt, system=SYSTEM, temperature=0.15,
                               num_ctx=NUM_CTX, num_predict=MAX_OUTPUT)
    return r.text


def _clean_article(text: str, valid: set[int]) -> str:
    """
    Tidy the model's Markdown: drop a leading title line (the app shows the
    title), remove citation markers that point nowhere, and trim stray
    whitespace. Unknown markers are removed rather than trusted.
    """
    text = re.sub(r"^\s*#\s+.*\n", "", text.strip())
    text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)          # "force ." → "force."
    if text.count("```") % 2 == 1:                          # answer cut off inside a query
        text += "\n```"
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write_topic(topic_id: int) -> bool:
    """
    Write and save one topic's article. RETURNS True if saved.

    HOW:  ≤ POINTS_PER_REQUEST points → one request. More → each batch is
          condensed to cited notes (numbers stay global), then one final
          request writes the article from all notes.
    """
    with db.connect() as conn:
        t = conn.execute("SELECT id, title FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not t:
            return False
        points = _topic_points(conn, topic_id)[: POINTS_PER_REQUEST * MAX_BATCHES]
    if not points:
        return False

    citations = {str(i + 1): p["passage_id"] for i, p in enumerate(points)}
    if len(points) <= POINTS_PER_REQUEST:
        material = _numbered(points, 1)
    else:
        notes: list[str] = []
        for b in range(0, len(points), POINTS_PER_REQUEST):
            if _cancel.is_set():
                return False
            batch = points[b:b + POINTS_PER_REQUEST]
            _set(message=f"Reading points {b + 1}–{b + len(batch)} of {len(points)}")
            notes.append(_ask(NOTES_PROMPT.format(title=t["title"], points=_numbered(batch, b + 1))))
        material = "\n".join(notes)

    _set(message="Writing the article")
    article = _clean_article(_ask(ARTICLE_PROMPT.format(title=t["title"], points=material)),
                             {int(k) for k in citations})
    if len(article) < 40:
        return False
    with db.connect() as conn:
        conn.execute(
            "UPDATE topics SET body_markdown = ?, citations = ?, status = 'written', "
            "model_used = ?, written_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (article, json.dumps(citations), write_model(), topic_id),
        )
    return True


def _run(rewrite_all: bool, only_topic: int | None = None) -> None:
    global _running
    try:
        if not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
        if not ollama_client.has_model(write_model()):
            raise RuntimeError(f"The writing model {write_model()} isn't downloaded. Download it from Setup.")
        ollama_client.clear_gpu_except(write_model())   # whole 4 GB for the writer
        with db.connect() as conn:
            if only_topic is not None:
                todo = [only_topic]
            else:
                where = "" if rewrite_all else \
                    "WHERE t.status != 'written' OR t.id NOT IN (SELECT topic_id FROM lessons)"
                todo = [r["id"] for r in conn.execute(
                    f"""SELECT t.id FROM topics t LEFT JOIN topic_passages tp ON tp.topic_id = t.id
                        {where} GROUP BY t.id ORDER BY COUNT(tp.passage_id) DESC"""
                )]
        _set(total=len(todo))
        for n, tid in enumerate(todo, start=1):
            if _cancel.is_set():
                break
            with db.connect() as conn:
                title = conn.execute("SELECT title FROM topics WHERE id = ?", (tid,)).fetchone()
            _set(current=title["title"] if title else None, message="Reading the points")
            try:
                with db.connect() as conn:
                    written = conn.execute("SELECT status FROM topics WHERE id = ?", (tid,)).fetchone()
                if only_topic is None and (rewrite_all or not written or written["status"] != "written"):
                    write_topic(tid)
                if not _cancel.is_set():
                    _set(message="Designing the lesson")
                    lessons.build_lesson(tid, write_model())
            except ollama_client.OllamaError as exc:
                _set(message=f"Skipped one topic: {exc}")
            _set(done=n)
        _set(state="idle" if _cancel.is_set() else "done", current=None,
             message="Stopped." if _cancel.is_set() else
             ("Lesson ready." if only_topic is not None else "All articles and lessons ready."))
    except Exception as exc:
        _set(state="error", current=None, message=str(exc))
    finally:
        with _lock:
            _running = False
