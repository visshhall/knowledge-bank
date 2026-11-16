"""
test_chat.py — checks for chat.py (v0.11 Chat) and the removal clean-up of saved answers.
Plain asserts: run with   python -I tests/test_chat.py   from the engine folder.
WHAT: saved chats (create, search, rename, delete), a full question → cited, fact-checked reply
      with a stand-in for the AI, the library-first / general-knowledge switch, follow-up questions
      carrying history, the Stop button, and the clean-up that clears answers citing a removed file.
WHY:  Chat is the one screen that writes in conversation, so a mistake here would show up as an
      invented fact or a leftover of a removed PDF. No real AI is needed: ollama_client.generate is
      replaced by a small function that returns fixed text.
WHEN: before every release that touches chat.py, answers.py or the removal clean-up in importer.py.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-chat-test-")  # a throw-away bank
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import answers, chat, db, importer, ollama_client  # noqa: E402

db.init_db()

# --- stand-ins -------------------------------------------------------------------------------------
SOURCES = [
    {"passage_id": 1, "point_id": 1, "source_id": 7, "file_name": "rdp.pdf", "page_number": 3,
     "section": "Detection", "topic_id": None, "topic_title": "RDP attacks",
     "text": "Event ID 4625 records a failed logon. Many failures from one address suggest RDP brute force."},
    {"passage_id": 2, "point_id": 2, "source_id": 8, "file_name": "spray.pdf", "page_number": 9,
     "section": None, "topic_id": None, "topic_title": None,
     "text": "Password spraying tries one password against many accounts."},
]
calls = []           # every prompt the fake AI received
reply_text = [""]    # what the fake AI will say next
hold = [False]       # True: the fake AI keeps "writing" until Stop is pressed
sources_now = [SOURCES]

answers._sources = lambda q, limit=8: [dict(s) for s in sources_now[0]]
ollama_client.is_running = lambda: True


def fake_generate(model, prompt, system=None, temperature=0.2, num_ctx=8192, think=False,
                  num_predict=None, on_text=None, num_gpu=None, fallback=True, should_stop=None):
    calls.append({"prompt": prompt, "system": system, "model": model})
    if hold[0]:
        for _ in range(100):               # up to ~5 s of "writing", ends the moment Stop is pressed
            if should_stop and should_stop():
                break
            time.sleep(0.05)
        return ollama_client.GenerationResult("Event ID 4625 records a failed logon [1].", 0, 0, 0, 0, 0, 0)
    return ollama_client.GenerationResult(reply_text[0], 10, 10, 0, 0, 1.0, 1.0)


ollama_client.generate = fake_generate


def run(text, chat_id=None, general=False):
    """Send a message and wait for the reply (or error)."""
    r = chat.send(chat_id, text, general)
    assert r["ok"], r
    for _ in range(200):
        if chat.status()["state"] != "running":
            break
        time.sleep(0.05)
    st = chat.status()
    assert st["state"] in ("done", "error", "idle"), st
    return r["chat_id"], st


# 1. A new chat is named after the first question; the reply is cited and fact-checked.
reply_text[0] = "Event ID 4625 records a failed logon [1].\nEvent ID 9999 shows a success [1]."
cid, st = run("How do I spot an RDP brute force?")
assert st["state"] == "done", st
c = chat.get_chat(cid)
assert c["title"] == "How do I spot an RDP brute force?", c["title"]
assert [m["role"] for m in c["messages"]] == ["user", "assistant"]
a = c["messages"][1]
assert "4625" in a["content"] and "9999" not in a["content"], a["content"]   # unsupported ID removed
assert a["checks"]["removed_count"] == 1
assert a["sources"]["1"]["cited"] is True and a["sources"]["2"]["cited"] is False
assert a["general"] is False and a["sources"]["1"]["source_id"] == 7

# 2. A follow-up carries the earlier turns, and a short follow-up borrows the earlier question for search.
reply_text[0] = "Password spraying tries one password against many accounts [2]."
n = len(calls)
cid2, st = run("and for spraying?", cid)
assert cid2 == cid and st["state"] == "done"
assert "How do I spot an RDP brute force?" in calls[n]["prompt"], "history must be in the prompt"
assert "Event ID 4625 records a failed logon" in calls[n]["prompt"], "earlier answer must be in the prompt"
prev = [{"role": "user", "content": "RDP brute force"}]
assert chat._search_text("and for spraying?", prev).startswith("RDP brute force")
assert chat._search_text("and how do I detect it?", prev).startswith("RDP brute force"), "6-word follow-up with 'it'"
assert chat._search_text("What are the main ways attackers abuse scheduled tasks on Windows servers?", prev) == \
    "What are the main ways attackers abuse scheduled tasks on Windows servers?", "long standalone question is searched alone"
assert chat._search_text("Explain Kerberoasting", prev).startswith("RDP brute force"), "short message borrows"
assert chat._search_text("How do attackers use RDP brute force to get in?", []) == "How do attackers use RDP brute force to get in?"
assert len(chat.get_chat(cid)["messages"]) == 4

# 3. Library only: nothing matches → a plain explanation and NO call to the AI.
sources_now[0] = []
n = len(calls)
_, st = run("What is the capital of Peru?", None, general=False)
assert len(calls) == n, "no AI call when nothing matches and general knowledge is off"
cid3 = chat.list_chats()["chats"][0]["id"]
last = chat.get_chat(cid3)["messages"][-1]
assert "don't cover this" in last["content"] and "general knowledge" in last["content"], last["content"]

# 4. General knowledge on, nothing matches → the whole reply is marked as not from the files.
reply_text[0] = "Lima is the capital of Peru [1]."
_, st = run("What is the capital of Peru?", cid3, general=True)
g = chat.get_chat(cid3)["messages"][-1]
assert g["content"].startswith(chat.GENERAL_MARK), g["content"]
assert g["general"] is True and "[1]" not in g["content"]
sources_now[0] = SOURCES

# 5. General knowledge on, files match → file part is checked, general part is separate and unmarked by [n].
reply_text[0] = ("Event ID 4625 records a failed logon [1].\n\nFrom general knowledge (not from your files):\n"
                 "Spraying is slower but quieter [2].")
_, st = run("Explain RDP failed logons and spraying", cid, general=True)
m = chat.get_chat(cid)["messages"][-1]
assert m["general"] is True and chat.GENERAL_MARK in m["content"], m["content"]
head, tail = m["content"].split(chat.GENERAL_MARK)
assert "4625" in head and "[1]" in head and "[2]" not in tail

# 6. General knowledge OFF: even if the model adds a general section, it is treated as part of the checked text.
reply_text[0] = "Event ID 4625 records a failed logon [1].\nFrom general knowledge (not from your files):\nInvented 7777."
_, st = run("Failed logons?", cid, general=False)
m = chat.get_chat(cid)["messages"][-1]
assert "7777" not in m["content"] and m["general"] is False, m["content"]

# 7. "NOT IN SOURCES" becomes a plain explanation.
reply_text[0] = "NOT IN SOURCES"
_, st = run("Something unrelated about cooking", cid, general=False)
assert "don't cover this" in chat.get_chat(cid)["messages"][-1]["content"]

# 7b. The model explains what is missing AND adds the code phrase: keep the explanation, drop phrase and markers.
reply_text[0] = "The sources do not describe detection of this [1][2]. NOT IN SOURCES"
_, st = run("How do I detect cooking attacks in the sources?", cid, general=False)
m = chat.get_chat(cid)["messages"][-1]
assert "NOT IN SOURCES" not in m["content"] and "[1]" not in m["content"] and "do not describe detection" in m["content"], m["content"]

# 7c. A line of bare markers is dropped.
reply_text[0] = "Event ID 4625 records a failed logon [1].\n[1][2]"
_, st = run("What is 4625?", cid, general=False)
assert chat.get_chat(cid)["messages"][-1]["content"].strip() == "Event ID 4625 records a failed logon [1]."

# 8. Stop keeps what was written (and checks it).
hold[0] = True
r = chat.send(cid, "Tell me about 4625", False)
time.sleep(0.4)
chat.stop()
for _ in range(100):
    if chat.status()["state"] != "running":
        break
    time.sleep(0.05)
hold[0] = False
assert chat.status()["state"] == "done"
assert "Stopped" in chat.get_chat(cid)["messages"][-1]["content"]

# 9. Only one reply is written at a time.
hold[0] = True
r1 = chat.send(cid, "first question here", False)
r2 = chat.send(cid, "second question here", False)
assert r1["ok"] and not r2["ok"], (r1, r2)
chat.stop()
for _ in range(100):
    if chat.status()["state"] != "running":
        break
    time.sleep(0.05)
hold[0] = False

# 10. Search finds chats by title or message text; % is matched literally; rename and delete work.
assert any(x["id"] == cid for x in chat.list_chats("brute force")["chats"])
assert any(x["id"] == cid for x in chat.list_chats("Password spraying")["chats"])
assert chat.list_chats("zzzzqqq")["chats"] == []
assert chat.list_chats("100%")["chats"] == []            # no crash, no wildcard match
assert chat.rename_chat(cid, "  RDP notes  ")["ok"] and chat.get_chat(cid)["title"] == "RDP notes"
assert not chat.rename_chat(cid, "   ")["ok"]
assert chat.delete_chat(cid)["ok"] and chat.get_chat(cid) is None
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?", (cid,)).fetchone()[0] == 0

# 11. Removing a file clears the chat answers that cited it, and the saved Answers too (v0.9.2 bug fixed).
c = chat.new_chat("Cleanup test")["id"]
with db.connect() as conn:
    conn.execute("INSERT INTO chat_messages(chat_id, role, content, sources_json) VALUES (?, 'assistant', 'quote from file 7', ?)",
                 (c, json.dumps({"1": {"source_id": 7, "text": "x"}})))
    conn.execute("INSERT INTO chat_messages(chat_id, role, content, sources_json) VALUES (?, 'assistant', 'quote from file 8', ?)",
                 (c, json.dumps({"1": {"source_id": 8, "text": "y"}})))
    conn.execute("INSERT INTO answers(question, body_markdown, sources_json, checks_json, model_used, seconds) "
                 "VALUES ('q7', 'a', ?, '{}', 'm', 1)", (json.dumps({"1": {"source_id": 7}}),))
    conn.execute("INSERT INTO answers(question, body_markdown, sources_json, checks_json, model_used, seconds) "
                 "VALUES ('q8', 'a', ?, '{}', 'm', 1)", (json.dumps({"1": {"source_id": 8}}),))
    out = importer._clean_up_after_removal(conn, [7], set())
assert out["answers"] == 1 and out["chat_answers"] == 1, out
msgs = chat.get_chat(c)["messages"]
assert msgs[0]["content"] == chat.CLEARED and msgs[0]["sources"] == {}
assert msgs[1]["content"] == "quote from file 8"
with db.connect() as conn:
    assert [r[0] for r in conn.execute("SELECT question FROM answers")] == ["q8"]
assert importer._cited_source_ids("not json") == set()
assert importer._cited_source_ids('[{"source_id": "5"}, {"x": 1}]') == {5}

print("test_chat.py: all checks passed")
