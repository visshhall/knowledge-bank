"""
test_coverage.py — checks for coverage.py (v0.18: gaps per category, page usefulness, junk-site learning).
Run with   python -I tests/test_coverage.py   from the engine folder. No internet and no AI: sources and passages
are written straight into a temporary bank and the AI's topic phrases fall back to the plain ones.
WHAT: the coverage score rises with files, passages and freshness; a category answers keep citing is flagged
      sooner; plan_topics adds topics (origin 'coverage') for the weakest categories only, once per cool-down;
      thin learned pages are removed by maintain(); a site that keeps giving thin/removed pages and is never cited
      is blocked, a cited site is not; the owner's block/allow wins; rank_urls drops blocked sites and puts good
      ones first; removing a learned page by hand counts against its site, a bulk reset does not;
      prune_unused removes only old, never-cited learned pages; the model's phrases are parsed safely.
WHEN: before a release that touches coverage.py, learner.py's maintain/plan hooks or importer.remove_sources.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-cov-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import coverage, db, importer, learner, ollama_client  # noqa: E402

assert db.init_db() == 22
ollama_client.is_running = lambda: False          # no AI: topic phrases use the plain fallback
n = {"i": 0}


def add_source(title, cats, passages=5, origin=None, url=None, status="extracted", days_old=0):
    """A source with N passages, straight into the bank."""
    n["i"] += 1
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories, "
            "origin, url, added_at) VALUES (?, ?, ?, 'doc', 1, ?, ?, ?, ?, ?, datetime('now', ?))",
            (f"h{n['i']}", title, f"/x/{n['i']}", status, title, json.dumps(cats), origin, url, f"-{days_old} days"))
        sid = cur.lastrowid
        page = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, 1, 'text')", (sid,)).lastrowid
        for k in range(passages):
            conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) "
                         "VALUES (?, ?, 1, ?, 'text', ?)", (sid, page, k, f"c{sid}-{k}"))
    return sid


def cite(source_ids):
    """An assistant message whose answer cited these sources."""
    with db.connect() as conn:
        chat = conn.execute("INSERT INTO chats(title, mode) VALUES ('t', 'library')").lastrowid
        conn.execute("INSERT INTO chat_messages(chat_id, role, content, sources_json) VALUES (?, 'assistant', 'a', ?)",
                     (chat, json.dumps({str(i): {"source_id": s} for i, s in enumerate(source_ids, 1)})))


def _has(table):
    with db.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone())


def cat(name):
    return next(c for c in coverage.categories() if c["category"] == name)


# --- score ------------------------------------------------------------------------------------------------------
assert coverage.score_category(0, 0, None) == 0
assert coverage.score_category(8, 300, 0) == 100
assert coverage.score_category(4, 150, 0) == 25 + 15 + 20
assert coverage.score_category(8, 300, 400) == 80                       # stale: loses the freshness marks

# --- categories, weak flags, demand ---------------------------------------------------------------------------------
assert all(c["weak"] for c in coverage.categories())                    # an empty bank has gaps everywhere
for i in range(8):
    add_source(f"SIEM doc {i}", ["SIEM & Detection"], passages=40)
siem = cat("SIEM & Detection")
assert siem["sources"] == 8 and siem["passages"] == 320 and siem["score"] == 100 and not siem["weak"]
sid_ep = add_source("EDR note", ["Endpoint"], passages=10)
assert cat("Endpoint")["weak"] and cat("Endpoint")["score"] < coverage.WEAK_BELOW
add_source("Cloud a", ["Cloud"], passages=300)
add_source("Cloud b", ["Cloud"], passages=300)
add_source("Cloud c", ["Cloud"], passages=300)
add_source("Cloud d", ["Cloud"], passages=300)
add_source("Cloud e", ["Cloud"], passages=300)
mid = cat("Cloud")
assert mid["score"] >= coverage.WEAK_BELOW and not mid["weak"]
with db.connect() as conn:
    cloud_ids = [r["id"] for r in conn.execute("SELECT id FROM sources WHERE title LIKE 'Cloud %'")]
for _ in range(4):
    cite(cloud_ids[:1])                                                  # heavily used, not fully covered → gap
assert cat("Cloud")["cited"] == 4 and cat("Cloud")["weak"] is (mid["score"] < coverage.DEMAND_WEAK_BELOW)

# --- plan_topics ------------------------------------------------------------------------------------------------------
learner.set_enabled(True)
r = coverage.plan_topics()
assert r["ok"] and r["added"] >= 2 and len(r["categories"]) <= coverage.MAX_PLAN_PER_RUN and "SIEM & Detection" not in r["categories"]
topics = learner.status()["topics"]
assert topics and all(t["origin"] == "coverage" for t in topics)
again = coverage.plan_topics()                                          # cool-down: other weak categories, never the same
assert not set(again["categories"]) & set(r["categories"])
forced = coverage.plan_topics(force=True)
assert set(forced["categories"]) & set(r["categories"]) or forced["added"] == 0   # the button ignores the cool-down

# --- parse the model's phrases --------------------------------------------------------------------------------------------
assert coverage.parse_queries('["kql join examples for sentinel", "sentinel analytics rule tuning guide"]') == [
    "kql join examples for sentinel", "sentinel analytics rule tuning guide"]
assert coverage.parse_queries("- siem\n- detection engineering with sigma rules") == ["detection engineering with sigma rules"]
assert coverage.parse_queries("") == [] and coverage.parse_queries("[1, 2]") == []

# --- thin pages are pruned; junk sites blocked; cited sites kept ----------------------------------------------------------
for i in range(3):
    add_source(f"junk {i}", ["Cloud"], passages=1, origin="learned", url=f"https://junk.example/p{i}")
add_source("failed junk", [], passages=0, origin="learned", url=f"https://junk.example/p9", status="failed")
good = [add_source(f"good {i}", ["Cloud"], passages=12, origin="learned", url=f"https://good.example/p{i}") for i in range(2)]
cite([good[0]])
m = coverage.maintain()
assert m["pruned"] == 4 and m["blocked"] == ["junk.example"], m
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE url LIKE 'https://junk.example%'").fetchone()[0] == 0
    gs = conn.execute("SELECT * FROM site_stats WHERE host = 'good.example'").fetchone()
assert gs["pages"] == 2 and gs["useful"] == 1 and gs["blocked"] == 0 and gs["score"] > 0
st = coverage.status()
assert st["learned"]["total"] == 2 and st["learned"]["useful"] == 1 and st["learned"]["unused"] == 1
assert [s["host"] for s in st["sites"]][0] == "junk.example"            # blocked sites are listed first

# --- rank_urls --------------------------------------------------------------------------------------------------------------
keep, skipped = coverage.rank_urls(["https://new.example/a", "https://junk.example/z", "https://good.example/q"])
assert keep == ["https://good.example/q", "https://new.example/a"] and skipped == ["junk.example"]

# --- the owner's word wins ----------------------------------------------------------------------------------------------------
assert coverage.set_site("junk.example", "allow")["ok"]
assert coverage.rank_urls(["https://junk.example/z"])[1] == []
assert coverage.set_site("good.example", "block")["ok"]
assert coverage.rank_urls(["https://good.example/q"])[1] == ["good.example"]
assert coverage.set_site("good.example", "auto")["ok"] and coverage.rank_urls(["https://good.example/q"])[1] == []
assert coverage.set_site("", "block")["ok"] is False and coverage.set_site("x.example", "nope")["ok"] is False

# --- removal feedback: by hand counts, a bulk reset does not -----------------------------------------------------------------
v = add_source("hand removed", [], passages=9, origin="learned", url="https://fb.example/a")
importer.remove_sources([v])
with db.connect() as conn:
    assert conn.execute("SELECT removed FROM site_stats WHERE host = 'fb.example'").fetchone()["removed"] == 1
w = add_source("bulk removed", [], passages=9, origin="learned", url="https://bulk.example/a")
importer.remove_sources([w], feedback=False)
with db.connect() as conn:
    assert conn.execute("SELECT 1 FROM site_stats WHERE host = 'bulk.example'").fetchone() is None

# --- prune_unused: old and never cited only ----------------------------------------------------------------------------------------
old = add_source("old unused", [], passages=9, origin="learned", url="https://old.example/a", days_old=60)
fresh = add_source("fresh unused", [], passages=9, origin="learned", url="https://fresh.example/a", days_old=1)
res = coverage.prune_unused(45)
assert res.get("removed") == 1
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE id = ?", (old,)).fetchone()[0] == 0 or \
        conn.execute("SELECT status FROM sources WHERE id = ?", (old,)).fetchone()["status"] != "extracted"
    assert conn.execute("SELECT status FROM sources WHERE id = ?", (fresh,)).fetchone()["status"] == "extracted"
assert coverage.prune_unused(45)["removed"] == 0

# --- the switch -------------------------------------------------------------------------------------------------------------------------
assert coverage.auto_enabled() is True and coverage.set_auto(False)["on"] is False and coverage.auto_enabled() is False
print("test_coverage: all checks passed")
