"""
test_libtrain.py — checks for libtrain.py (v0.23: every page of the owner's files becomes checked training material,
then a training package and the trained model's import).
Run with   python -I tests/test_libtrain.py   from the engine folder. A fake question writer stands in for the model and a
fake `ollama` program stands in for the AI engine, so nothing real is downloaded or trained.
WHAT: answers whose numbers/IDs are not on the page, that lean on words not on the page, or that say "this page" are
      dropped and counted with a reason; good pairs are kept; short pages are marked done as skipped (no model call);
      reading goes file by file in page order and stops when every page is read; web-learned and replaced files are never
      read; status() counts pages, pairs, files, categories, per-day series and a time estimate; switching off and a
      running chat both pause reading; rejecting a pair keeps it out of the package; the package holds the text of EVERY
      page (also pages not yet read), the kept pairs, the chat examples, a manifest, a valid notebook and a zip; long pages
      are cut into pieces no longer than the limit; a wrong or truncated .gguf is refused; the import builds a Modelfile
      from the base model's own (FROM replaced, extra FROM lines dropped), creates kb-tuned, switches Chat to it and
      remembers the earlier model; switching back works.
WHEN: before a release that touches libtrain.py, training.chat_lines or the lib_* tables.
"""
import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-libtrain-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import chat, db, libtrain, ollama_client, setup_manager  # noqa: E402

assert db.init_db() == 23

PAGE = ("Microsoft Sentinel analytics rules run KQL queries on a schedule. A scheduled rule with a query frequency of "
        "5 minutes and a lookup period of 1 hour creates incidents from matching events. Event ID 4625 records a failed "
        "sign-in on Windows. The SecurityEvent table holds Windows security events collected by the agent, and the "
        "SigninLogs table holds Entra ID sign-ins. Analysts tune rules by adding watchlists of trusted IP ranges.")
GOOD = [{"q": "What does Event ID 4625 record on Windows?", "a": "Event ID 4625 records a failed sign-in on Windows."},
        {"q": "Which table holds Entra ID sign-ins?", "a": "The SigninLogs table holds Entra ID sign-ins."}]
BAD_NUMBER = {"q": "How often do scheduled rules run?", "a": "Scheduled rules in Microsoft Sentinel run every 15 minutes."}
BAD_WORDS = {"q": "What is Sentinel?", "a": "Sentinel is a cloud SIEM platform offering SOAR playbooks, UEBA, threat intelligence feeds and notebooks."}
BAD_SELF = {"q": "What does this page say about watchlists?", "a": "Analysts tune rules by adding watchlists of trusted IP ranges."}
calls = {"ask": 0}


def fake_ask(prompt):
    calls["ask"] += 1
    assert "PAGE TEXT:" in prompt and "Reply with JSON only" in prompt
    return "Here you go:\n```json\n" + json.dumps(GOOD + [BAD_NUMBER, BAD_WORDS, BAD_SELF, GOOD[0]]) + "\n```"


libtrain._ask = fake_ask
state = {"ollama": True, "chat": "idle"}
ollama_client.is_running = lambda: state["ollama"]
chat.status = lambda: {"state": state["chat"]}
db.set_setting("chat_model", "qwen3.5:4b")
n = {"i": 0}


def add(title, pages, origin=None, status="extracted", cat="SIEM & Detection"):
    n["i"] += 1
    with db.connect() as conn:
        sid = conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories, origin) "
            "VALUES (?, ?, ?, 'pdf', 1, ?, ?, ?, ?)",
            (f"l{n['i']}", title + ".pdf", f"/x/{n['i']}", status, title, json.dumps([cat]), origin)).lastrowid
        for i, text in enumerate(pages, start=1):
            pid = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, ?, ?)", (sid, i, text)).lastrowid
            conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) "
                         "VALUES (?, ?, ?, 0, ?, ?)", (sid, pid, i, text, f"h{sid}-{i}"))
    return sid


