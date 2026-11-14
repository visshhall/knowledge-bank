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

from . import chunking, config, db, lessons, ollama_client

# Sized from the owner's benchmark (RTX 3050, 4 GB): a 4,096-token window
# keeps qwen3.5:4b fully on the GPU (11.6 tokens/s). 8 points × ≤800 chars ≈
# 1,600 tokens in + ≤1,300 out fits that window; 1,300 avoids the cut-off
# endings seen in the benchmark (which allowed only 700).
#
# v0.8 SPEED-UP (owner: "article writing is very slow"). v0.5–v0.7 used 8
# points per request and up to 12 note-taking passes per topic, each allowed
# 1,300 tokens — about 4 calls / 8–10 minutes for a typical 17-point topic.
# Now: the 12 most central points go straight into ONE writing request
# (12 × ≤650 chars ≈ 2,100 tokens in + ≤950 out, still inside 4,096), and
# only extra points beyond that get short note passes (≤450 tokens each, at
# most 3). Typical topic: 1–2 calls, ~2–3 minutes including its lesson.
# Every point stays visible under "Source points" either way.
POINTS_PER_REQUEST = 12     # points read directly by the writing request
POINT_MAX_CHARS = 650       # each point is trimmed to this for the prompt
NOTE_BATCH = 12             # extra points per note-taking pass
MAX_NOTE_BATCHES = 3        # → up to 48 points read per topic (most central first)
NUM_CTX = 4096              # model window for writing requests
MAX_OUTPUT = 950            # cap on the article's length (tokens)
NOTES_MAX_OUTPUT = 450      # cap on each note-taking pass

SYSTEM = (
    "You write study articles for a cybersecurity analyst's private knowledge bank. "
    "Use ONLY facts from the numbered SOURCE POINTS. Never invent event IDs, MITRE IDs, "
    "commands, product names or numbers. Copy queries and commands exactly. "
    "End every bullet and every sentence with the source markers it came from, e.g. [2] or [1][4]. "
    "Write plainly and briefly. No introductions like 'This article…'."
)

ARTICLE_PROMPT = """Write a concise knowledge-bank article (about 300-450 words) titled "{title}" from the SOURCE POINTS below.

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
Extract the distinct facts as at most 8 short bullets. Keep queries, commands, event IDs and MITRE IDs exactly.
End each bullet with its source markers, e.g. [3].

SOURCE POINTS:
{points}
"""

_lock = threading.Lock()
_running = False
_cancel = threading.Event()
_priority: list[int] = []  # topics asked for with "Write this topic now" (v0.8)
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


def start(rewrite_all: bool = False, only_topic: int | None = None, focus: int | None = None) -> dict:
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
    threading.Thread(target=_run, args=(rewrite_all, only_topic, focus), name="kb-writer", daemon=True).start()
    return {"ok": True, "message": "Working."}


