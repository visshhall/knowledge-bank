"""
test_taxonomy.py — checks for taxonomy.py (v0.19: categories and sub-categories that grow from the data).
Run with   python -I tests/test_taxonomy.py   from the engine folder. No internet; the AI is replaced by a fake reply.
WHAT: built-in categories still win; files that fit nothing are grouped into NEW categories (plain mode: 3+ files share a
      distinctive word; AI mode: 2+ files, the AI's name folded into an existing category when it is the same thing);
      single files stay unplaced; new files are tagged at import with grown categories; a big category is split into
      sub-categories and its files tagged "Parent / Child"; near-duplicate grown categories are merged and empty ones
      dropped; the owner can rename, merge and delete grown categories but not built-in ones; coverage and the
      status report include grown categories.
WHEN: before a release that touches taxonomy.py, importer._name_and_tag or coverage.categories.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-tax-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import coverage, db, taxonomy, titles  # noqa: E402

assert db.init_db() == 22
taxonomy._ask = lambda prompt: None               # no AI unless a test sets one
n = {"i": 0}


def add(title, text, cats=None):
    n["i"] += 1
    with db.connect() as conn:
        sid = conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories) "
            "VALUES (?, ?, ?, 'doc', 1, 'extracted', ?, ?)",
            (f"t{n['i']}", title, f"/x/{n['i']}", title, json.dumps(cats if cats is not None else []))).lastrowid
        page = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, 1, ?)", (sid, text)).lastrowid
        conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) VALUES (?, ?, 1, 0, ?, ?)",
                     (sid, page, text, f"c{sid}"))
    return sid


def tags(sid):
    with db.connect() as conn:
        r = conn.execute("SELECT categories, subcats FROM sources WHERE id = ?", (sid,)).fetchone()
    return json.loads(r["categories"] or "[]"), json.loads(r["subcats"] or "[]")


# --- built-in list is untouched ---------------------------------------------------------------------------------------
siem_text = "sentinel kql analytics rule siem alert playbook detection rule " * 3
assert taxonomy.classify(siem_text)[0] == titles.categorise(siem_text) == ["SIEM & Detection"]
assert taxonomy.all_top() == list(titles.CATEGORIES)

# --- plain mode: groups of 3+ files with a shared distinctive word -------------------------------------------------------------
sk = [add(f"Sanskrit grammar notes {i}", f"Sanskrit grammar sandhi rules lesson {i}") for i in range(4)]
pr = [add(f"Resin printing guide {i}", f"Resin printing layer curing washing guide {i}") for i in range(3)]
lone = add("Mango pickle recipe", "A recipe for mango pickle with oil and spices")
r = taxonomy.grow()
assert r["ok"] and len(r["new"]) == 2 and not r["ai"], r
names = taxonomy.all_top()[len(titles.CATEGORIES):]
assert len(names) == 2 and any("Sanskrit" in x for x in names) and any("Resin" in x for x in names), names
sk_cat = next(x for x in names if "Sanskrit" in x)
assert all(tags(i)[0] == [sk_cat] for i in sk) and tags(lone)[0] == []        # the loner stays unplaced
assert "Added" in r["message"] and taxonomy.status()["unplaced"] == 1
assert taxonomy.grow()["new"] == []                                           # nothing more to do

# --- new files are tagged at import with grown categories ----------------------------------------------------------------------
cats, subs = taxonomy.classify("Sanskrit grammar and sandhi rules for beginners", "Intro to Sanskrit")
assert cats == [sk_cat], cats

# --- AI mode: names are validated, existing categories are extended not duplicated ------------------------------------------------
a = [add(f"Odoo theme notes {i}", f"odoo website theme snippet qweb xml {i}") for i in range(2)]
b = [add(f"Resin cure notes {i}", f"resin curing uv wash notes {i}") for i in range(2)]
def fake_ai(prompt):
    """Answers like a model that read the numbered list: finds the file numbers by title words."""
    import re as _re
    nums = {}
    for m in _re.finditer(r"^(\d+)\. (.+)$", prompt, _re.M):
        key = "odoo" if "Odoo" in m.group(2) else "resin" if "Resin" in m.group(2) else None
        if key:
            nums.setdefault(key, []).append(int(m.group(1)))
    return json.dumps([
        {"name": "Odoo Website", "terms": ["odoo", "website", "theme", "qweb", "snippet"], "files": nums["odoo"] + [99]},
        {"name": "Resin Printing", "terms": ["resin", "curing", "uv", "wash"], "files": nums["resin"]},   # same as an existing category
        {"name": "x", "terms": ["a"], "files": nums["odoo"]},                                          # junk → ignored
    ])


taxonomy._ask = fake_ai
r = taxonomy.grow()
assert r["ai"] and r["new"] == ["Odoo Website"], r
assert all(tags(i)[0] == ["Odoo Website"] for i in a)
resin = next(x for x in names if "Resin" in x)
assert all(tags(i)[0] == [resin] for i in b)                                  # folded into the existing one
assert taxonomy.all_top().count("Odoo Website") == 1
taxonomy._ask = lambda prompt: None

# --- sub-categories for a big category --------------------------------------------------------------------------------------------------
big = [add(f"Kubernetes pods deployment {i}", f"kubernetes pods cluster manifests deployment {i}", ["Cloud"]) for i in range(7)]
big += [add(f"Serverless functions lambda {i}", f"serverless functions lambda triggers cold start {i}", ["Cloud"]) for i in range(7)]
r = taxonomy.grow()
assert len(r["subs"]) >= 2 and all(s.startswith("Cloud / ") for s in r["subs"]), r
assert all(tags(i)[1] and tags(i)[1][0].startswith("Cloud / ") for i in big), [tags(i) for i in big]
assert tags(big[0])[1] != tags(big[-1])[1]                                    # the two clusters got different sub-categories
st = taxonomy.status()
cloud = next(c for c in st["categories"] if c["name"] == "Cloud")
assert len(cloud["subs"]) >= 2 and sum(s["files"] for s in cloud["subs"]) == 14
assert taxonomy.grow()["subs"] == []                                          # once

# --- coverage includes grown categories ----------------------------------------------------------------------------------------------------
assert any(c["category"] == sk_cat and c["sources"] == 4 for c in coverage.categories())

# --- owner controls -------------------------------------------------------------------------------------------------------------------------
assert taxonomy.rename("Cloud", "Cloudy")["ok"] is False and taxonomy.merge("Cloud", "Network")["ok"] is False
assert taxonomy.delete("Cloud")["ok"] is False
assert taxonomy.rename(sk_cat, "Sanskrit Language")["ok"] and all(tags(i)[0] == ["Sanskrit Language"] for i in sk)
assert taxonomy.rename("Sanskrit Language", "Cloud")["ok"] is False
assert taxonomy.merge("Odoo Website", "Sanskrit Language")["ok"]
assert all(tags(i)[0] == ["Sanskrit Language"] for i in a) and "Odoo Website" not in taxonomy.all_top()
assert taxonomy.delete(resin)["ok"] and all(tags(i)[0] == [] for i in pr)

# --- housekeeping: duplicates merged, empty categories dropped -------------------------------------------------------------------------------
with db.connect() as conn:
    conn.execute("INSERT INTO taxonomy(name, terms_json) VALUES ('Sanskrit Language Notes', '[\"sanskrit\"]')")
    conn.execute("INSERT INTO taxonomy(name, terms_json) VALUES ('Empty Thing', '[\"zzzz\"]')")
s = {"new": [], "subs": [], "placed": 0, "merged": [], "dropped": [], "ai": False}
taxonomy._housekeeping(s)
assert s["merged"] and "Empty Thing" in s["dropped"] and "Empty Thing" not in taxonomy.all_top(), s

# --- the switch ------------------------------------------------------------------------------------------------------------------------------------
assert taxonomy.auto_enabled() and taxonomy.set_auto(False)["on"] is False and not taxonomy.auto_enabled()
print("test_taxonomy: all checks passed")
