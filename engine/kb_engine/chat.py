"""
chat.py — v0.11/v0.12 Chat: saved, multi-turn conversations with your library or, in Free mode, with the model alone.

WHAT:  Lets the owner talk to the Knowledge Bank the way he would to a
       colleague who has read all his PDFs:
         - Many saved chats (new, rename, delete, search by title or text).
         - Each question is answered from the best passages in the bank
           (the same retrieval as Answers: meaning + exact words), numbered
           [1]…[n] and cited, with the same fact check (answers.finalize):
           every number, technique ID, IP, event ID or query line must be in
           the cited sources or the sentence is removed.
         - Earlier turns are sent along, so follow-ups work ("explain that
           more simply", "and for Linux?"). A very short follow-up also
           borrows the words of the previous question when searching.
         - Library first, general knowledge only when the owner turns the
           switch on for that message. Anything that does NOT come from his
           files is placed in a separate section that starts with
           "From general knowledge (not from your files):", is not
           fact-checked, carries no source markers, and the message is
           flagged `general` so the window can label it clearly.
         - Writing is streamed (the window polls status()) and can be
           stopped; the part already written is kept and checked.
       v0.12 adds THREE MODES, remembered per chat:
         library  only from his files, every sentence cited and fact-checked (v0.11);
         both     files first, plus a clearly marked general-knowledge part (v0.11's
                  "Also use general knowledge" switch);
         free     no files at all: the model answers like any general AI chat, shaped
                  by a PERSONA (personas.py — instructions the owner can write himself).
                  Nothing in a Free reply is fact-checked or cited, and the window
                  labels it "not from your files". A longer part of the conversation
                  is sent along than in the library modes, since there are no passages
                  competing for room in the 4,096-token window.
WHY:  The owner asked to turn the Knowledge Bank itself into the chat app,
       because it already holds the enriched data of ~200 PDFs. Reusing the
       bank (instead of a separate chat program) keeps every answer
       traceable to a file and page, and keeps everything on this laptop.
WHEN:  Called from server.py: GET /chat/list, POST /chat/new, GET /chat/get,
       POST /chat/rename, POST /chat/delete, POST /chat/send, GET
       /chat/status, POST /chat/stop. The window is Chat.jsx.
       importer.py calls forget_sources() when a file is removed.
CONNECTED TO: answers.py (retrieval `_sources`, fact check `finalize`),
       ollama_client.py (generate, streaming, stop), db.py (tables `chats`
       and `chat_messages`, schema v14; `mode` and `persona_id`, schema v15; setting
       `chat_model`), personas.py (persona_prompt), writer.py (write_model = the
       default model), chunking.with_section.
PRIVACY: nothing here talks to any server except the local Ollama.
"""

from __future__ import annotations

import json
import re
import threading
import time

from . import answers, chunking, db, ollama_client, personas

MAX_SOURCES = 6        # passages per question (history shares the 4,096-token window)
SOURCE_CHARS = 800     # each passage is cut to this length in the prompt
HISTORY_TURNS = 4      # earlier messages sent to the model (2 questions + 2 answers)
HISTORY_CHARS = 500    # each earlier message is cut to this length in the prompt
NUM_CTX = 4096
MAX_OUTPUT = 800
FREE_HISTORY_TURNS = 12   # Free mode: how many earlier messages are looked at …
FREE_HISTORY_CHARS = 6000  # … and the most text of them that is sent (newest first); no passages share the window
FREE_MESSAGE_CHARS = 2000  # one earlier message is cut to this length
FREE_MAX_OUTPUT = 1200
MODES = ("library", "both", "free")
DEFAULT_TITLE = "New chat"
GENERAL_MARK = "From general knowledge (not from your files):"
CLEARED = "This answer used a file that was removed from the bank, so it was cleared."

SYSTEM_LIBRARY = (
    "You are the private research assistant of a cybersecurity analyst, in a conversation with him. "
    "Answer his latest QUESTION using ONLY the numbered SOURCES taken from his own documents. "
    "The CONVERSATION shows what was said before, so follow-up questions make sense. "
    "If the sources do not contain the answer, reply exactly: NOT IN SOURCES. "
    "Never invent event IDs, MITRE IDs, commands, tools or numbers. Copy queries exactly. "
    "End every sentence and bullet with the source markers it came from, e.g. [2] or [1][3]. "
    "Be direct and practical; use short bullets or numbered steps when the answer is a procedure."
)

