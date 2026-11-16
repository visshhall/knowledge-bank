"""
test_memory.py — checks for memory.py (v0.14 memory about the owner) and how Free chat uses it.
Plain asserts: run with   python -I tests/test_memory.py   from the engine folder.
WHAT: add / edit / pin / delete / clear, limits and duplicates, the on/off switch, which facts fit the
      prompt (pinned first, then newest, within the character budget), that Free chat gets the facts
      and the library modes do not, suggestions parsed from a model reply (JSON, code fence, bullets;
      repeats and already-saved facts dropped; nothing saved until approved), and schema v17.
WHY:  memory must stay a plain list the owner controls: nothing may be saved without him, and facts
      must never leak into answers that are meant to come only from his files. The AI is replaced by
      a stand-in that records what it receives.
WHEN: before every release that touches memory.py or chat.build_free_prompt.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-memory-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import answers, chat, db, memory, ollama_client  # noqa: E402

assert db.init_db() == 21

# --- add, limits, duplicates ------------------------------------------------------------------------
assert memory.add("")["ok"] is False and memory.add("hi")["ok"] is False
assert memory.add("x" * 301)["ok"] is False
a = memory.add("Sells 3D-printed planters and lamps under the brand Ākāra")
b = memory.add("Prefers British English", pinned=True)
assert a["ok"] and b["ok"]
dup = memory.add("  sells 3D-printed PLANTERS and lamps, under the brand Ākāra!! ")
assert dup["ok"] is False and "already" in dup["message"]
listing = memory.list_all()
assert listing["enabled"] is True and listing["facts"][0]["text"] == "Prefers British English"   # pinned first
assert listing["facts"][0]["pinned"] is True

# --- edit, pin, delete ----------------------------------------------------------------------------------
assert memory.update(a["id"], text="Sells 3D-printed planters, lamps and vases under the brand Ākāra")["ok"]
assert memory.update(a["id"], text="no")["ok"] is False
assert memory.update(99999, text="whatever else")["ok"] is False
assert memory.update(b["id"], pinned=False)["ok"]
assert memory.list_all()["facts"][0]["text"] == "Prefers British English"   # same order: newest first, nothing pinned
assert memory.update(a["id"], pinned=True)["ok"]
assert memory.list_all()["facts"][0]["id"] == a["id"]                      # pinning moves it to the top
c = memory.add("Works from Mumbai")
assert memory.delete(c["id"])["ok"] and all(f["id"] != c["id"] for f in memory.list_all()["facts"])

# --- the prompt block: budget, order, off switch -----------------------------------------------------------
blk = memory.block()
assert blk.startswith("WHAT THE OWNER HAS TOLD YOU") and blk.index("planters") < blk.index("British")   # pinned first
assert "never list it back" in blk
for i in range(30):
    memory.add(f"Fact number {i} " + "word " * 20)
text = memory.block_text(memory.list_all()["facts"])
assert len(text) <= memory.PROMPT_CHARS and "Sells 3D-printed" in text   # pinned fact always fits
assert memory.list_all()["used_chars"] == len(text)
memory.set_enabled(False)
assert memory.block() == "" and memory.list_all()["enabled"] is False and len(memory.list_all()["facts"]) > 30   # off, not erased
memory.set_enabled(True)
assert memory.block()
assert memory.clear()["deleted"] > 30 and memory.list_all()["facts"] == [] and memory.block() == ""

# --- the limit on how many facts are kept ------------------------------------------------------------------
for i in range(memory.MAX_FACTS):
    assert memory.add(f"Fact {i} about something unique {i * 7}")["ok"]
assert "full" in memory.add("One more fact than allowed")["message"]
memory.clear()

# --- Free chat gets the facts, the library modes do not -------------------------------------------------------
memory.add("Sells 3D-printed planters and lamps under the brand Ākāra", pinned=True)
system, prompt = chat.build_free_prompt("Write a tagline", [], None)
assert "brand Ākāra" in system and "brand Ākāra" not in prompt
sources = [{"text": "Event ID 4625 records a failed logon.", "section": None}]
lib_system, lib_prompt = chat.build_prompt("What is 4625?", [], sources, general=False)
assert "Ākāra" not in lib_system and "Ākāra" not in lib_prompt
memory.set_enabled(False)
assert "brand Ākāra" not in chat.build_free_prompt("Write a tagline", [], None)[0]
memory.set_enabled(True)

# --- suggestions are parsed, cleaned and never saved on their own ---------------------------------------------
known = "Sells 3D-printed planters and lamps under the brand Ākāra"
assert memory.parse_proposals('["Based in Mumbai", "' + known + '", "based in mumbai!", "", "' + "y" * 400 + '"]') == ["Based in Mumbai"]
assert memory.parse_proposals('Here you go:\n```json\n["Uses a 4 GB graphics card", "Writes in British English"]\n```') == \
    ["Uses a 4 GB graphics card", "Writes in British English"]
assert memory.parse_proposals("- Likes short answers\n- Runs a small shop\nsome chatter") == ["Likes short answers", "Runs a small shop"]
assert memory.parse_proposals("nothing here") == [] and memory.parse_proposals("[]") == []
assert len(memory.parse_proposals(str([f"fact {i}" for i in range(12)]).replace("'", '"'))) == memory.SUGGEST_MAX

seen = {}
ollama_client.is_running = lambda: True
answers._sources = lambda q, limit=8: []


def fake_generate(model, prompt, system=None, temperature=0.2, num_ctx=8192, think=False, num_predict=None,
                  on_text=None, num_gpu=None, fallback=True, should_stop=None):
    seen.update(prompt=prompt, system=system)
    if "MESSAGES HE WROTE" in prompt:
        return ollama_client.GenerationResult('["Sells lamps", "Prefers short answers"]', 5, 5, 0, 0, 1.0, 1.0)
    return ollama_client.GenerationResult("ok", 5, 5, 0, 0, 1.0, 1.0)


ollama_client.generate = fake_generate
cid = chat.new_chat()["id"]
assert memory.suggest(cid)["ok"] is False                       # a chat with no messages from him
r = chat.send(cid, "I sell lamps and I prefer short answers. What is a good tagline?", mode="free")
for _ in range(100):
    if chat.status()["state"] != "running":
        break
    time.sleep(0.05)
assert memory.suggest(cid)["ok"]
for _ in range(100):
    if memory.suggest_status()["state"] != "running":
        break
    time.sleep(0.05)
st = memory.suggest_status()
assert st["state"] == "done" and st["proposals"] == ["Sells lamps", "Prefers short answers"], st
assert "I sell lamps" in seen["prompt"] and "Assistant" not in seen["prompt"]   # only HIS words are read
assert [f["text"] for f in memory.list_all()["facts"]] == [known]               # nothing saved without approval

# --- a failed suggestion is explained -----------------------------------------------------------------------------------
ollama_client.is_running = lambda: False
assert memory.suggest(cid)["ok"]
for _ in range(100):
    if memory.suggest_status()["state"] != "running":
        break
    time.sleep(0.05)
assert memory.suggest_status()["state"] == "error" and "Ollama" in memory.suggest_status()["message"]

print("test_memory: all checks passed")
