"""
test_brain.py — checks for brain.py (v0.21 live learning view: a dot per file, related to what is already there).
Run with   python -I tests/test_brain.py   from the engine folder. A fake embedding model stands in for Ollama: every text
shares one strong common direction (like the real model) plus a direction for its subject, so the test also proves the
"remove the shared direction" step works.
WHAT: without the model, files get key-word vectors and still link by subject; with the model they are upgraded to meaning
      vectors without being announced as new again; a new file links to its subject's files and not to others, and its
      event reads in plain words; passages that are already embedded are reused (no model call); the graph marks dots newer
      than a cursor, respects the cap, hides replaced files; related() lists neighbours best first; deleting a file removes
      its dot, links and events; only files with text are processed.
WHEN: before a release that touches brain.py or the tables it writes.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-brain-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import brain, db  # noqa: E402

assert db.init_db() == 22
import numpy as np  # noqa: E402

AXES = {"kql": 1, "sandhi": 2, "resin": 3}
calls = {"embed": 0, "available": False}


def fake_embed(texts):
    """Strong shared direction (axis 0) + a subject axis + a little text-dependent noise."""
    calls["embed"] += len(texts)
    out = []
    for t in texts:
        v = np.zeros(16, dtype=np.float32)
        v[0] = 5.0
        for word, axis in AXES.items():
            if word in t.lower():
                v[axis] = 2.0
        v[4 + (sum(map(ord, t)) % 8)] = 0.3
        out.append(v.tolist())
    return out


brain._embed_texts = fake_embed
brain.embedding_available = lambda: calls["available"]
n = {"i": 0}


def add(title, text, passages=3):
    n["i"] += 1
    with db.connect() as conn:
        sid = conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories) "
            "VALUES (?, ?, ?, 'doc', 1, 'extracted', ?, '[\"Cloud\"]')", (f"b{n['i']}", title, f"/x/{n['i']}", title)).lastrowid
        page = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, 1, ?)", (sid, text)).lastrowid
        for k in range(passages):
            conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) VALUES (?, ?, 1, ?, ?, ?)",
                         (sid, page, k, f"{text} part {k}", f"h{sid}-{k}"))
    return sid


def sub(a):
    with db.connect() as conn:
        return {r["source_id"]: r["method"] for r in conn.execute("SELECT source_id, method FROM source_vectors")}, \
            conn.execute("SELECT COUNT(*) FROM brain_events").fetchone()[0], \
            [(r["a"], r["b"]) for r in conn.execute("SELECT a, b FROM source_links")]


kql = [add(f"KQL join cheatsheet {i}", f"kql join summarize sentinel table query {i}") for i in range(3)]
sk = [add(f"Sanskrit sandhi rules {i}", f"sandhi vowel visarga rules {i}") for i in range(3)]
empty = add("Empty file", "x", passages=0)

# --- no model: key-word vectors, links by subject ----------------------------------------------------------------------------------
assert brain.pending_count() == 7
r = brain.process_pending(20)
assert r["ok"] and r["done"] == 6 and calls["embed"] == 0
methods, events, links = sub(0)
assert set(methods.values()) == {"terms"} and events == 6 and empty not in methods
assert all((a in kql and b in kql) or (a in sk and b in sk) for a, b in links) and links, links
assert brain.pending_count() == 1                                   # the file with no text keeps waiting

# --- the model becomes available: upgrade, not announced again ------------------------------------------------------------------------
calls["available"] = True
brain.process_pending(20)
methods, events, links = sub(0)
assert set(methods[i] for i in kql + sk) == {"embed"} and events == 6 and calls["embed"] > 0
assert links and all((a in kql and b in kql) or (a in sk and b in sk) for a, b in links), links    # shared direction removed

# --- a new file arrives and links to its subject; its event reads in plain words --------------------------------------------------------
cut = brain.graph()["now"]
import time as _t; _t.sleep(1.1)
new = add("KQL parse and extend notes", "kql parse extend project operators sentinel")
d = brain.process_source(new, True)
assert d["method"] == "embed" and d["links"] and all(l["id"] in kql for l in d["links"]), d
g = brain.graph(since=cut)
assert [x["id"] for x in g["nodes"] if x["new"]] == [new] and g["total"] == 7
ev = g["events"][0]
assert ev["source_id"] == new and "KQL parse and extend notes" in ev["text"] and "KQL join cheatsheet" in ev["text"] and "relates" in ev["text"]
assert any(l["a"] == new or l["b"] == new for l in g["links"]) and g["status"]["methods"] == {"embed": 7}

# --- a file with no relatives starts a new area; already-embedded passages are reused -----------------------------------------------------
before = calls["embed"]
odd = add("Resin curing times", "resin curing uv wash times")
brain.process_source(odd, True)
d_odd = brain.process_source(add("Resin wash notes", "resin wash isopropyl"), True)
assert calls["embed"] > before
solo = brain.graph()["events"]
assert any("starts a new area" in e["text"] or "Resin" in e["text"] for e in solo)
again = calls["embed"]
brain.process_source(odd, True)                                     # vector re-made from stored passage vectors: no model call
assert calls["embed"] == again

# --- related(), cap, replaced files, deletion --------------------------------------------------------------------------------------------------
rel = brain.related(new)
assert rel["ok"] and rel["related"] and [x["sim"] for x in rel["related"]] == sorted([x["sim"] for x in rel["related"]], reverse=True)
assert brain.related(99999)["ok"] is False
assert len(brain.graph(limit=20)["nodes"]) <= 20
with db.connect() as conn:
    conn.execute("UPDATE sources SET replaced_by = ? WHERE id = ?", (new, kql[0]))
assert kql[0] not in [x["id"] for x in brain.graph()["nodes"]]
with db.connect() as conn:
    conn.execute("DELETE FROM sources WHERE id = ?", (sk[0],))
    assert conn.execute("SELECT COUNT(*) FROM source_vectors WHERE source_id = ?", (sk[0],)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM source_links WHERE a = ? OR b = ?", (sk[0], sk[0])).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM brain_events WHERE source_id = ?", (sk[0],)).fetchone()[0] == 0
print("test_brain: all checks passed")