def write_now(topic_id: int) -> dict:
    """
    "Write this topic now" (v0.8): if the writer is running, this topic is
    done next; otherwise the writer starts with just this topic.
    """
    with db.connect() as conn:
        kind = conn.execute("SELECT kind FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if not kind:
        return {"ok": False, "message": "Topic not found."}
    if kind[0] == "data":
        return {"ok": False, "message": "This topic is calculated from a spreadsheet — nothing to write."}
    with _lock:
        if _running:
            if topic_id not in _priority:
                _priority.insert(0, topic_id)
            return {"ok": True, "message": "Next up: this topic."}
    return start(rewrite_all=False, only_topic=None, focus=topic_id)


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
    Each: {"passage_id", "text"} — text carries its document part (with_section).
    """
    rows = conn.execute(
        """
        SELECT p.id, p.cluster_id, p.text, p.section FROM topic_passages tp
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
        points.append({"passage_id": key, "text": chunking.with_section(r["text"], r["section"])})
    return points



def _numbered(points: list[dict], start: int) -> str:
    """Format points as [n] blocks for the prompt, numbering from `start`."""
    return "\n\n".join(
        f"[{start + i}] {p['text'][:POINT_MAX_CHARS]}" for i, p in enumerate(points)
    )


def _ask(prompt: str, limit: int = MAX_OUTPUT, live: bool = False) -> str:
    """One writing request. live=True streams the text into the job status
    ("live"), so the Topics screen shows the article being written."""
    on_text = (lambda t: _set(live=t)) if live else None
    r = ollama_client.generate(write_model(), prompt, system=SYSTEM, temperature=0.15,
                               num_ctx=NUM_CTX, num_predict=limit, on_text=on_text)
    return r.text


def _check_article(article: str, sources: list[str]) -> tuple[str, dict]:
    """
    Accuracy pass (v0.8), the same rules as answers and lessons: every
    number, event ID, technique ID, IP and query line must appear in the
    topic's sources. Unsupported sentences and query lines are removed; an
    emptied section or code block is dropped. RETURNS (article, checks).
    """
    ck = lessons.Checker(sources)
    out, in_code, code = [], False, []
    for line in article.split("\n"):
        if line.strip().startswith("```"):
            if in_code:
                if code:
                    out += [fence, *code, line]
                in_code, code = False, []
            else:
                in_code, fence, code = True, line, []
            continue
        if in_code:
            if not line.strip() or ck.ok_code(line):
                code.append(line)
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        prefix = re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
        head = prefix.group(0) if prefix else ""
        kept = ck.clean_text(line[len(head):], max_len=4000)
        if kept:
            out.append(head + kept)
    # Drop headings left with nothing under them.
    final = []
    for k, line in enumerate(out):
        if line.lstrip().startswith("## "):
            rest = next((l for l in out[k + 1:] if l.strip()), "")
            if not rest or rest.lstrip().startswith("## "):
                continue
        final.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(final)).strip()
    return text, {"removed": ck.removed, "removed_count": len(ck.removed)}


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
    # Filler the model adds despite instructions (v0.8): "Event IDs: N/A",
    # and a "Where sources disagree" section that only says there are none.
    text = "\n".join(l for l in text.split("\n")
                     if not re.search(r":\**\s*(N/?A|none|not specified|not provided)\b", l, re.I))
    text = re.sub(r"## Where sources disagree\s*\n(?:(?!## ).)*?(no (?:direct )?(?:contradictions|disagreements)|"
                  r"do not contradict|are consistent|consistently)(?:(?!## ).)*", "", text,
                  flags=re.I | re.S)
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
        points = _topic_points(conn, topic_id)[: POINTS_PER_REQUEST + NOTE_BATCH * MAX_NOTE_BATCHES]
    if not points:
        return False

    citations = {str(i + 1): p["passage_id"] for i, p in enumerate(points)}
    direct = points[:POINTS_PER_REQUEST]
    material = _numbered(direct, 1)
    extra = points[POINTS_PER_REQUEST:]
    if extra:
        notes: list[str] = []
        for b in range(0, len(extra), NOTE_BATCH):
            if _cancel.is_set():
                return False
            batch = extra[b:b + NOTE_BATCH]
            first = POINTS_PER_REQUEST + b + 1
            _set(message=f"Reading extra points {first}–{first + len(batch) - 1} of {len(points)}")
            notes.append(_ask(NOTES_PROMPT.format(title=t["title"], points=_numbered(batch, first)),
                              limit=NOTES_MAX_OUTPUT))
        material += "\n\nNOTES FROM MORE POINTS:\n" + "\n".join(notes)

    _set(message="Writing the article", live="", live_topic=topic_id)
    raw = _ask(ARTICLE_PROMPT.format(title=t["title"], points=material), live=True)
    article = _clean_article(raw, {int(k) for k in citations})
    _set(message="Checking every fact against the sources")
    article, checks = _check_article(article, [p["text"] for p in points])
    _set(live=None, live_topic=None)
    if len(article) < 40:
        return False
    with db.connect() as conn:
        conn.execute(
            "UPDATE topics SET body_markdown = ?, citations = ?, status = 'written', checks_json = ?, "
            "model_used = ?, written_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (article, json.dumps(citations), json.dumps(checks), write_model(), topic_id),
        )
    return True


def _run(rewrite_all: bool, only_topic: int | None = None, focus: int | None = None) -> None:
    global _running
    try:
        if not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
        if not ollama_client.has_model(write_model()):
            raise RuntimeError(f"The writing model {write_model()} isn't downloaded. Download it from Setup.")
        ollama_client.clear_gpu_except(write_model())   # whole 4 GB for the writer
        # v0.8.2: the first time a model writes, measure whether forcing every
        # layer onto the graphics card is faster, and keep the faster way.
        _set(message="Checking the graphics card speed (first time only, about a minute)…")
        from . import gpu
        gpu.tune_once(write_model())
        with db.connect() as conn:
            if only_topic is not None:
                todo = [only_topic]
            elif focus is not None:
                todo = [focus]
            else:
                # Spreadsheet ("data") topics are calculated, never AI-written.
                where = "WHERE t.kind != 'data'" if rewrite_all else \
                    "WHERE t.kind != 'data' AND (t.status != 'written' OR t.id NOT IN (SELECT topic_id FROM lessons))"
                todo = [r["id"] for r in conn.execute(
                    f"""SELECT t.id FROM topics t LEFT JOIN topic_passages tp ON tp.topic_id = t.id
                        {where} GROUP BY t.id ORDER BY COUNT(tp.passage_id) DESC"""
                )]
        _set(total=len(todo))
        n = 0
        while todo:
            if _cancel.is_set():
                break
            # A topic the owner asked for jumps the queue.
            with _lock:
                wanted = _priority.pop(0) if _priority else None
            if wanted is not None:
                if wanted in todo:
                    todo.remove(wanted)
                else:
                    _set(total=_state["total"] + 1)
                tid = wanted
            else:
                tid = todo.pop(0)
            n += 1
            with db.connect() as conn:
                title = conn.execute("SELECT title FROM topics WHERE id = ?", (tid,)).fetchone()
            _set(current=title["title"] if title else None, message="Reading the points")
            try:
                with db.connect() as conn:
                    written = conn.execute("SELECT status FROM topics WHERE id = ?", (tid,)).fetchone()
                if only_topic is None and (rewrite_all or wanted is not None or not written
                                           or written["status"] != "written"):
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
