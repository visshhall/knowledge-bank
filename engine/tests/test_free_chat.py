"""
test_free_chat.py — checks for v0.12 Free Chat and personas (chat.py, personas.py, db schema v15).
Plain asserts: run with   python -I tests/test_free_chat.py   from the engine folder.
WHAT: the three modes (library / both / free), that Free sends no passages and no fact check,
      that the persona's instructions reach the model, the longer Free history, mode and persona
      remembered per chat, built-in persona protection, and the schema v15 migration on a v14 bank.
WHY:  Free Chat must never pass off the model's own words as coming from the owner's files, and the
      library modes must behave exactly as in v0.11. No real AI is needed: ollama_client.generate
      is replaced by a function that records what it was given and returns fixed text.
WHEN: before every release that touches chat.py, personas.py or the chat tables in db.py.
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-free-test-")  # a throw-away bank
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import answers, chat, db, ollama_client, personas  # noqa: E402

assert db.init_db() == 17

SOURCES = [{"passage_id": 1, "point_id": 1, "source_id": 7, "file_name": "rdp.pdf", "page_number": 3,
            "section": None, "topic_id": None, "topic_title": "RDP",
            "text": "Event ID 4625 records a failed logon."}]
calls = []
reply_text = [""]
searched = []


def fake_sources(q, limit=8):
    searched.append(q)
    return [dict(s) for s in SOURCES]


answers._sources = fake_sources
ollama_client.is_running = lambda: True


def fake_generate(model, prompt, system=None, temperature=0.2, num_ctx=8192, think=False,
                  num_predict=None, on_text=None, num_gpu=None, fallback=True, should_stop=None):
    calls.append({"prompt": prompt, "system": system, "temperature": temperature, "num_predict": num_predict})
    return ollama_client.GenerationResult(reply_text[0], 10, 10, 0, 0, 1.0, 1.0)


ollama_client.generate = fake_generate


def run(text, chat_id=None, **kw):
    r = chat.send(chat_id, text, **kw)
    assert r["ok"], r
    for _ in range(200):
        if chat.status()["state"] != "running":
            break
        time.sleep(0.05)
    assert chat.status()["state"] == "done", chat.status()
    return r["chat_id"]


# --- built-in personas are seeded and protected --------------------------------------------------
names = [p["name"] for p in personas.list_all()["personas"]]
assert names[:2] == ["Assistant", "Ākāra copywriter"] and len(names) == 5, names
builtin = personas.get(None)
assert builtin["key"] == "assistant" and builtin["builtin"] == 1
assert personas.save(builtin["id"], "x", "Changed instructions here")["ok"] is False
assert personas.delete(builtin["id"])["ok"] is False
assert personas.save(None, "", "Some instructions.")["ok"] is False
assert personas.save(None, "Short", "tiny")["ok"] is False
assert personas.save(None, "Long", "x" * 5000)["ok"] is False
mine = personas.save(None, "Pirate", "Answer everything like a pirate, briefly.")
assert mine["ok"]
assert personas.save(mine["id"], "Pirate captain", "Answer like a pirate captain, briefly.")["ok"]
assert [p["name"] for p in personas.list_all()["personas"]][-1] == "Pirate captain"
assert "pirate captain" in personas.persona_prompt(mine["id"]).lower()
assert "privately on the owner's own computer" in personas.persona_prompt(mine["id"])  # base rules always added

# --- the v0.11 flag still means "both"; unknown modes fall back safely ------------------------------
assert chat.normalize_mode(None, False) == "library"
assert chat.normalize_mode(None, True) == "both"
assert chat.normalize_mode("free", True) == "free"
assert chat.normalize_mode("nonsense", False) == "library"

# --- library mode: unchanged from v0.11 (cited, fact-checked, passages sent) ------------------------
reply_text[0] = "Event ID 4625 records a failed logon [1]. It also records event 9999 [1]."
cid = run("What does event 4625 record?", mode="library")
msgs = chat.get_chat(cid)["messages"]
assert msgs[-1]["mode"] == "library" and msgs[-1]["sources"] and "9999" not in msgs[-1]["content"]
assert "Event ID 4625" in calls[-1]["prompt"] and calls[-1]["temperature"] == 0.2
assert chat.get_chat(cid)["mode"] == "library"

# --- free mode: no search, no passages, no fact check, persona used, no source markers --------------
searched.clear()
n = len(calls)
reply_text[0] = "Arr, a **failed logon** it be [1], and the number 123456 is fine here."
cid2 = run("Tell me about logons", mode="free", persona_id=mine["id"])
assert not searched, "Free mode must not search the library"
free_call = calls[n]
assert "Event ID 4625" not in free_call["prompt"] and "SOURCES" not in free_call["prompt"]
assert "pirate captain" in free_call["system"].lower()
assert free_call["temperature"] == 0.6 and free_call["num_predict"] == chat.FREE_MAX_OUTPUT
chat_free = chat.get_chat(cid2)
m = chat_free["messages"][-1]
assert m["mode"] == "free" and m["sources"] == {} and m["general"] is False
assert "123456" in m["content"] and "[1]" not in m["content"]   # not fact-checked, markers stripped
assert chat_free["mode"] == "free" and chat_free["persona_id"] == mine["id"]

# --- free mode keeps a longer conversation than the library modes ----------------------------------
cid3 = None
for i in range(5):
    reply_text[0] = f"answer number {i}"
    cid3 = run(f"question number {i} about something", cid3, mode="free")
last_prompt = calls[-1]["prompt"]
assert "question number 0 about something" in last_prompt and "answer number 3" in last_prompt, last_prompt
lib_cid = None
for i in range(5):
    reply_text[0] = f"Event ID 4625 records a failed logon [1]. answer {i}"
    lib_cid = run(f"library question number {i} about logons", lib_cid, mode="library")
assert "library question number 0" not in calls[-1]["prompt"]     # library keeps only the last 4 messages
# one huge earlier message cannot crowd out the newest ones
assert len(chat._free_history_text([{"role": "user", "content": "z" * 50000}] * 12)) <= chat.FREE_HISTORY_CHARS + chat.FREE_MESSAGE_CHARS + 20

# --- switching a chat's mode is remembered; an old chat without a mode reads as library ---------------
cid4 = run("hello there friend", cid3, mode="both")
assert chat.get_chat(cid4)["mode"] == "both"
assert chat.get_chat(cid4)["messages"][-1]["mode"] == "both"
assert any(c["mode"] == "both" for c in chat.list_chats()["chats"])

# --- a deleted persona falls back to the Assistant -----------------------------------------------
assert personas.delete(mine["id"])["ok"]
assert chat.get_chat(cid2)["persona_id"] is None
n = len(calls)
reply_text[0] = "ok"
run("still there?", cid2, mode="free", persona_id=mine["id"])    # id no longer exists
assert "general, honest" not in calls[n]["system"] and "capable, honest general assistant" in calls[n]["system"]

# --- empty reply is explained, not saved blank ---------------------------------------------------
reply_text[0] = "   "
cid5 = run("say nothing", mode="free")
assert "returned nothing" in chat.get_chat(cid5)["messages"][-1]["content"]

# --- schema v15 upgrades a real v14 bank without losing chats -----------------------------------
old = Path(os.environ["KB_DATA_DIR"]) / "old.sqlite3"
con = sqlite3.connect(old)
con.executescript("""
CREATE TABLE chats(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE chat_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, sources_json TEXT, checks_json TEXT, general INTEGER NOT NULL DEFAULT 0,
  model_used TEXT, seconds REAL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
INSERT INTO chats(title) VALUES ('old chat');
INSERT INTO chat_messages(chat_id, role, content, general) VALUES (1, 'assistant', 'old answer', 1);
CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT);
""")
con.commit()
con.close()
real_connect = db.connect


def connect_old():
    c = sqlite3.connect(old)
    c.row_factory = sqlite3.Row
    return c


db.connect = connect_old
try:
    db._migrate_v15()
    db._migrate_v15()   # running twice must change nothing
    with db.connect() as c:
        assert c.execute("SELECT mode FROM chats WHERE id = 1").fetchone()["mode"] == "library"
        assert c.execute("SELECT mode FROM chat_messages WHERE id = 1").fetchone()["mode"] is None
        assert c.execute("SELECT COUNT(*) FROM personas WHERE builtin = 1").fetchone()[0] == 5
finally:
    db.connect = real_connect
assert chat.get_chat(cid)["messages"][0]["mode"] is None          # a user message has no answering mode
assert chat.get_chat(cid)["messages"][1]["mode"] == "library"

print("test_free_chat: all checks passed")
