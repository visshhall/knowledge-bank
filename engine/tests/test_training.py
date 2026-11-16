"""
test_training.py — checks for training.py (v0.16 learning from use): signals, examples, corrections, export.
Run with   python -I tests/test_training.py   from the engine folder. No AI and no internet are used:
the chat is filled directly in the database.
WHAT: thumbs-up/copy make a Free-chat answer a 'good' example; thumbs-down and Regenerate remove it; a copy
      does not undo a thumbs-down; short answers, library answers and answers the fact-checker trimmed are
      never examples; a correction replaces the plain example and keeps the original; rejecting leaves an
      example out; status counts and the ready flag; export needs 20 examples, de-duplicates, writes the
      JSONL and the recipe; Edit (undo with reason edit) is neutral.
WHEN: before a release that touches training.py or chat.undo_last.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-train-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import chat, config, db, training  # noqa: E402

assert db.init_db() == 19
LONG = "A fluted planter reads as quiet craftsmanship, with soft vertical lines that catch the light. " * 2


def make_chat(mode="free"):
    with db.connect() as conn:
        cid = conn.execute("INSERT INTO chats(title, mode) VALUES ('t', ?)", (mode,)).lastrowid
    return cid


def add(cid, role, content, mode="free", checks=None):
    with db.connect() as conn:
        return conn.execute("INSERT INTO chat_messages(chat_id, role, content, checks_json, mode) VALUES (?, ?, ?, ?, ?)",
                            (cid, role, content, json.dumps(checks or {}), mode if role == "assistant" else None)).lastrowid


def count(where="1=1"):
    with db.connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM training_examples WHERE {where}").fetchone()[0]


c = make_chat()
add(c, "user", "Write a product line for a fluted planter.")
a1 = add(c, "assistant", LONG)

# up -> a good example with the question and persona text
assert training.record(a1, "up") == {"ok": True, "example": True} and count() == 1
assert training.record(a1, "up")["example"] is True and count() == 1          # not duplicated
# down removes it; a later copy does not bring it back
assert training.record(a1, "down")["example"] is False and count() == 0
assert training.record(a1, "copy")["example"] is False and count() == 0
# an answer nobody marked down: copy alone makes an example
add(c, "user", "Another line please.")
a2 = add(c, "assistant", LONG + " Second.")
assert training.record(a2, "copy")["example"] is True and count() == 1

# never examples: too short, library mode, fact-checker trimmed, "files don't cover"
c2 = make_chat("library")
add(c2, "user", "q")
lib = add(c2, "assistant", LONG, mode="library")
assert training.record(lib, "up")["example"] is False
add(c, "user", "short?")
short = add(c, "assistant", "Yes.")
assert training.record(short, "up")["example"] is False
add(c, "user", "q3")
trimmed = add(c, "assistant", LONG + " trimmed", checks={"removed_count": 2})
assert training.record(trimmed, "up")["example"] is False
add(c, "user", "q4")
nf = add(c, "assistant", "Your files don't cover this. " + LONG)
assert training.record(nf, "up")["example"] is False
assert training.record(99999, "up")["ok"] is False and training.record(a1, "bogus")["ok"] is False

# correction replaces the plain example, changes the chat text, keeps the original
r = training.correct(a2, "My better line about the fluted planter, written in my own voice and style.")
assert r["ok"]
with db.connect() as conn:
    row = conn.execute("SELECT kind, response, original FROM training_examples WHERE message_id = ?", (a2,)).fetchone()
    shown = conn.execute("SELECT content FROM chat_messages WHERE id = ?", (a2,)).fetchone()[0]
assert row["kind"] == "correction" and row["original"].startswith("A fluted planter") and shown == row["response"]
assert training.correct(a2, "x")["ok"] is False and training.correct(lib, "A long enough correction text.")["ok"] is False
assert training.correct(a2, "Second rewrite of the same answer, again in my voice.")["ok"]
with db.connect() as conn:
    assert conn.execute("SELECT original FROM training_examples WHERE message_id = ?", (a2,)).fetchone()[0].startswith("A fluted")

# regenerate / edit through chat.undo_last
add(c, "user", "q5")
a5 = add(c, "assistant", LONG + " five")
training.record(a5, "up")
assert count(f"message_id = {a5}") == 1
r = chat.undo_last(c, reason="regen")
assert r["ok"] and r["text"] == "q5" and count(f"message_id = {a5}") == 0
add(c, "user", "q6")
a6 = add(c, "assistant", LONG + " six")
assert chat.undo_last(c, reason="edit")["ok"]
sig = training.status()["signals"]
assert sig["regen"] == 1 and sig["edit"] == 1 and sig["down"] == 1 and sig["correct"] == 2, sig

# review / reject / counts
st = training.status()
assert st["usable"] == 1 and st["corrections"] == 1 and st["ready"] is False
ex = training.examples()
assert ex["total"] == 1 and ex["examples"][0]["kind"] == "correction"
assert training.set_status(ex["examples"][0]["id"], "rejected")["ok"]
assert training.status()["usable"] == 0 and training.examples("rejected")["total"] == 1
assert training.set_status(ex["examples"][0]["id"], "new")["ok"] and training.set_status(1, "weird")["ok"] is False

# export: needs 20, writes jsonl + recipe, de-duplicates
assert training.export()["ok"] is False
for i in range(25):
    cc = make_chat()
    add(cc, "user", f"Question number {i}?")
    m = add(cc, "assistant", LONG + f" variant {i}")
    training.record(m, "up")
cc = make_chat(); add(cc, "user", "Question number 3?"); m = add(cc, "assistant", LONG + " variant 3"); training.record(m, "up")  # duplicate pair
out = training.export()
assert out["ok"] and out["count"] == 26 and out["corrections"] == 1, out
lines = Path(out["path"]).read_text(encoding="utf-8").strip().split("\n")
assert len(lines) == 26 and json.loads(lines[0])["messages"][-1]["role"] == "assistant"
assert json.loads(lines[0])["messages"][0]["role"] == "system"
assert "ollama create" in (config.DATA_DIR / "training" / "HOW_TO_FINE_TUNE.md").read_text(encoding="utf-8")
print("test_training: all checks passed")