SYSTEM_GENERAL = (
    "You are the private research assistant of a cybersecurity analyst, in a conversation with him. "
    "Answer his latest QUESTION. First use the numbered SOURCES taken from his own documents and end every "
    "sentence that uses them with its source markers, e.g. [2] or [1][3]. Never invent event IDs, MITRE IDs, "
    "commands, tools or numbers, and copy queries exactly. The CONVERSATION shows what was said before. "
    "If the sources do not fully answer, you may add what you know yourself, but put ALL of that in a final "
    "section that begins with the exact line: " + GENERAL_MARK + " — with no source markers in it, and say plainly "
    "when you are unsure. If the sources answer everything, do not add that section."
)

PROMPT = """CONVERSATION SO FAR:
{history}

SOURCES:
{sources}

QUESTION: {question}

Write the answer in Markdown (no title). Start with a one or two sentence direct answer, then details if useful."""

PROMPT_NO_SOURCES = """CONVERSATION SO FAR:
{history}

No passage in his files matched this question.

QUESTION: {question}

Answer from your own general knowledge only. Begin with the exact line: """ + GENERAL_MARK + """
Be brief and say plainly when you are unsure."""

PROMPT_FREE = """CONVERSATION SO FAR:
{history}

OWNER: {question}

Reply to the owner's latest message."""

_lock = threading.Lock()
_state: dict = {"state": "idle"}
_stop = threading.Event()


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def status() -> dict:
    """Live state of the answer being written: idle | running | done | error."""
    with _lock:
        return dict(_state)


def chat_model() -> str:
    """
    The model Chat writes with: the owner's pick in Setup → Models (setting
    `chat_model`), otherwise the same model that writes articles.
    """
    from .writer import write_model  # late import: writer imports lessons → avoids a cycle
    return db.get_setting("chat_model") or write_model()


def normalize_mode(mode: str | None, general: bool = False) -> str:
    """
    The mode a message is sent in. An explicit valid `mode` wins; otherwise the
    old v0.11 `general` flag decides (True → "both", False → "library"), so a
    window or script that only knows v0.11 keeps working.
    """
    if mode in MODES:
        return mode
    return "both" if general else "library"


# ---------------------------------------------------------------------------
# Saved chats (create, list, open, rename, delete)
# ---------------------------------------------------------------------------

def new_chat(title: str | None = None) -> dict:
    """Create an empty chat. RETURNS {"id", "title"}."""
    title = " ".join((title or DEFAULT_TITLE).split())[:80] or DEFAULT_TITLE
    with db.connect() as conn:
        cur = conn.execute("INSERT INTO chats(title) VALUES (?)", (title,))
        return {"id": cur.lastrowid, "title": title}


