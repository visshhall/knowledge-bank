"""
personas.py — v0.12 personas: the instructions the model follows in Free Chat.

WHAT:  A persona is a name plus a block of instructions ("system prompt") that
       tells the local model who it is and how to answer in Free Chat mode.
       Five come with the app (read-only): a plain Assistant, an Ākāra product
       copywriter, a coding helper, a tutor and a security analyst. The owner
       can add his own, edit them and delete them, and can copy a built-in as a
       starting point (the window does that by creating a new persona with the
       built-in's text pre-filled).
WHY:   Free Chat is the "ChatGPT-like" mode of the Knowledge Bank: it does not
       use his files, so the only thing that shapes the answer is the model and
       its instructions. Letting the owner write those instructions himself is
       how he makes the model behave the way he wants — the closest thing to
       "my own model" short of training one (that comes later, v0.15).
WHEN:  Called from server.py (GET /chat/personas, POST /chat/persona/save,
       POST /chat/persona/delete) and from chat.py when a Free reply is written.
       db.py seeds BUILT_IN into the `personas` table on every start (the
       built-ins are refreshed, the owner's own personas are never touched).
CONNECTED TO: db.py (table `personas`, schema v15), chat.py (persona_prompt),
       Chat.jsx (the persona picker and editor).
PRIVACY: stored only in the local database.
"""

from __future__ import annotations

from . import db

MAX_NAME = 60
MAX_PROMPT = 4000  # about 1,000 tokens: it shares the 4,096-token window with the conversation

# What every persona is told, whatever else it says. Short on purpose: a small model follows a
# short rule better than a long one, and the window is only 4,096 tokens.
BASE_RULES = (
    "You are running privately on the owner's own computer, so answer directly and completely. "
    "Do not add warnings, lectures or moral commentary he did not ask for. "
    "If you are not sure of something, say so plainly instead of guessing, and never invent facts, "
    "numbers, quotes, links or sources."
)

# (key, name, instructions). `key` is what db.py matches on so the built-ins can be improved in later
# versions without ever creating duplicates.
BUILT_IN: list[tuple[str, str, str]] = [
    ("assistant", "Assistant",
     "You are a capable, honest general assistant. Answer what he asks in clear, well-organised "
     "language. Use short paragraphs, and bullets or numbered steps when the answer is a list or a procedure. "
     "Match the length to the question: a short question gets a short answer."),
    ("akara-copywriter", "Ākāra copywriter",
     "You write website and product copy for Ākāra, a luxury home-décor brand from Mumbai (legal name "
     "Precision Forge Labs) that sells 3D-printed planter pots, vases, ceiling, floor and table lamps and desk "
     "accessories. The voice is refined, calm and confident: classy and quietly luxurious, never loud, never "
     "cheap, no hype words such as 'amazing' or 'best ever', no exclamation marks. Write for search too: use "
     "the product's natural keywords once or twice, never stuffed. When asked for a product page give: a meta title "
     "(up to 60 characters), a meta description (up to 155 characters), a URL slug in lower case with hyphens, a "
     "headline, a short description and 4 to 6 benefit bullets. Use ONLY the material, size, colour and facts he "
     "gives you. If a detail is missing, ask for it instead of inventing it."),
    ("coding-helper", "Coding helper",
     "You are a careful senior software engineer. Give complete, working code in fenced blocks with the language "
     "named, add brief comments that explain why, and say which file the code belongs in. Prefer simple, readable "
     "solutions. Before a long answer, state in one line what you understood the task to be. If the request is "
     "ambiguous, give the most likely reading and name the assumption."),
    ("tutor", "Tutor",
     "You are a patient tutor. Explain from first principles in plain words, use one concrete example, then "
     "check understanding with a single short question. Build up step by step and avoid jargon unless you define "
     "it first. If he says he is stuck, try a different explanation rather than repeating the same one."),
    ("security-analyst", "Security analyst",
     "You are a senior SOC and detection-engineering analyst helping a colleague. Be precise and practical: "
     "name the relevant log sources and event IDs, give detection logic and sample KQL or Sigma-style queries, "
     "and separate what is certain from what depends on the environment. Mark any command, ID or number you "
     "are not fully sure of with '(verify)'. Cover detection, triage, containment and what evidence to keep."),
]


def get(persona_id: int | None) -> dict | None:
    """One persona as {"id", "key", "name", "prompt", "builtin"}; the first built-in when id is None."""
    with db.connect() as conn:
        if persona_id is None:
            row = conn.execute("SELECT * FROM personas WHERE key = 'assistant'").fetchone()
        else:
            row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
    return dict(row) if row else None


def list_all() -> dict:
    """Every persona, built-ins first, then the owner's own in the order he made them."""
    with db.connect() as conn:
        rows = conn.execute("SELECT id, key, name, prompt, builtin FROM personas "
                            "ORDER BY builtin DESC, id").fetchall()
    return {"personas": [dict(r) | {"builtin": bool(r["builtin"])} for r in rows]}


def persona_prompt(persona_id: int | None) -> str:
    """
    The full instructions for a Free reply: the owner's persona text followed by
    the short rules every persona gets. Falls back to the plain Assistant when
    the persona was deleted.
    """
    p = get(persona_id) or get(None)
    text = p["prompt"] if p else BUILT_IN[0][2]
    return f"{text}\n\n{BASE_RULES}"


def save(persona_id: int | None, name: str, prompt: str) -> dict:
    """
    Create (persona_id None) or update one of the owner's own personas.
    Built-ins cannot be changed — the window offers "Copy and edit" for them.
    RETURNS {"ok": True, "id"} or {"ok": False, "message"}.
    """
    name = " ".join((name or "").split())[:MAX_NAME]
    prompt = (prompt or "").strip()
    if not name:
        return {"ok": False, "message": "Give the persona a name."}
    if len(prompt) < 10:
        return {"ok": False, "message": "Write what this persona should do (at least a sentence)."}
    if len(prompt) > MAX_PROMPT:
        return {"ok": False, "message": f"Keep the instructions under {MAX_PROMPT} characters, so they leave room for the conversation."}
    with db.connect() as conn:
        if persona_id is None:
            cur = conn.execute("INSERT INTO personas(name, prompt, builtin) VALUES (?, ?, 0)", (name, prompt))
            return {"ok": True, "id": cur.lastrowid}
        row = conn.execute("SELECT builtin FROM personas WHERE id = ?", (persona_id,)).fetchone()
        if not row:
            return {"ok": False, "message": "That persona no longer exists."}
        if row["builtin"]:
            return {"ok": False, "message": "Built-in personas can't be changed. Use “Copy and edit” to make your own version."}
        conn.execute("UPDATE personas SET name = ?, prompt = ? WHERE id = ?", (name, prompt, persona_id))
    return {"ok": True, "id": persona_id}


def delete(persona_id: int) -> dict:
    """Delete one of the owner's own personas. Chats that used it fall back to the Assistant."""
    with db.connect() as conn:
        row = conn.execute("SELECT builtin FROM personas WHERE id = ?", (persona_id,)).fetchone()
        if not row:
            return {"ok": True}
        if row["builtin"]:
            return {"ok": False, "message": "Built-in personas can't be deleted."}
        conn.execute("UPDATE chats SET persona_id = NULL WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    return {"ok": True}
