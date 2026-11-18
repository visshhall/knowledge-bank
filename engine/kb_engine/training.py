"""
training.py — v0.16 "the app learns from how you use it": signals, training examples, dataset export.

WHAT:  1. SIGNALS. Every time the owner reacts to an answer — thumbs up, thumbs down, Copy, Regenerate,
          Edit — the window calls record(). Copy and thumbs-up mean "good"; thumbs-down and Regenerate
          mean "not good"; Edit (he rewrote his question) is neutral. Nothing is asked of him.
       2. EXAMPLES. A good Free-chat answer becomes a training example (his question -> that answer, with
          the persona's instructions as the system text). A CORRECTION — he rewrote the answer with
          "Correct this answer" — becomes an example too and replaces the plain one: it is the best teaching
          signal there is ("the model said X, I wanted Y"). Examples are filtered automatically: too short,
          "files don't cover this" replies, answers whose facts the checker removed, and anything he marked
          down are never kept. He can reject any example in Learning.
       3. EXPORT. export() writes a JSONL dataset (one chat per line, the format fine-tuning tools read) and
          a HOW_TO_FINE_TUNE.md recipe into the data folder. READY_AT good examples is the point where a
          fine-tune is worth trying; the Learning screen says when that is reached.
WHY:   The owner asked for the app to improve by itself apart from him adding data. A model on a 4 GB laptop
       cannot safely rewrite itself, so the app does everything around the training — collects, filters and
       prepares — and the actual fine-tune is a short cloud run he starts (see HOW_TO_FINE_TUNE.md).
       Only Free-chat answers are used: library answers depend on passages attached to the question, which a
       fine-tuned model would not see, so teaching it those answers would teach it to invent.
WHEN:  record() runs when the window reports a reaction (/training/signal) and from chat.undo_last();
       correct() when he saves a corrected answer; export() when he presses "Export dataset".
CONNECTED TO: db.py (tables message_feedback, training_examples — schema v18), chat.py (undo_last calls
       on_undo; messages live in chat_messages), personas.py (the persona text stored with an example),
       server.py (/training/*), Learning.jsx (the screen), config.py (data folder).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json

from . import config, db, mistakes, personas

READY_AT = 300          # good examples before a fine-tune is worth trying
MIN_RESPONSE_CHARS = 40  # shorter answers teach nothing
MAX_TEXT_CHARS = 6000    # an example longer than this is cut out (too long for a small model's training)
SIGNALS = ("up", "down", "copy", "regen", "edit", "correct")


def _message(conn, message_id: int):
    return conn.execute("SELECT id, chat_id, role, content, mode, checks_json FROM chat_messages WHERE id = ?",
                        (message_id,)).fetchone()


def _usable(msg) -> bool:
    """Is this answer worth teaching from? (Free chat only, real text, nothing removed by the fact-checker.)"""
    if not msg or msg["role"] != "assistant" or msg["mode"] != "free":
        return False
    text = (msg["content"] or "").strip()
    if len(text) < MIN_RESPONSE_CHARS or len(text) > MAX_TEXT_CHARS:
        return False
    if text.startswith("Your files don't"):
        return False
    try:
        if (json.loads(msg["checks_json"] or "{}").get("removed_count") or 0) > 0:
            return False
    except ValueError:
        pass
    return True


def _question_for(conn, msg) -> tuple[str, str]:
    """The owner's message this answer replied to, and the persona text that was in force."""
    q = conn.execute("SELECT content FROM chat_messages WHERE chat_id = ? AND id < ? AND role = 'user' "
                     "ORDER BY id DESC LIMIT 1", (msg["chat_id"], msg["id"])).fetchone()
    p = conn.execute("SELECT persona_id FROM chats WHERE id = ?", (msg["chat_id"],)).fetchone()
    system = personas.persona_prompt(p["persona_id"] if p else None)
    return ((q["content"] if q else "").strip(), system)


def _log(conn, message_id, chat_id, signal) -> None:
    conn.execute("INSERT INTO message_feedback(message_id, chat_id, signal) VALUES (?, ?, ?)",
                 (message_id, chat_id, signal))


def record(message_id: int, signal: str) -> dict:
    """
    One reaction to an answer (see _record). A thumbs-down is also a MISTAKE for mistakes.py — logged after the
    database transaction above has been committed, since mistakes.py opens its own connection.
    """
    result = _record(message_id, signal)
    if signal == "down" and result.get("ok"):
        mistakes.log_message("down", message_id)
    return result