def _like(q: str) -> str:
    """Escape % and _ so the owner's search text is matched literally."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_chats(q: str | None = None) -> dict:
    """
    Saved chats, newest first. With `q`, only chats whose title or any
    message contains it (plain text match, not case sensitive).
    """
    q = " ".join((q or "").split())
    sql = ("SELECT c.id, c.title, c.updated_at, "
           "c.mode, (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id = c.id) AS messages FROM chats c")
    args: list = []
    if q:
        sql += (" WHERE c.title LIKE ? ESCAPE '\\' OR c.id IN "
                "(SELECT chat_id FROM chat_messages WHERE content LIKE ? ESCAPE '\\')")
        args = [_like(q), _like(q)]
    sql += " ORDER BY c.updated_at DESC, c.id DESC LIMIT 200"
    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {"chats": [dict(r) for r in rows], "query": q}


def get_chat(chat_id: int) -> dict | None:
    """One chat with all its messages (sources decoded), or None."""
    with db.connect() as conn:
        c = conn.execute("SELECT id, title, mode, persona_id, created_at, updated_at FROM chats WHERE id = ?",
                         (chat_id,)).fetchone()
        if not c:
            return None
        rows = conn.execute("SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
    messages = []
    for r in rows:
        try:
            sources = json.loads(r["sources_json"] or "{}")
        except ValueError:
            sources = {}
        try:
            checks = json.loads(r["checks_json"] or "{}")
        except ValueError:
            checks = {}
        messages.append({"id": r["id"], "role": r["role"], "content": r["content"], "sources": sources,
                         "checks": checks, "general": bool(r["general"]),
                         "mode": (r["mode"] or ("both" if r["general"] else "library")) if r["role"] == "assistant" else None,
                         "model_used": r["model_used"],
                         "seconds": r["seconds"], "created_at": r["created_at"]})
    return {"id": c["id"], "title": c["title"], "mode": c["mode"], "persona_id": c["persona_id"],
            "created_at": c["created_at"], "updated_at": c["updated_at"], "messages": messages}


def rename_chat(chat_id: int, title: str) -> dict:
    title = " ".join((title or "").split())[:80]
    if not title:
        return {"ok": False, "message": "Type a name for the chat."}
    with db.connect() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    return {"ok": True}


def delete_chat(chat_id: int) -> dict:
    """Delete a chat and, by cascade, all its messages."""
    with db.connect() as conn:
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return {"ok": True}


def forget_sources(conn, source_ids) -> int:
    """
    A file was removed from the bank: clear every chat answer that cited it.

    WHY:   Removing a PDF must leave none of its text behind (v0.9.2 rule).
           The conversation itself stays; only the assistant messages that
           quoted the removed file are replaced by a short note and lose
           their sources.
    CALLED BY: importer._clean_up_after_removal (inside its transaction).
    RETURNS the number of messages cleared.
    """
    from .importer import _cited_source_ids
    gone = {int(x) for x in source_ids}
    cleared = 0
    for r in conn.execute("SELECT id, sources_json FROM chat_messages WHERE role = 'assistant' "
                          "AND sources_json IS NOT NULL AND sources_json != '{}'").fetchall():
        if gone & _cited_source_ids(r["sources_json"]):
            conn.execute("UPDATE chat_messages SET content = ?, sources_json = '{}', checks_json = NULL, "
                         "general = 0 WHERE id = ?", (CLEARED, r["id"]))
            cleared += 1
    return cleared


# ---------------------------------------------------------------------------
# Sending a message
# ---------------------------------------------------------------------------

def send(chat_id: int | None, text: str, general: bool = False, mode: str | None = None,
         persona_id: int | None = None) -> dict:
    """
    Add the owner's message to a chat and start writing the reply in the
    background. chat_id None starts a new chat. `mode` is "library", "both" or
    "free" (see the top of this file); `general` is the older v0.11 way to ask
    for "both". The mode and persona are saved on the chat, so the chat opens
    the way it was last used. RETURNS {"ok", "chat_id"} or {"ok": False, "message"}.
    """
    mode = normalize_mode(mode, general)
    text = (text or "").strip()
    if len(text) < 2:
        return {"ok": False, "message": "Type a message first."}
    with _lock:
        if _state.get("state") == "running":
            return {"ok": False, "message": "Still writing the previous reply. Press Stop or wait."}
    if chat_id is None:
        chat_id = new_chat()["id"]
    with db.connect() as conn:
        c = conn.execute("SELECT id, title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not c:
            return {"ok": False, "message": "That chat no longer exists."}
        history = conn.execute(
            "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, FREE_HISTORY_TURNS)).fetchall()[::-1]
        if persona_id is not None and not personas.get(persona_id):
            persona_id = None  # a deleted persona falls back to the Assistant
        conn.execute("INSERT INTO chat_messages(chat_id, role, content) VALUES (?, 'user', ?)", (chat_id, text))
        title = c["title"]
        if title == DEFAULT_TITLE:  # the first question names the chat
            title = " ".join(text.split())[:60]
        conn.execute("UPDATE chats SET title = ?, mode = ?, persona_id = ?, updated_at = datetime('now') WHERE id = ?",
                     (title, mode, persona_id, chat_id))
    _stop.clear()
    with _lock:
        _state.clear()
        _state.update(state="running", chat_id=chat_id,
                      stage="Thinking…" if mode == "free" else "Finding the best passages…",
                      live=None, started_at=time.time())
    threading.Thread(target=_run, args=(chat_id, text, mode, [dict(h) for h in history], persona_id),
                     name="kb-chat", daemon=True).start()
    return {"ok": True, "chat_id": chat_id}


def stop() -> dict:
    """Stop writing now; the part already written is kept and checked."""
    _stop.set()
    return {"ok": True}


# Words that show a message leans on what was said before ("how do I detect it?").
_FOLLOW_UP = re.compile(r"\b(it|its|that|this|those|these|they|them|their|same|above|previous|earlier)\b", re.I)
_FOLLOW_START = re.compile(r"^\s*(and|also|but|then|so|what about|how about)\b", re.I)


def _search_text(text: str, history: list[dict]) -> str:
    """
    The words used to look for passages.

    A follow-up carries too little meaning on its own ("and how do I detect
    it?" — detect what?), so the owner's previous question is added when the
    message is short (under 10 words), opens with "and / also / what about…",
    or points back with a word like it, that, this, them. A long standalone
    question is searched as written. (Found in the first real test: a
    6-word follow-up was searched alone and returned unrelated passages.)
    """
    words = text.split()
    leans_back = len(words) < 10 or _FOLLOW_UP.search(text) or _FOLLOW_START.match(text)
    if not leans_back:
        return text
    for h in reversed(history):
        if h["role"] == "user":
            return f"{h['content'][:300]} {text}"
    return text


def _history_text(history: list[dict]) -> str:
    if not history:
        return "(this is the first message)"
    lines = []
    for h in history:
        who = "Analyst" if h["role"] == "user" else "Assistant"
        body = " ".join(h["content"].split())
        lines.append(f"{who}: {body[:HISTORY_CHARS]}")
    return "\n".join(lines)


def build_prompt(question: str, history: list[dict], sources: list[dict], general: bool) -> tuple[str, str]:
    """
    The (system, prompt) pair for one question. Shared with the model
    comparison (modelpick.py) so a model is judged on exactly what Chat sends.
    """
    hist = _history_text(history[-HISTORY_TURNS:])
    if not sources:
        return SYSTEM_GENERAL, PROMPT_NO_SOURCES.format(history=hist, question=question)
    numbered = "\n\n".join(
        f"[{i}] {chunking.with_section(s['text'], s['section'])[:SOURCE_CHARS]}"
        for i, s in enumerate(sources, start=1))
    return (SYSTEM_GENERAL if general else SYSTEM_LIBRARY,
            PROMPT.format(history=hist, sources=numbered, question=question))


def _free_history_text(history: list[dict]) -> str:
    """
    The earlier conversation for Free mode: the newest messages that fit in
    FREE_HISTORY_CHARS, each cut to FREE_MESSAGE_CHARS, oldest first. (Library
    modes send far less, because retrieved passages need the room.)
    """
    if not history:
        return "(this is the first message)"
    kept: list[str] = []
    used = 0
    for h in reversed(history):
        who = "Owner" if h["role"] == "user" else "Assistant"
        line = f"{who}: {h['content'].strip()[:FREE_MESSAGE_CHARS]}"
        if used + len(line) > FREE_HISTORY_CHARS and kept:
            break
        kept.append(line)
        used += len(line)
    return "\n".join(reversed(kept))


def build_free_prompt(question: str, history: list[dict], persona_id: int | None) -> tuple[str, str]:
    """The (system, prompt) pair for a Free reply: the persona's instructions and the conversation."""
    return (personas.persona_prompt(persona_id),
            PROMPT_FREE.format(history=_free_history_text(history), question=question))


def split_general(body: str) -> tuple[str, str]:
    """
    Split a written reply into (part from the files, general-knowledge part).
    The general part starts at the line that begins with "From general
    knowledge"; it is empty when the model did not add one.
    """
    m = re.search(r"(?im)^[ \t>*#_-]*from general knowledge", body)
    if not m:
        return body, ""
    return body[:m.start()].rstrip(), body[m.start():].strip()


def finish_reply(body: str, sources: list[dict], general: bool) -> tuple[str, bool, list[str]]:
    """
    Turn the model's raw text into the saved reply.

    RETURNS (markdown, has_general_part, removed_sentences).
      - the file-based part is fact-checked (answers.finalize);
      - the general part (only when `general` is on) is kept as written, but
        source markers are stripped from it, since nothing there came from a file;
      - "NOT IN SOURCES" or an empty result becomes a plain explanation.
    """
    if general and not sources:
        lib, gen = "", body                      # nothing from the files: all of it is general knowledge
    elif general:
        lib, gen = split_general(body)
    else:
        # Switch off: a stray "From general knowledge" line from the model is dropped, and
        # everything it wrote stays under the fact check.
        lib, gen = re.sub(r"(?im)^[ \t>*#_-]*from general knowledge[^\n]*\n?", "", body), ""
    gen = re.sub(r"\s*\[\d+\]", "", gen).strip()
    not_found = "NOT IN SOURCES" in lib.upper()[:60]
    removed: list[str] = []
    checked = ""
    if sources and not not_found and "NOT IN SOURCES" in lib.upper():
        # The model explained what its sources lack and then added the code phrase anyway
        # (seen in the first real test). Keep the explanation, drop the phrase, and drop the
        # [n] markers — a statement that something is absent is not backed by those passages.
        lib = re.sub(r"(?i)\s*NOT IN SOURCES\.?", "", lib)
        lib = re.sub(r"\s*\[\d+\]", "", lib).strip()
    if sources and not not_found:
        checked, removed = answers.finalize(lib, sources)
    if gen and not gen.lower().lstrip("*#> _-").startswith("from general knowledge"):
        gen = GENERAL_MARK + "\n" + gen
    parts = [p for p in (checked, gen) if p]
    if parts:
        return "\n\n".join(parts), bool(gen), removed
    if not sources or not_found:
        msg = "Your files don't cover this."
        msg += ("" if general else " Turn on “Also use general knowledge” to get an answer from the model's own "
                                   "knowledge, clearly marked as not coming from your files.")
    else:
        msg = "Your files don't answer this directly. The closest passages are listed below — open them to read more."
    return msg, False, removed


def _run(chat_id: int, text: str, mode: str, history: list[dict], persona_id: int | None = None) -> None:
    started = time.time()
    try:
        if not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
        model = chat_model()
        if mode == "free":
            _run_free(chat_id, text, history, persona_id, model, started)
            return
        general = mode == "both"
        history = history[-HISTORY_TURNS:]  # library modes keep the window for the passages
        sources = answers._sources(_search_text(text, history), limit=MAX_SOURCES)
        if not sources and not general:
            reply, has_general, removed = finish_reply("", sources, general)
            _save_reply(chat_id, reply, {}, {"removed": [], "removed_count": 0}, False, model, started, mode)
            return
        system, prompt = build_prompt(text, history, sources, general)
        _set(stage=f"Writing with {model}…")
        r = ollama_client.generate(model, prompt, system=system, temperature=0.2, num_ctx=NUM_CTX,
                                   num_predict=MAX_OUTPUT, on_text=lambda t: _set(live=t),
                                   should_stop=_stop.is_set)
        _set(stage="Checking every fact against the sources…")
        reply, has_general, removed = finish_reply(r.text.strip(), sources, general)
        if _stop.is_set():
            reply += "\n\n*(Stopped before the end.)*"
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", reply)}
        src = {str(i): {k: s.get(k) for k in ("passage_id", "point_id", "source_id", "file_name",
                                                "page_number", "section", "topic_id", "topic_title")}
               | {"text": s["text"], "cited": i in cited}
               for i, s in enumerate(sources, start=1)}
        _save_reply(chat_id, reply, src, {"removed": removed, "removed_count": len(removed)},
                    has_general, model, started, mode)
    except Exception as exc:
        _set(state="error", stage=None, live=None, message=str(exc))


def _run_free(chat_id: int, text: str, history: list[dict], persona_id: int | None,
              model: str, started: float) -> None:
    """
    Write one Free reply: no passages, no citations, no fact check. The persona's
    instructions are the system prompt. A little more warmth than the library
    modes (temperature 0.6) because here the owner wants a conversation, not a
    quotation. Called only by _run.
    """
    system, prompt = build_free_prompt(text, history, persona_id)
    _set(stage=f"Writing with {model}…")
    r = ollama_client.generate(model, prompt, system=system, temperature=0.6, num_ctx=NUM_CTX,
                               num_predict=FREE_MAX_OUTPUT, on_text=lambda t: _set(live=t),
                               should_stop=_stop.is_set)
    reply = re.sub(r"\s*\[\d+\]", "", r.text.strip())  # nothing here came from a file, so no source markers
    if not reply:
        reply = "The model returned nothing. Try again, or choose another model above."
    if _stop.is_set():
        reply += "\n\n*(Stopped before the end.)*"
    _save_reply(chat_id, reply, {}, {"removed": [], "removed_count": 0}, False, model, started, "free")


def _save_reply(chat_id: int, reply: str, sources: dict, checks: dict, has_general: bool,
                model: str, started: float, mode: str = "library") -> None:
    seconds = round(time.time() - started, 1)
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone():
            _set(state="idle", stage=None, live=None)  # the owner deleted the chat meanwhile
            return
        cur = conn.execute(
            "INSERT INTO chat_messages(chat_id, role, content, sources_json, checks_json, general, model_used, seconds, mode) "
            "VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, reply, json.dumps(sources), json.dumps(checks), 1 if has_general else 0, model, seconds, mode))
        conn.execute("UPDATE chats SET updated_at = datetime('now') WHERE id = ?", (chat_id,))
    _set(state="done", stage=None, live=None, message_id=cur.lastrowid, seconds=seconds)
