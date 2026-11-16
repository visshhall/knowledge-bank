"""
test_modelpick.py — checks for modelpick.py (v0.11 model picker and compare-on-my-files).
Plain asserts: run with   python -I tests/test_modelpick.py   from the engine folder.
WHAT: the picker only accepts real, downloaded, answer-writing models; the choice is saved and Chat uses it;
      a comparison asks every model the SAME questions with the SAME passages, fact-checks each answer,
      and reports speed, cited sources and removed sentences; bad requests are refused with a plain message.
WHY:  A wrong model name must never be saved (Chat would stop working), and a comparison must be fair.
      The AI and Ollama are replaced by small stand-ins, so no model is needed.
WHEN: before every release that touches modelpick.py or chat.build_prompt.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-pick-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import answers, chat, db, modelpick, ollama_client, setup_manager  # noqa: E402

db.init_db()

INSTALLED = [{"name": "qwen3.5:4b", "size_mb": 3400}, {"name": "phi4-mini:latest", "size_mb": 2500},
             {"name": "nomic-embed-text:latest", "size_mb": 270}]
SRC = [{"passage_id": 1, "point_id": 1, "source_id": 7, "file_name": "a.pdf", "page_number": 1, "section": None,
        "topic_id": None, "topic_title": None, "text": "Event ID 4625 records a failed logon."}]
asked = []   # (model, prompt) for every request the stand-in AI received

ollama_client.is_running = lambda: True
ollama_client.installed_details = lambda: [dict(m) for m in INSTALLED]
ollama_client.installed_models = lambda: [m["name"] for m in INSTALLED]
ollama_client.clear_gpu_except = lambda keep=None, wait_seconds=20: None
ollama_client.unload = lambda m: None
ollama_client.speeds = lambda: {"qwen3.5:4b": {"kind": "tokens/s", "value": 11.6, "at": "10:00"}}
answers._sources = lambda q, limit=8: [dict(s) for s in SRC]
setup_manager.status = lambda: {"models": {"list": [], "job": {"state": "idle", "message": "", "current": None}}}
downloads = []
setup_manager.start_model_downloads = lambda include_benchmark_extras=True, names=None, force=False: (
    downloads.append(names) or {"ok": True, "message": "Started."})


def fake_generate(model, prompt, system=None, **kw):
    asked.append((model, prompt))
    text = ("Event ID 4625 records a failed logon [1]." if model.startswith("qwen")
            else "Event ID 4625 records a failed logon [1].\nEvent ID 1234 is a success [1].")
    return ollama_client.GenerationResult(text, 10, 20, 0, 0, 2.0, 2.5)


ollama_client.generate = fake_generate

# 1. Choices: embedding models are hidden, the current one is marked, suggestions exclude installed models.
c = modelpick.choices()
names = [m["name"] for m in c["installed"]]
assert names == ["qwen3.5:4b", "phi4-mini:latest"], names
assert c["current"] == "qwen3.5:4b" and [m["current"] for m in c["installed"]] == [True, False]
assert c["installed"][0]["speed"]["value"] == 11.6
sugg = [s["name"] for s in c["suggested"]]
assert "phi4-mini" not in sugg and "gemma3:4b" in sugg, sugg

# 2. Select: only downloaded, answer-writing models; the pick is saved and Chat uses it.
assert not modelpick.select("gemma3:4b")["ok"]                  # not downloaded
assert not modelpick.select("nomic-embed-text")["ok"]           # cannot write
assert not modelpick.select("bad name; rm -rf")["ok"]           # not a model name
assert db.get_setting("chat_model") is None
assert modelpick.select("phi4-mini")["ok"]                      # accepts the name without :latest
assert chat.chat_model() == "phi4-mini" and modelpick.choices()["current"] == "phi4-mini"
db.set_setting("chat_model", "qwen3.5:4b")

# 3. Download validates the name and starts the shared download job.
assert not modelpick.download("x y")["ok"] and downloads == []
assert modelpick.download("gemma3:4b")["ok"] and downloads == [["gemma3:4b"]]

# 4. Compare: bad requests are refused in plain words.
assert not modelpick.start_compare(["qwen3.5:4b"])["ok"]
assert not modelpick.start_compare(["qwen3.5:4b", "llama3.2:3b"], ["A real question here"])["ok"]
assert not modelpick.start_compare(["qwen3.5:4b", "phi4-mini"])["ok"], "no topics and no questions → plain message"

# 5. Compare: same questions and passages for each model; results carry speed, citations and removals.
r = modelpick.start_compare(["qwen3.5:4b", "phi4-mini"], ["What is event 4625?", "How is it used in RDP attacks?"])
assert r["ok"], r
for _ in range(200):
    if modelpick.compare_status()["state"] != "running":
        break
    time.sleep(0.05)
st = modelpick.compare_status()
assert st["state"] == "done", st
by = {x["model"]: x for x in st["results"]}
assert set(by) == {"qwen3.5:4b", "phi4-mini"}
assert [a["question"] for a in by["qwen3.5:4b"]["answers"]] == [a["question"] for a in by["phi4-mini"]["answers"]]
assert by["qwen3.5:4b"]["removed_total"] == 0 and by["phi4-mini"]["removed_total"] == 2   # 1234 removed twice
assert by["qwen3.5:4b"]["cited_total"] == 2 and by["qwen3.5:4b"]["avg_tokens_per_s"] == 10.0
assert "1234" not in by["phi4-mini"]["answers"][0]["answer"]
prompts = {q: set() for q in ("What is event 4625?", "How is it used in RDP attacks?")}
for model, prompt in asked:
    for q in prompts:
        if f"QUESTION: {q}" in prompt:
            prompts[q].add(prompt)
assert all(len(v) == 1 for v in prompts.values()), "every model must receive the identical prompt per question"

# 6. Cancel stops between questions and reports it.
slow = []


def slow_generate(model, prompt, system=None, **kw):
    slow.append(model)
    time.sleep(0.3)
    return ollama_client.GenerationResult("Event ID 4625 records a failed logon [1].", 1, 1, 0, 0, 1.0, 1.0)


ollama_client.generate = slow_generate
assert modelpick.start_compare(["qwen3.5:4b", "phi4-mini"], ["Question number one", "Question number two"])["ok"]
time.sleep(0.1)
modelpick.cancel_compare()
for _ in range(200):
    if modelpick.compare_status()["state"] != "running":
        break
    time.sleep(0.05)
assert modelpick.compare_status()["state"] == "cancelled" and len(slow) < 4

print("test_modelpick.py: all checks passed")