def _record(message_id: int, signal: str) -> dict:
    """
    One reaction to an answer. up/copy → keep it as a 'good' example (if it passes the filter and has not
    been marked down); down → drop any example made from it. RETURNS {"ok": True, "example": bool}.
    """
    if signal not in SIGNALS or signal in ("regen", "correct"):
        return {"ok": False, "message": "Unknown reaction."}
    with db.connect() as conn:
        msg = _message(conn, message_id)
        if not msg or msg["role"] != "assistant":
            return {"ok": False, "message": "That answer is not in the chat any more."}
        _log(conn, message_id, msg["chat_id"], signal)
        have = conn.execute("SELECT id, kind FROM training_examples WHERE message_id = ?", (message_id,)).fetchone()
        if signal == "down":
            if have and have["kind"] == "good":
                conn.execute("DELETE FROM training_examples WHERE id = ?", (have["id"],))
            return {"ok": True, "example": False}
        if signal in ("up", "copy") and not have and _usable(msg):
            marked_down = conn.execute("SELECT 1 FROM message_feedback WHERE message_id = ? AND signal = 'down'",
                                       (message_id,)).fetchone()
            if marked_down and signal == "copy":
                return {"ok": True, "example": False}   # a copy does not undo a thumbs-down
            prompt, system = _question_for(conn, msg)
            if prompt:
                conn.execute("INSERT INTO training_examples(message_id, chat_id, kind, system, prompt, response) "
                             "VALUES (?, ?, 'good', ?, ?, ?)",
                             (message_id, msg["chat_id"], system, prompt, msg["content"].strip()))
                return {"ok": True, "example": True}
        return {"ok": True, "example": bool(have)}


def on_undo(chat_id: int, message_id: int | None, reason: str, answer: str = "", mode: str | None = None,
            question: str = "") -> None:
    """
    Called by chat.undo_last() after the newest answer was deleted. 'regen' = he asked again, so the
    answer was not good: log it (also as a mistake for mistakes.py, with the answer text passed in because the
    message no longer exists) and drop its example. 'edit' = he rewrote his question: neutral, just logged.
    """
    if message_id is None:
        return
    with db.connect() as conn:
        _log(conn, message_id, chat_id, "regen" if reason == "regen" else "edit")
        conn.execute("DELETE FROM training_examples WHERE message_id = ?", (message_id,))
    if reason == "regen":
        mistakes.log_raw("regen", chat_id, message_id, mode, question, answer)


def correct(message_id: int, text: str) -> dict:
    """
    He rewrote a Free-chat answer. The chat now shows his version; a 'correction' example (question →
    his version, remembering the model's original) replaces any plain example for that answer.
    """
    text = (text or "").strip()
    if len(text) < 2:
        return {"ok": False, "message": "Write the answer you wanted."}
    if len(text) > MAX_TEXT_CHARS:
        return {"ok": False, "message": "That is too long. Keep a corrected answer under about 6,000 characters."}
    with db.connect() as conn:
        msg = _message(conn, message_id)
        if not msg or msg["role"] != "assistant" or msg["mode"] != "free":
            return {"ok": False, "message": "Only answers from Free chat can be corrected."}
        prompt, system = _question_for(conn, msg)
        if not prompt:
            return {"ok": False, "message": "That answer has no question to go with it."}
        old = conn.execute("SELECT kind, original FROM training_examples WHERE message_id = ?", (message_id,)).fetchone()
        original = old["original"] if old and old["kind"] == "correction" and old["original"] else msg["content"]
        conn.execute("UPDATE chat_messages SET content = ? WHERE id = ?", (text, message_id))
        conn.execute("DELETE FROM training_examples WHERE message_id = ?", (message_id,))
        conn.execute("INSERT INTO training_examples(message_id, chat_id, kind, system, prompt, response, original) "
                     "VALUES (?, ?, 'correction', ?, ?, ?, ?)",
                     (message_id, msg["chat_id"], system, prompt, text, original))
        _log(conn, message_id, msg["chat_id"], "correct")
        chat_id, mode = msg["chat_id"], msg["mode"]
    mistakes.log_raw("correct", chat_id, message_id, mode, prompt, original, text)  # his version = what was wanted
    return {"ok": True}


def status() -> dict:
    """Counts for the Learning screen: signals, examples by kind, and whether a fine-tune is worth trying."""
    with db.connect() as conn:
        sig = {r["signal"]: r["n"] for r in conn.execute(
            "SELECT signal, COUNT(*) AS n FROM message_feedback GROUP BY signal")}
        ex = {(r["kind"], r["status"]): r["n"] for r in conn.execute(
            "SELECT kind, status, COUNT(*) AS n FROM training_examples GROUP BY kind, status")}
    good, corr = ex.get(("good", "new"), 0), ex.get(("correction", "new"), 0)
    rejected = ex.get(("good", "rejected"), 0) + ex.get(("correction", "rejected"), 0)
    usable = good + corr
    return {"signals": {s: sig.get(s, 0) for s in SIGNALS}, "good": good, "corrections": corr, "rejected": rejected,
            "usable": usable, "ready_at": READY_AT, "ready": usable >= READY_AT,
            "message": (f"{usable} examples collected — enough to try a fine-tune." if usable >= READY_AT else
                        f"{usable} of about {READY_AT} examples collected. Keep chatting in Free chat and rate or correct answers.")}


