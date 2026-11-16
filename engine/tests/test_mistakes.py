"""
test_mistakes.py — checks for mistakes.py (v0.17 learn from mistakes). Run with   python -I tests/test_mistakes.py
WHAT: mistakes are logged from thumbs-down, Regenerate, Correct and fact-checker removals (once per message and
      kind); habits in his corrections are found by counting (too long/short, bullets, opener, closer);
      the AI's JSON reply is parsed safely (needs support, length limits, code fences); lessons are stored,
      merged when similar, capped at MAX_ACTIVE and applied per scope (free / library / both / all) to the
      instructions of a reply; a lesson that did not reduce mistakes is switched off by the app, one that did
      is marked working; the switch for the whole feature and per-lesson on/off/delete work; a pile of new
      mistakes starts a pattern search by itself.
WHEN: before a release that touches mistakes.py, training.py, or the lesson block in chat.py. No real AI used.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-mist-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import chat, db, mistakes, ollama_client, training  # noqa: E402

assert db.init_db() == 21
real_maybe_run = mistakes.maybe_run
mistakes.maybe_run = lambda: None          # logging must not start background work during these checks
ollama_client.is_running = lambda: True


def make_chat(mode="free"):
    with db.connect() as conn:
        return conn.execute("INSERT INTO chats(title, mode) VALUES ('t', ?)", (mode,)).lastrowid


def add(cid, role, content, mode="free", checks=None):
    with db.connect() as conn:
        return conn.execute("INSERT INTO chat_messages(chat_id, role, content, checks_json, mode) VALUES (?, ?, ?, ?, ?)",
                            (cid, role, content, json.dumps(checks or {}), mode if role == "assistant" else None)).lastrowid


def one(sql, args=()):
    with db.connect() as conn:
        return conn.execute(sql, args).fetchone()


def allrows(sql):
    with db.connect() as conn:
        return conn.execute(sql).fetchall()


def n(table, where="1=1"):
    with db.connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


LONG = "Certainly! Here is a fairly long answer about fluted planters and how they look in a living room. " * 3 + " Let me know if you need anything else."

# --- logging from the four sources -----------------------------------------------------------------------------
c = make_chat()
add(c, "user", "Describe the planter.")
a1 = add(c, "assistant", LONG)
training.record(a1, "down")
assert n("mistake_log", "kind = 'down'") == 1
training.record(a1, "down")
assert n("mistake_log", "kind = 'down'") == 1                      # same message and kind only once
add(c, "user", "Describe the lamp.")
a2 = add(c, "assistant", LONG + " lamp")
assert chat.undo_last(c, reason="regen")["ok"]
assert n("mistake_log", "kind = 'regen'") == 1
row = one("SELECT question, answer, mode FROM mistake_log WHERE kind = 'regen'")
assert row["question"] == "Describe the lamp." and "lamp" in row["answer"] and row["mode"] == "free"
add(c, "user", "Describe the vase.")
a3 = add(c, "assistant", LONG + " vase")
assert chat.undo_last(c, reason="edit")["ok"] and n("mistake_log", "kind = 'edit'") == 0   # Edit is neutral
add(c, "user", "Describe the vase.")
a4 = add(c, "assistant", LONG + " vase again")
assert training.correct(a4, "A tall matte vase with soft vertical flutes.")["ok"]
corr = one("SELECT answer, detail FROM mistake_log WHERE kind = 'correct'")
assert corr["detail"].startswith("A tall matte") and "vase again" in corr["answer"]
cl = make_chat("library")
add(cl, "user", "What is event 4625?")
lib = add(cl, "assistant", "It is a failed logon [1]. It also drops accounts.", mode="library")
mistakes.log_message("removed", lib, "claim about dropping accounts not in sources")
assert n("mistake_log", "kind = 'removed'") == 1 and n("mistake_log") == 4

# --- counting patterns ----------------------------------------------------------------------------------------------
rows = [{"answer": LONG + str(i), "detail": f"A tall vase number {i}."} for i in range(4)]
keys = {p["key"] for p in mistakes.count_patterns(rows)}
assert keys == {"len-short", "no-opener", "no-closer"}, keys
bullets = "Intro line.\n- first point here\n- second point here\n- third point here"
rows = [{"answer": bullets, "detail": "Plain prose version of the same points."} for _ in range(3)]
assert "bullets-off" in {p["key"] for p in mistakes.count_patterns(rows)}
rows = [{"answer": "Short.", "detail": "A much longer, fuller answer with concrete detail.\n- one\n- two"} for _ in range(3)]
keys = {p["key"] for p in mistakes.count_patterns(rows)}
assert "len-long" in keys and "bullets-on" in keys
assert mistakes.count_patterns(rows[:2]) == [] and mistakes.count_patterns([]) == []        # too few corrections
mixed = [{"answer": LONG, "detail": "x " * 100}, {"answer": "ok", "detail": "ok"}, {"answer": "hi there", "detail": "hi there!"}]
assert mistakes.count_patterns(mixed) == []                                                   # no habit

# --- parsing the model's reply --------------------------------------------------------------------------------------------
valid = {1: "down", 2: "down", 3: "correct"}
reply = '''Here you go:
```json
{"lessons": [
 {"text": "Give the command first, then explain it.", "scope": "free", "mistakes": [1, 2]},
 {"text": "Only one weak mistake supports this lesson text.", "scope": "free", "mistakes": [1]},
 {"text": "A single correction is enough support for this.", "scope": "weird", "mistakes": [3]},
 {"text": "short", "scope": "free", "mistakes": [1, 2]},
 {"text": "Cites ids that were never shown to the model.", "scope": "all", "mistakes": [98, 99]}]}
```'''
got = mistakes.parse_lessons(reply, valid)
assert [g["text"] for g in got] == ["Give the command first, then explain it.", "A single correction is enough support for this."]
assert got[1]["scope"] == "all" and mistakes.parse_lessons("no json", valid) == [] and mistakes.parse_lessons('{"lessons": 5}', valid) == []

# --- storing, merging, applying per scope ------------------------------------------------------------------------------------
r1 = mistakes.add_rule("Start with the answer, no pleasantries.", "free", "pattern", "no-opener", 3, [])
r2 = mistakes.add_rule("Only state commands that appear in the sources.", "library", "model", None, 2, [])
r3 = mistakes.add_rule("Label guesses clearly as guesses.", "both", "model", None, 2, [])
r4 = mistakes.add_rule("Keep a calm, precise tone everywhere.", "all", "model", None, 2, [])
assert len({r1, r2, r3, r4}) == 4
assert mistakes.add_rule("Start with the answer, no pleasantries!", "free", "model", None, 1, []) == r1      # merged, not duplicated
assert mistakes.add_rule("x", "free", "model", None, 1, []) is None and mistakes.add_rule("A" * 300, "free", "model", None, 1, []) is None
assert mistakes.add_rule("Fine text here ok.", "nowhere", "model", None, 1, []) is None
free, lib_b, both = mistakes.block("free"), mistakes.block("library"), mistakes.block("both")
assert "pleasantries" in free and "calm" in free and "commands" not in free and "guesses" not in free
assert "commands" in lib_b and "calm" in lib_b and "pleasantries" not in lib_b and "guesses" not in lib_b
assert "commands" in both and "guesses" in both and "calm" in both
assert "pleasantries" in chat.build_free_prompt("hello there", [], None)[0]                                   # reaches the reply
mistakes.set_enabled(False)
assert mistakes.block("free") == "" and "pleasantries" not in chat.build_free_prompt("hello there", [], None)[0]
mistakes.set_enabled(True)
assert mistakes.set_rule(r1, False)["ok"] and "pleasantries" not in mistakes.block("free")
assert mistakes.set_rule(r1, True)["ok"] and "pleasantries" in mistakes.block("free")

# --- cap on active lessons --------------------------------------------------------------------------------------------------------
SENTENCES = ["Prefer concrete numbers over vague adjectives.", "Never invent product names or model numbers.",
             "Mention the file name when quoting a command.", "Explain acronyms the first time they appear.",
             "Avoid emojis in professional replies.", "Put warnings before the steps they apply to.",
             "Summarise long answers in one closing sentence.", "Ask a clarifying question when the request is ambiguous.",
             "Use metric units and Indian rupee amounts.", "Quote error messages exactly as written.",
             "Separate facts from assumptions clearly.", "Offer one alternative when a plan has risks.",
             "Write dates as day, month name, year.", "Keep code blocks free of commentary.", "Name the tool before its command."]
for t in SENTENCES[:mistakes.MAX_ACTIVE + 3]:
    mistakes.add_rule(t, "all", "model", None, 1, [])
assert n("lesson_rules", "status = 'active'") == mistakes.MAX_ACTIVE and n("lesson_rules", "status = 'off'") >= 4

# --- did it help? (evaluate) ---------------------------------------------------------------------------------------------------------
with db.connect() as conn:
    conn.execute("DELETE FROM lesson_rules"); conn.execute("DELETE FROM mistake_log")
    conn.execute("DELETE FROM chat_messages")
def rule(text, base, scope="free"):
    rid = mistakes.add_rule(text, scope, "model", None, 2, [])
    with db.connect() as conn:
        conn.execute("UPDATE lesson_rules SET baseline_rate = ?, created_at = '2000-01-01 00:00:00' WHERE id = ?", (base, rid))
    return rid
good, bad, none_ = rule("Lesson that works well here.", 0.5), rule("Lesson that makes no difference.", 0.1), rule("Lesson without any baseline.", None)
c = make_chat()
for i in range(12):
    mid = add(c, "assistant", f"answer {i}", mode="free")
    add(c, "user", "q")
mistakes.evaluate()                                              # 12 answers, no mistakes after → rate 0
v = {r["id"]: r for r in mistakes.status()["rules"]}
assert v[good]["verdict"] == v[none_]["verdict"] == v[bad]["verdict"] == "working"   # no mistakes after → rate 0
for i in range(4):
    mistakes.log_raw("down", c, 1000 + i, "free", "q", "a")       # 4 of 12 = 0.33 after
mistakes.evaluate()
with db.connect() as conn:
    conn.execute("UPDATE lesson_rules SET verdict = 'new', status = 'active' WHERE id = ?", (bad,))
mistakes.evaluate()
v = {r["id"]: r for r in mistakes.status()["rules"]}
assert v[bad]["verdict"] == "not_helping" and v[bad]["status"] == "off" and "did not get better" in v[bad]["note"]
assert v[good]["verdict"] == "working" and v[good]["status"] == "active"          # judged once, kept
assert mistakes.set_rule(bad, True)["ok"] and {r["id"]: r for r in mistakes.status()["rules"]}[bad]["status"] == "active"
assert mistakes.delete_rule(bad)["ok"] and mistakes.delete_rule(bad)["ok"] is False

# --- AI pattern search end to end (fake model) ---------------------------------------------------------------------------------------------
with db.connect() as conn:
    conn.execute("DELETE FROM lesson_rules"); conn.execute("DELETE FROM mistake_log")
for i in range(5):
    mistakes.log_raw("down", c, 2000 + i, "free", f"question {i}", f"a rambling answer {i}")
ids = [r["id"] for r in allrows("SELECT id FROM mistake_log ORDER BY id")]
seen = {}
def fake(model, prompt, system=None, temperature=0.2, num_ctx=8192, think=False, num_predict=None, on_text=None,
         num_gpu=None, fallback=True, should_stop=None):
    seen["prompt"], seen["system"] = prompt, system
    return ollama_client.GenerationResult(json.dumps({"lessons": [{"text": "Answer in at most three short paragraphs.",
                                                                  "scope": "free", "mistakes": ids[:3]}]}), 10, 10, 0, 0, 1, 1)
ollama_client.generate = fake
out = mistakes.run_patterns()
assert out["ok"] and out["new_lessons"] == 1 and "a rambling answer 0" in seen["prompt"], out
assert n("mistake_log", "rule_id IS NOT NULL") == 3 and "three short paragraphs" in mistakes.block("free")
# busy chat → the AI is not used
chat._state["state"] = "running"
assert mistakes._distill_with_model() == 0
chat._state["state"] = "idle"

# --- automatic start after enough new mistakes ----------------------------------------------------------------------------------------------
mistakes.maybe_run = real_maybe_run
called = []
mistakes.run_patterns = lambda *a, **k: called.append(1)
mistakes._last_run = 0.0
with db.connect() as conn:
    conn.execute("UPDATE mistake_log SET rule_id = 1")                      # everything assigned
mistakes.maybe_run(); time.sleep(0.2)
assert called == []                                                         # nothing waiting → no search
for i in range(mistakes.DISTILL_AT):
    mistakes.log_raw("down", c, 3000 + i, "free", "q", "a")
time.sleep(0.4)
assert called, "a pile of new mistakes should start a search"
print("test_mistakes: all checks passed")
