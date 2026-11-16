"""
memory.py — v0.14 memory about the owner: short facts the assistant is told in Free chat.

WHAT:  A list of short facts the owner wants his assistant to know ("I sell 3D-printed planters
       and lamps under the brand Ākāra", "Write in British English", "My laptop has a 4 GB
       graphics card"). In Free chat the facts are added to the model's instructions, so he does
       not have to repeat himself in every chat. He can:
         - add a fact by typing it, edit it, pin it (pinned facts are always included first),
           delete one, or clear them all;
         - switch the whole memory off (setting `memory_on`) without losing it;
         - press "Suggest from this chat": the model reads what HE wrote in that chat and
           proposes up to 5 lasting facts. Nothing is saved until he approves each one.
WHY:   The owner wants a private assistant that knows him, without it quietly "learning" things
       about him he cannot see. So memory is a plain list he can read, correct and erase: facts
       are only ever added by him (typed, or approved from a suggestion), never automatically.
       This is the cheapest form of "training" for a small local model: no training, just context.
LIMITS: Facts are short (300 characters), at most 200 are kept, and at most PROMPT_CHARS (about
       350 tokens) go into one reply — pinned first, then newest — because the model's window is only
       4,096 tokens and the conversation needs the room. Only Free chat uses memory; "My files" and
       "Files + general" answers come from his documents and are not shaped by it.
WHEN:  server.py → GET /memory, POST /memory/add, /memory/update, /memory/delete, /memory/clear,
       /memory/enable, /memory/suggest, GET /memory/suggest/status. chat.build_free_prompt calls
       block() every time a Free reply is written.
CONNECTED TO: db.py (table user_memory, schema v17; setting memory_on), chat.py (block, suggest uses
       chat_model and the chat's messages), ollama_client.py (generate), Chat.jsx / MemoryPanel.jsx.
PRIVACY: stored only in the local database (and so in his backups); never sent anywhere.
"""

from __future__ import annotations

import json
import re
import threading
import time

from . import db, ollama_client

