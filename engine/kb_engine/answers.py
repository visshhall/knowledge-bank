"""
answers.py — Phase 4 "answer pages": ask a question, get a short written
answer built ONLY from your own files, every sentence cited.

WHAT:  ask(question) starts a background job:
         1. Find the best passages for the question (meaning.quick_search:
            meaning + exact words), up to MAX_SOURCES distinct ones.
         2. Number them [1]…[n] and ask the local writing model (qwen3.5:4b)
            to answer using only those, citing each sentence.
         3. Fact-check the answer with the same Checker as lessons: every
            number, technique ID, IP, event ID and query line must appear in
            the cited sources, or the sentence is removed (and counted).
         4. Save it (table `answers`, schema v7) so recent answers can be
            reopened instantly without asking the AI again.
       status() reports progress; recent() lists saved answers; get(id)
       returns one.
WHY:   The owner wants the bank to answer like a colleague who has read all
       his PDFs — but a local 4B model can invent things, so the answer is
       limited to retrieved passages, cited, and checked. If nothing
       relevant is found, it says so instead of guessing.
WHEN:  POST /answer/ask, GET /answer/status, GET /answers, GET /answer?id
       (server.py), from the Answers screen (Answers.jsx) or the "Write an
       answer" row in Ctrl+K search.
CONNECTED TO: meaning.py (retrieval), lessons.Checker (fact check),
       writer.write_model / ollama_client.generate (the AI), db.py
       (`answers` table, passages, sources, topics), chunking.with_section.
"""

from __future__ import annotations

import json
import re
import threading
import time

from . import chunking, db, meaning, ollama_client
from .lessons import Checker

MAX_SOURCES = 8        # passages given to the model (fits a 4,096-token window)
SOURCE_CHARS = 900     # each passage is cut to this length
NUM_CTX = 4096
MAX_OUTPUT = 700       # a focused answer, not an article

SYSTEM = (
    "You answer questions for a cybersecurity analyst using ONLY the numbered SOURCES from his own "
    "documents. If the sources don't contain the answer, reply exactly: NOT IN SOURCES. "
    "Never invent event IDs, MITRE IDs, commands, tools or numbers. Copy queries exactly. "
    "End every sentence and bullet with the source markers it came from, e.g. [2] or [1][3]. "
    "Be direct and practical; use short bullets or numbered steps when the answer is a procedure."
)

PROMPT = """QUESTION: {question}

SOURCES:
{sources}

Write the answer in Markdown (no title). Start with a one or two sentence direct answer, then details if useful."""

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def status() -> dict:
    with _lock:
        return dict(_state)


def ask(question: str) -> dict:
    """Start answering in the background. RETURNS {"ok", "message"}."""
    q = " ".join((question or "").split())
    if len(q) < 4:
        return {"ok": False, "message": "Type a question first."}
    with _lock:
        if _state.get("state") == "running":
            return {"ok": False, "message": "Still answering the previous question."}
        _state.clear()
        _state.update(state="running", question=q, stage="Finding the best passages…", started_at=time.time())
    threading.Thread(target=_run, args=(q,), name="kb-answer", daemon=True).start()
    return {"ok": True, "message": "Answering."}


def _sources(question: str) -> list[dict]:
    """Best distinct passages for the question, with file/page/topic details."""
    hits = meaning.quick_search(question, limit=MAX_SOURCES * 2)["results"]
    seen, out = set(), []
    for h in hits:
        if h["point_id"] in seen:
            continue
        seen.add(h["point_id"])
        out.append(h)
        if len(out) == MAX_SOURCES:
            break
    if not out:
        return []
    marks = ",".join("?" * len(out))
    with db.connect() as conn:
        rows = {r["id"]: r for r in conn.execute(
            f"SELECT p.id, p.text, p.section, p.source_id FROM passages p WHERE p.id IN ({marks})",
            [h["passage_id"] for h in out])}
    for h in out:
        r = rows[h["passage_id"]]
        h["text"] = r["text"]
        h["source_id"] = r["source_id"]
    return out


def _run(question: str) -> None:
    from .writer import write_model  # late import: writer imports lessons → avoids a cycle

    started = time.time()
    try:
        if not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
        sources = _sources(question)
        if not sources:
            raise RuntimeError("Nothing in your files matches this question. Try other words.")
        numbered = "\n\n".join(
            f"[{i}] {chunking.with_section(s['text'], s['section'])[:SOURCE_CHARS]}"
            for i, s in enumerate(sources, start=1))
        model = write_model()
        _set(stage=f"Writing the answer with {model}…")
        r = ollama_client.generate(model, PROMPT.format(question=question, sources=numbered),
                                   system=SYSTEM, temperature=0.1, num_ctx=NUM_CTX, num_predict=MAX_OUTPUT)
        body = r.text.strip()
        not_found = "NOT IN SOURCES" in body.upper()[:60]

        _set(stage="Checking every fact against the sources…")
        ck = Checker([s["text"] for s in sources])
        valid = set(range(1, len(sources) + 1))
        clean_lines = []
        for line in ([] if not_found else body.split("\n")):
            if line.strip().startswith("```") or not line.strip():
                clean_lines.append(line)
                continue
            # Unknown markers are dropped; sentences with unsupported facts removed.
            line = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid else "", line)
            prefix = re.match(r"^\s*(?:[-*]|\d+[.)])\s+|^\s*#+\s+", line)
            head = prefix.group(0) if prefix else ""
            kept = ck.clean_text(line[len(head):], max_len=2000)
            if kept:
                clean_lines.append(head + kept)
        answer = "\n".join(clean_lines).strip()
        answer = re.sub(r"\n{3,}", "\n\n", answer)
        if answer.count("```") % 2 == 1:
            answer += "\n```"
        if not answer:
            answer = ("Your files don't answer this directly. The closest passages are listed below — "
                      "open them to read more.")
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
        src = {str(i): {k: s.get(k) for k in ("passage_id", "point_id", "source_id", "file_name",
                                                "page_number", "section", "topic_id", "topic_title")}
               | {"text": s["text"], "cited": i in cited}
               for i, s in enumerate(sources, start=1)}
        checks = {"removed": ck.removed, "removed_count": len(ck.removed)}
        with db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO answers(question, body_markdown, sources_json, checks_json, model_used, seconds) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (question, answer, json.dumps(src), json.dumps(checks), model, round(time.time() - started, 1)))
            answer_id = cur.lastrowid
        _set(state="done", stage=None, answer_id=answer_id, seconds=round(time.time() - started, 1))
    except Exception as exc:
        _set(state="error", stage=None, message=str(exc))


def get(answer_id: int) -> dict | None:
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM answers WHERE id = ?", (answer_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "question": r["question"], "answer": r["body_markdown"],
            "sources": json.loads(r["sources_json"]), "checks": json.loads(r["checks_json"] or "{}"),
            "model_used": r["model_used"], "seconds": r["seconds"], "created_at": r["created_at"]}


def recent(limit: int = 30) -> dict:
    with db.connect() as conn:
        rows = conn.execute("SELECT id, question, created_at FROM answers ORDER BY id DESC LIMIT ?",
                            (limit,)).fetchall()
    return {"answers": [dict(r) for r in rows]}


def delete(answer_id: int) -> dict:
    with db.connect() as conn:
        conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
    return {"ok": True}