# --- parsing and checking ---
assert libtrain.parse_pairs('junk [{"q": "a?", "a": "b"}] junk') == [("a?", "b")]
assert libtrain.parse_pairs("no json here") == [] and libtrain.parse_pairs("[not json]") == []
assert libtrain.pairs_wanted(300) == 2 and libtrain.pairs_wanted(50_000) == 6
assert libtrain.check_pair(GOOD[0]["q"], GOOD[0]["a"], PAGE) == (True, "")
assert libtrain.check_pair(BAD_NUMBER["q"], BAD_NUMBER["a"], PAGE) == (False, "a fact is not on the page")
assert libtrain.check_pair(BAD_WORDS["q"], BAD_WORDS["a"], PAGE)[1] == "not enough of it is on the page"
assert libtrain.check_pair(BAD_SELF["q"], BAD_SELF["a"], PAGE)[1] == "refers to the page"
assert libtrain.check_pair("Q?", "Too short.", PAGE)[1] == "too short"

# --- reading pages ---
a = add("Sentinel guide", [PAGE, "Contents", PAGE.replace("Sentinel", "Microsoft Sentinel")])
b = add("Cloud notes", [PAGE], cat="Cloud")
web = add("Web page", [PAGE], origin="learned")
old = add("Old guide", [PAGE])
with db.connect() as conn:  # an older version of file b (replaced files are never read)
    conn.execute("UPDATE sources SET replaced_by = ? WHERE id = ?", (b, old))
order = libtrain.next_pages(10)
with db.connect() as conn:
    srcs = [conn.execute("SELECT source_id, page_number FROM pages WHERE id = ?", (p,)).fetchone() for p in order]
assert [(s[0], s[1]) for s in srcs] == [(a, 1), (a, 2), (a, 3), (b, 1)], srcs  # file by file, page order; no web/replaced

st0 = libtrain.status()
assert st0["pages"] == {"total": 4, "done": 0, "skipped": 0, "left": 4, "pct": 0} and st0["files"] == {"total": 2, "done": 0}

r = libtrain.run_round(2)
assert r["read"] == 2 and calls["ask"] == 1  # page 2 ("Contents") is skipped without asking the model
with db.connect() as conn:
    rows = {x["page_id"]: dict(x) for x in conn.execute("SELECT * FROM lib_pages_done")}
    kept = conn.execute("SELECT COUNT(*) FROM lib_qa").fetchone()[0]
assert kept == 2  # the two good pairs; the repeat of GOOD[0] is not stored twice
first = rows[order[0]]
# a short page asks for 2 pairs and looks at no more than 2 + 2 of the reply: GOOD x2 kept, the next two dropped
assert first["kept"] == 2 and first["dropped"] == 2 and first["skipped"] == 0
assert json.loads(first["reasons_json"]) == {"a fact is not on the page": 1, "not enough of it is on the page": 1}
assert rows[order[1]]["skipped"] == 1

state["chat"] = "running"
assert libtrain.run_round(2)["read"] == 0  # the owner's own question goes first
state["chat"] = "idle"
libtrain.set_on(False)
assert libtrain.run_round(2) == {"read": 0, "reason": "off"}
libtrain.set_on(True)
state["ollama"] = False
assert libtrain.run_round(2)["read"] == 0
state["ollama"] = True
assert libtrain.run_round(5)["read"] == 2
assert libtrain.run_round(5)["read"] == 0 and libtrain.next_pages(5) == []

st = libtrain.status()
assert st["pages"]["done"] == 4 and st["pages"]["pct"] == 100 and st["pages"]["skipped"] == 1 and st["eta_hours"] == 0
assert st["pairs"]["kept"] == 6 and st["pairs"]["dropped"] == 6, st["pairs"]
assert st["files"] == {"total": 2, "done": 2}
assert {c["name"]: c["pct"] for c in st["categories"]} == {"SIEM & Detection": 100, "Cloud": 100}
assert len(st["daily"]) == 30 and st["daily"][-1]["pages"] == 4 and st["daily"][-1]["pairs"] == 6
assert st["sec_per_page"] is not None and len(st["recent"]) == 6 and st["recent"][0]["file"]

