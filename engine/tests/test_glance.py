"""
test_glance.py — checks for glance.py (v0.22 numbers behind the at-a-glance pictures).
Run with   python -I tests/test_glance.py   from the engine folder. Synthetic rows only.
WHAT: files are counted by kind and split into yours vs read from the web; replaced files are left out; categories with files are
      listed biggest first; the 30-day series has 30 days with files and web pages in the right buckets; health figures are
      percentages (linked, in topics, well covered) and an empty bank gives zeros, not errors.
WHEN: before a release that touches glance.py.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-glance-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import db, glance  # noqa: E402

assert db.init_db() == 23
g = glance.all_glance()                                   # empty bank
assert g["files"]["total"] == 0 and g["categories"] == [] and len(g["daily"]) == 30
assert g["health"]["linked_pct"] == 0 and g["health"]["well_covered_pct"] == 0 and g["health"]["topics_pct"] == 0
n = {"i": 0}


def add(ftype, cats, origin=None, days_old=0, status="extracted"):
    n["i"] += 1
    with db.connect() as conn:
        return conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories, origin, added_at) "
            "VALUES (?, ?, ?, ?, 1, ?, 't', ?, ?, datetime('now', ?))",
            (f"g{n['i']}", f"f{n['i']}", f"/x/{n['i']}", ftype, status, json.dumps(cats), origin, f"-{days_old} days")).lastrowid


a = add("pdf", ["Cloud"], days_old=1)
add("pdf", ["Cloud"], days_old=2)
add("image", ["SIEM & Detection"])
w = add("doc", ["Cloud"], origin="learned", days_old=1)
r = add("pdf", ["Cloud"])
with db.connect() as conn:
    conn.execute("UPDATE sources SET replaced_by = ? WHERE id = ?", (a, r))
    conn.execute("INSERT INTO source_vectors(source_id, method, vec) VALUES (?, 'terms', x'00')", (a,))
g = glance.all_glance()
assert g["files"]["total"] == 4 and g["files"]["web"] == 1 and g["files"]["mine"] == 3
assert {k["type"]: k["n"] for k in g["files"]["kinds"]} == {"pdf": 2, "image": 1, "doc": 1}
assert g["files"]["kinds"][0]["label"] == "PDF" and g["files"]["status"] == {"extracted": 4}
assert [c["name"] for c in g["categories"]] == ["Cloud", "SIEM & Detection"] and g["categories"][0]["files"] == 3
assert sum(d["files"] for d in g["daily"]) == 3 and sum(d["web"] for d in g["daily"]) == 1
assert g["health"]["linked_pct"] == 25 and g["health"]["subjects"] == 2 and 0 <= g["health"]["well_covered_pct"] <= 100
print("test_glance: all checks passed")