MAX_FACT_CHARS = 300
MAX_FACTS = 200
PROMPT_CHARS = 1400          # most memory text sent with one Free reply
SUGGEST_MESSAGES = 20        # most recent of his messages in a chat looked at for suggestions
SUGGEST_MESSAGE_CHARS = 400
SUGGEST_MAX = 5

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def _norm(text: str) -> str:
    """Spelling-insensitive form used to spot a fact that is already saved."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def enabled() -> bool:
    return bool(db.get_setting("memory_on", True))


def set_enabled(on: bool) -> dict:
    db.set_setting("memory_on", bool(on))
    return {"ok": True, "enabled": bool(on)}


def list_all() -> dict:
    """Everything remembered, pinned first then newest; plus the on/off switch and how much is used."""
    with db.connect() as conn:
        rows = conn.execute("SELECT id, text, pinned, created_at, updated_at FROM user_memory "
                            "ORDER BY pinned DESC, id DESC").fetchall()
    facts = [dict(r) | {"pinned": bool(r["pinned"])} for r in rows]
    return {"enabled": enabled(), "facts": facts, "used_chars": len(block_text(facts)), "limit_chars": PROMPT_CHARS}


def add(text: str, pinned: bool = False) -> dict:
    """Save one fact. RETURNS {"ok": True, "id"} or {"ok": False, "message"} (empty, too long, already saved, full)."""
    text = " ".join((text or "").split())
    if len(text) < 3:
        return {"ok": False, "message": "Write the fact first."}
    if len(text) > MAX_FACT_CHARS:
        return {"ok": False, "message": f"Keep each fact under {MAX_FACT_CHARS} characters — split it into two."}
    with db.connect() as conn:
        rows = conn.execute("SELECT text FROM user_memory").fetchall()
        if len(rows) >= MAX_FACTS:
            return {"ok": False, "message": f"Memory is full ({MAX_FACTS} facts). Delete some first."}
        if any(_norm(r["text"]) == _norm(text) for r in rows):
            return {"ok": False, "message": "That is already remembered."}
        cur = conn.execute("INSERT INTO user_memory(text, pinned) VALUES (?, ?)", (text, 1 if pinned else 0))
    return {"ok": True, "id": cur.lastrowid}


def update(fact_id: int, text: str | None = None, pinned: bool | None = None) -> dict:
    """Change a fact's wording and/or whether it is pinned."""
    with db.connect() as conn:
        row = conn.execute("SELECT text FROM user_memory WHERE id = ?", (fact_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "That fact no longer exists."}
        if text is not None:
            text = " ".join(text.split())
            if len(text) < 3 or len(text) > MAX_FACT_CHARS:
                return {"ok": False, "message": f"A fact needs 3 to {MAX_FACT_CHARS} characters."}
            conn.execute("UPDATE user_memory SET text = ?, updated_at = datetime('now') WHERE id = ?", (text, fact_id))
        if pinned is not None:
            conn.execute("UPDATE user_memory SET pinned = ? WHERE id = ?", (1 if pinned else 0, fact_id))
    return {"ok": True}


def delete(fact_id: int) -> dict:
    with db.connect() as conn:
        conn.execute("DELETE FROM user_memory WHERE id = ?", (fact_id,))
    return {"ok": True}


def clear() -> dict:
    """Forget everything (the window asks twice)."""
    with db.connect() as conn:
        n = conn.execute("DELETE FROM user_memory").rowcount
    return {"ok": True, "deleted": n}


def block_text(facts: list[dict]) -> str:
    """The facts that fit PROMPT_CHARS, pinned first then newest, one per line ('' when none)."""
    lines: list[str] = []
    used = 0
    for f in facts:  # already ordered pinned → newest
        line = f"- {f['text']}"
        if used + len(line) + 1 > PROMPT_CHARS:
            continue  # a shorter, older fact may still fit
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def block() -> str:
    """
    The text added to a Free reply's instructions, or '' when memory is off or empty.
    The model is told to use the facts only when they matter and never to recite them.
    """
    if not enabled():
        return ""
    text = block_text(list_all()["facts"])
    if not text:
        return ""
    return ("WHAT THE OWNER HAS TOLD YOU ABOUT HIMSELF (use it only when it helps the answer; never list it back "
            "or mention that you were given it):\n" + text)


# ---------------------------------------------------------------------------
# Suggestions from a chat (the owner approves each one)
# ---------------------------------------------------------------------------

SUGGEST_SYSTEM = (
    "You read the messages a person wrote in a chat and list lasting facts he stated about HIMSELF, his business, "
    "his preferences or his projects, so an assistant can remember them. Rules: only what he clearly said — never "
    "guess or infer; skip anything temporary (today's task, 'this month', 'right now', a one-off question); skip anything about other people "
    "unless it is his business relationship; one short sentence per fact, written as a plain statement without "
    "'the owner' or 'he' (for example: Sells 3D-printed planters and lamps under the brand Ākāra). Skip passwords, card or account numbers and ID numbers. Reply with a JSON list of strings and nothing "
    "else, at most " + str(SUGGEST_MAX) + " items; reply [] if there is nothing worth remembering."
)


def suggest_status() -> dict:
    with _lock:
        return dict(_state)


def suggest(chat_id: int) -> dict:
    """
    Start proposing facts from one chat, in the background (about the same time as a short reply).
    The window polls suggest_status(); the proposals are NOT saved — he approves each one.
    """
    with _lock:
        if _state.get("state") == "running":
            return {"ok": False, "message": "Already reading a chat. Wait a moment."}
    from . import chat  # late: chat imports this module
    with db.connect() as conn:
        rows = conn.execute("SELECT content FROM chat_messages WHERE chat_id = ? AND role = 'user' "
                            "ORDER BY id DESC LIMIT ?", (chat_id, SUGGEST_MESSAGES)).fetchall()
    if not rows:
        return {"ok": False, "message": "Nothing to read yet — that chat has no messages from you."}
    messages = [r["content"].strip()[:SUGGEST_MESSAGE_CHARS] for r in reversed(rows)]
    with _lock:
        _state.clear()
        _state.update(state="running", proposals=[], started_at=time.time())
    threading.Thread(target=_suggest_run, args=(messages, chat.chat_model()), name="kb-memory", daemon=True).start()
    return {"ok": True}


def parse_proposals(text: str) -> list[str]:
    """
    The model's reply → clean, new, short facts. Accepts a JSON list (also inside a code fence or with
    chatter around it) or, failing that, bullet lines. Drops empties, over-long lines and facts that are
    already remembered or repeated.
    """
    items: list = []
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            items = [x for x in parsed if isinstance(x, str)]
        except ValueError:
            items = []
    if not items:
        items = [re.sub(r"^\s*[-*•\d.)]+\s*", "", ln) for ln in text.splitlines() if ln.strip().startswith(("-", "*", "•"))]
    with db.connect() as conn:
        known = {_norm(r["text"]) for r in conn.execute("SELECT text FROM user_memory")}
    out: list[str] = []
    for it in items:
        fact = " ".join(it.split()).strip(" \"'")
        if 3 <= len(fact) <= MAX_FACT_CHARS and _norm(fact) not in known:
            known.add(_norm(fact))
            out.append(fact)
    return out[:SUGGEST_MAX]


def _suggest_run(messages: list[str], model: str) -> None:
    try:
        if not ollama_client.is_running():
            raise RuntimeError("The AI engine (Ollama) isn't running. Start it from Setup.")
        # What is already remembered is shown so the model does not propose it again in other words.
        have = [f["text"] for f in list_all()["facts"]][:40]
        prompt = ("ALREADY REMEMBERED (do not repeat these, even in other words):\n"
                  + ("\n".join(f"- {t}" for t in have) if have else "(nothing yet)")
                  + "\n\nMESSAGES HE WROTE (oldest first):\n" + "\n".join(f"- {m}" for m in messages)
                  + "\n\nJSON list of NEW lasting facts:")
        r = ollama_client.generate(model, prompt, system=SUGGEST_SYSTEM, temperature=0.1, num_ctx=4096, num_predict=400)
        with _lock:
            _state.update(state="done", proposals=parse_proposals(r.text))
    except Exception as exc:
        with _lock:
            _state.update(state="error", message=str(exc))