# --- package ---
rej = st["recent"][0]["id"]
libtrain.reject(rej)
c = add("New file", [PAGE + " Extra line about watchlists."])  # not read yet: still in the raw text
with db.connect() as conn:  # one long page, to prove pieces are cut to size
    long_text = " ".join(f"Sentence number {i} explains detection tuning for analysts." for i in range(200))
    pid = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, 2, ?)", (c, long_text)).lastrowid
    conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) VALUES (?, ?, 2, 0, ?, 'hl')",
                 (c, pid, long_text))
    cid = conn.execute("INSERT INTO chats(title, mode) VALUES ('t', 'free')").lastrowid
    mid = conn.execute("INSERT INTO chat_messages(chat_id, role, content, mode) VALUES (?, 'assistant', 'x', 'free')",
                       (cid,)).lastrowid
    conn.execute("INSERT INTO training_examples(message_id, chat_id, kind, system, prompt, response, status) VALUES "
                 "(?, ?, 'liked', '', 'How do I tune a rule?', 'Add a watchlist of trusted ranges and re-test the rule.', 'new')",
                 (mid, cid))
pk = libtrain.build_package()
assert pk["ok"], pk
folder = Path(pk["folder"])
text = [json.loads(l)["text"] for l in (folder / "kb_text.jsonl").read_text(encoding="utf-8").splitlines()]
assert any("New file, page 1" in t for t in text) and not any("Web page" in t or "Old guide" in t for t in text)
assert all(len(t.split(":\n", 1)[1]) <= libtrain.TEXT_CHUNK_CHARS for t in text)
assert sum("New file, page 2" in t for t in text) >= 5  # the long page became several pieces
qa = [json.loads(l) for l in (folder / "kb_qa.jsonl").read_text(encoding="utf-8").splitlines()]
with db.connect() as conn:
    rq = conn.execute("SELECT question FROM lib_qa WHERE id = ?", (rej,)).fetchone()[0]
# 6 kept rows = the same 2 pairs from 3 pages: trained once each, and the rejected one is out everywhere
assert len(qa) == 1 and qa[0]["messages"][0]["role"] == "user" and qa[0]["messages"][0]["content"] != rq, qa
assert len((folder / "kb_chat.jsonl").read_text(encoding="utf-8").splitlines()) == 1
man = json.loads((folder / "manifest.json").read_text())
assert man["hf_base"] == "unsloth/Qwen3.5-4B" and man["ollama_base"] == "qwen3.5:4b" and man["model_name"] == "kb-tuned"
nb = json.loads(Path(pk["notebook"]).read_text())
code = "".join("".join(cl["source"]) for cl in nb["cells"] if cl["cell_type"] == "code")
assert nb["nbformat"] == 4 and "unsloth/Qwen3.5-4B" in code and "save_pretrained_gguf" in code and "MAX_MINUTES" in code
for cl in nb["cells"]:  # every code cell is valid Python once Colab's ! and %% lines are taken out
    if cl["cell_type"] == "code":
        out, shell = [], False
        for line in "".join(cl["source"]).splitlines():
            if shell or line.lstrip().startswith(("!", "%")):  # Colab shell/magic line (and its \ continuation lines)
                if not shell:  # continuation lines belong to the command above: no extra statement
                    out.append(line[:len(line) - len(line.lstrip())] + "pass")
                shell = line.rstrip().endswith("\\")
            else:
                out.append(line)
        compile("\n".join(out), "cell", "exec")
assert set(zipfile.ZipFile(pk["zip"]).namelist()) == {"kb_text.jsonl", "kb_qa.jsonl", "kb_chat.jsonl", "manifest.json"}
assert "kb-model.gguf" in (folder / "README.txt").read_text()
db.set_setting("chat_model", "llama3.2:3b")
assert libtrain.base_model()[0] == "qwen3.5:4b" and libtrain.base_model()[2]  # unsupported chat model: told, trains 4B
db.set_setting("chat_model", "qwen3.5:4b")