def examples(status_filter: str = "new", limit: int = 40, offset: int = 0) -> dict:
    """A page of examples for review (newest first); text is cut for the list."""
    status_filter = "rejected" if status_filter == "rejected" else "new"
    limit = max(1, min(int(limit), 100))
    with db.connect() as conn:
        rows = conn.execute("SELECT id, kind, prompt, response, original, created_at FROM training_examples "
                            "WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                            (status_filter, limit, max(0, int(offset)))).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM training_examples WHERE status = ?", (status_filter,)).fetchone()[0]
    cut = lambda t, n: (t or "")[:n] + ("…" if t and len(t) > n else "")  # noqa: E731
    return {"total": total, "examples": [{"id": r["id"], "kind": r["kind"], "prompt": cut(r["prompt"], 300),
                                          "response": cut(r["response"], 600), "original": cut(r["original"], 600),
                                          "created_at": r["created_at"]} for r in rows]}


def set_status(example_id: int, status: str) -> dict:
    """Reject an example (it is left out of the dataset) or restore it."""
    if status not in ("new", "rejected"):
        return {"ok": False, "message": "Unknown status."}
    with db.connect() as conn:
        n = conn.execute("UPDATE training_examples SET status = ? WHERE id = ?", (status, example_id)).rowcount
    return {"ok": bool(n)}


RECIPE = """# How to fine-tune a small model on your own examples

This folder holds `{dataset}`: {count} question → answer examples collected from your Free chats
({corrections} of them are answers you corrected yourself). One example per line, in the "messages" format
that fine-tuning tools read.

A fine-tune teaches the model your **style and format** (how Ākāra copy should sound, how you like answers
laid out). It does not teach it new facts — use the Library for facts. It takes about an hour on a free
cloud graphics card; your 4 GB laptop card cannot do it.

## Steps
1. Open a free notebook service that gives a GPU (Google Colab is one) and search for an
   "Unsloth Qwen3 4B fine-tune" notebook. Use the 4 B size — it is the size your laptop can run afterwards.
2. In the notebook, upload `{dataset}` and point its dataset step at that file (the format is the
   standard chat "messages" list, so no conversion is needed).
3. Run all cells. Training with about {count} examples is usually 10–40 minutes.
4. In the last step choose to export a **GGUF** file (q4_k_m is a good size) and download it.
5. Put the downloaded file in a folder on your laptop, with a text file named `Modelfile` next to it
   containing exactly one line:  `FROM ./your-file-name.gguf`
6. Open Command Prompt in that folder and run:  `ollama create akara-mine -f Modelfile`
7. Back in this app, open Chat, choose the model `akara-mine` in the model list at the top. Compare it with
   your usual model on a few of your own questions before you rely on it.

## Good to know
- Fewer than ~200 examples changes very little; 300–1000 good ones is the useful range.
- If the new model is worse, simply pick your old model again — nothing is lost.
- Rejected examples (Learning screen) are left out of the file.
"""


def chat_lines() -> list[str]:
    """
    The Free-chat examples as JSONL lines ({"messages": [...]}), duplicates (same question and answer) once.
    Shared by export() and libtrain.build_package() (v0.23), so both write the same chat examples.
    """
    with db.connect() as conn:
        rows = conn.execute("SELECT kind, system, prompt, response FROM training_examples WHERE status = 'new' "
                            "ORDER BY id").fetchall()
    seen, lines = set(), []
    for r in rows:
        key = hashlib.sha256((r["prompt"] + "\x00" + r["response"]).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        msgs = ([{"role": "system", "content": r["system"]}] if r["system"] else []) + [
            {"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["response"]}]
        lines.append(json.dumps({"messages": msgs}, ensure_ascii=False))
    return lines


def export() -> dict:
    """
    Write the dataset (JSONL) and the recipe into <data folder>/training/. Duplicates (same question and
    answer) are written once. RETURNS {"ok", "path", "folder", "count", "corrections"}.
    """
    with db.connect() as conn:
        rows = conn.execute("SELECT kind, system, prompt, response FROM training_examples WHERE status = 'new' "
                            "ORDER BY id").fetchall()
    seen, lines, corr = set(), [], 0
    for r in rows:
        key = hashlib.sha256((r["prompt"] + "\x00" + r["response"]).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        msgs = ([{"role": "system", "content": r["system"]}] if r["system"] else []) + [
            {"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["response"]}]
        lines.append(json.dumps({"messages": msgs}, ensure_ascii=False))
        corr += r["kind"] == "correction"
    if len(lines) < 20:
        return {"ok": False, "message": f"Only {len(lines)} examples so far. Collect at least 20 (300 or more is better) before exporting."}
    folder = config.DATA_DIR / "training"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"dataset-{_dt.date.today().isoformat()}.jsonl"
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "HOW_TO_FINE_TUNE.md").write_text(RECIPE.format(dataset=name, count=len(lines), corrections=corr),
                                                encoding="utf-8")
    return {"ok": True, "path": str(folder / name), "folder": str(folder), "count": len(lines), "corrections": corr}