# --- bringing the model back ---
tmp = Path(tempfile.mkdtemp())
(tmp / "x.txt").write_text("hi")
assert "gguf" in libtrain.check_gguf(str(tmp / "x.txt"))
small = tmp / "small.gguf"
small.write_bytes(b"GGUF" + b"0" * 100)
assert "too small" in libtrain.check_gguf(str(small))
fake = tmp / "kb-model.gguf"
with open(fake, "wb") as f:
    f.write(b"NOPE")
    f.truncate(libtrain.MIN_GGUF_BYTES + 10)
assert "not a GGUF" in libtrain.check_gguf(str(fake))
with open(fake, "r+b") as f:
    f.write(b"GGUF")
assert libtrain.check_gguf(str(fake)) is None

mf = libtrain._modelfile("# made by ollama\nFROM /blobs/sha256-abc\nFROM /blobs/sha256-vision\nTEMPLATE {{ .Prompt }}\nPARAMETER stop <|im_end|>", "C:/m/kb-model.gguf")
assert mf.count("FROM") == 1 and 'FROM "C:/m/kb-model.gguf"' in mf and "TEMPLATE {{ .Prompt }}" in mf and "PARAMETER stop" in mf

ran = []


class Done:
    def __init__(self, out="", code=0):
        self.stdout, self.stderr, self.returncode = out, "", code


def fake_run(args, timeout):
    ran.append(args[1:])
    if args[1] == "show":
        return Done("FROM /blobs/base\nRENDERER qwen3.5\nPARSER qwen3.5\n")
    return Done("success")


libtrain._run = fake_run
setup_manager.find_ollama_exe = lambda: "ollama"
installed = {"qwen3.5:4b"}
ollama_client.has_model = lambda name, installed_list=None: name in installed or name.split(":")[0] in {m.split(":")[0] for m in installed}
assert libtrain.start_import(str(fake))["ok"]
for _ in range(100):
    if libtrain.status()["import"]["state"] != "running":
        break
    time.sleep(0.05)
imp = libtrain.status()["import"]
assert imp["state"] == "done", imp
assert ran[0] == ["show", "qwen3.5:4b", "--modelfile"] and ran[1][:2] == ["create", "kb-tuned"]
written = (Path(os.environ["KB_DATA_DIR"]) / "training" / "model" / "Modelfile").read_text()
assert "RENDERER qwen3.5" in written and str(fake) in written
assert db.get_setting("chat_model") == "kb-tuned:latest" and db.get_setting("chat_model_before_tuned") == "qwen3.5:4b"
installed.add("kb-tuned:latest")
from kb_engine import modelpick  # noqa: E402
assert modelpick.select is not None
assert libtrain.use_model("previous")["ok"] and db.get_setting("chat_model") == "qwen3.5:4b"
assert libtrain.use_model("tuned")["ok"] and db.get_setting("chat_model") == "kb-tuned:latest"
assert libtrain.base_model()[0] == "qwen3.5:4b"  # training again from a tuned model starts from the same base

installed.discard("qwen3.5:4b")  # base model missing → a clear message, nothing switched
db.set_setting("chat_model", "qwen3.5:4b")
assert libtrain.start_import(str(fake))["ok"]
for _ in range(100):
    if libtrain.status()["import"]["state"] != "running":
        break
    time.sleep(0.05)
assert libtrain.status()["import"]["state"] == "error" and "Download it" in libtrain.status()["import"]["message"]

# --- deleting a file removes what was learned from it ---
with db.connect() as conn:
    conn.execute("DELETE FROM sources WHERE id = ?", (a,))
    assert conn.execute("SELECT COUNT(*) FROM lib_qa WHERE source_id = ?", (a,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM lib_pages_done WHERE source_id = ?", (a,)).fetchone()[0] == 0

print("test_libtrain: all checks passed")
