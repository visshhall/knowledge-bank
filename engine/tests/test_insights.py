"""
test_insights.py — checks for insights.py (v0.20 data behind the Insights screen).
Run with   python -I tests/test_insights.py   from the engine folder. Synthetic rows only; nothing needs the AI or internet.
WHAT: the knowledge map has a node per category and links only between categories that share files; the heatmap puts files
      and citations in the right rolling week (oldest first); mistake trends count kinds per week, give the share of
      answers that went wrong and mark the week a lesson was added; the timeline lists learned pages, new categories,
      lessons, gap topics and blocked sites newest first, and the 30-day series has 30 entries; weeks are clamped.
WHEN: before a release that touches insights.py or the tables it reads.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-ins-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import db, insights, taxonomy  # noqa: E402

assert db.init_db() == 22
n = {"i": 0}


def src(title, cats, days_old=0, origin=None, topic=None, passages=2):
    n["i"] += 1
    with db.connect() as conn:
        sid = conn.execute(
            "INSERT INTO sources(sha256, file_name, original_path, file_type, size_bytes, status, title, categories, origin, learn_topic, added_at) "
            "VALUES (?, ?, ?, 'doc', 1, 'extracted', ?, ?, ?, ?, datetime('now', ?))",
            (f"s{n['i']}", title, f"/x/{n['i']}", title, json.dumps(cats), origin, topic, f"-{days_old} days")).lastrowid
        page = conn.execute("INSERT INTO pages(source_id, page_number, text) VALUES (?, 1, 't')", (sid,)).lastrowid
        for k in range(passages):
            conn.execute("INSERT INTO passages(source_id, page_id, page_number, ordinal, text, content_hash) VALUES (?, ?, 1, ?, 't', ?)",
                         (sid, page, k, f"p{sid}-{k}"))
    return sid


def message(sources=None, days_old=0, role="assistant"):
    with db.connect() as conn:
        chat = conn.execute("SELECT id FROM chats LIMIT 1").fetchone()
        chat = chat["id"] if chat else conn.execute("INSERT INTO chats(title, mode) VALUES ('t', 'library')").lastrowid
        conn.execute("INSERT INTO chat_messages(chat_id, role, content, sources_json, created_at) VALUES (?, ?, 'a', ?, datetime('now', ?))",
                     (chat, role, json.dumps({str(i): {"source_id": s} for i, s in enumerate(sources or [], 1)}) if sources else None, f"-{days_old} days"))


a = src("SIEM one", ["SIEM & Detection", "Cloud"], days_old=2)
b = src("SIEM two", ["SIEM & Detection"], days_old=10)
c = src("Cloud only", ["Cloud"], days_old=100)                     # older than 12 weeks
l = src("Learned page", ["Cloud"], days_old=1, origin="learned", topic="kubernetes security")
l2 = src("Learned page 2", ["Cloud"], days_old=1, origin="learned", topic="kubernetes security")

# --- map -----------------------------------------------------------------------------------------------------------------
m = insights.knowledge_map()
ids = {x["id"]: x for x in m["nodes"]}
assert set(ids) == set(taxonomy.all_top()) and ids["SIEM & Detection"]["files"] == 2 and ids["Cloud"]["files"] == 4
assert m["links"] == [{"a": "Cloud", "b": "SIEM & Detection", "weight": 1}]
assert ids["Cloud"]["learned"] == 2 and 0 <= ids["Cloud"]["score"] <= 100

# --- heatmap: oldest week first, rolling weeks -------------------------------------------------------------------------------
message([a], days_old=3)
message([a, b], days_old=9)
message(None, days_old=0)
h = insights.heatmap(12, insights._now())
row = {r["category"]: r for r in h["rows"]}
assert len(row["SIEM & Detection"]["added"]) == 12
assert row["SIEM & Detection"]["added"][-1] == 1 and row["SIEM & Detection"]["added"][-2] == 1       # a: this week, b: last week
assert row["SIEM & Detection"]["used"][-1] == 1 and row["SIEM & Detection"]["used"][-2] == 2          # cited 3 and 9 days ago
assert sum(row["Cloud"]["added"]) == 3                                                               # c (100 days old) is outside the window
assert h["rows"][0]["total"] >= h["rows"][-1]["total"]

# --- mistakes ----------------------------------------------------------------------------------------------------------------------------
with db.connect() as conn:
    for kind, days in (("down", 1), ("down", 2), ("regen", 8), ("correct", 15)):
        conn.execute("INSERT INTO mistake_log(kind, created_at) VALUES (?, datetime('now', ?))", (kind, f"-{days} days"))
    conn.execute("INSERT INTO lesson_rules(text, created_at) VALUES ('Keep answers short.', datetime('now', '-8 days'))")
mm = insights.mistakes(12, insights._now())
assert mm["kinds"]["down"][-1] == 2 and mm["kinds"]["regen"][-2] == 1 and mm["kinds"]["correct"][-3] == 1
assert mm["total"][-1] == 2 and mm["answers"][-1] == 2 and mm["rate"][-1] == 1.0 and mm["rate"][0] is None
assert mm["lessons"] == [{"week": 10, "text": "Keep answers short.", "status": "active", "verdict": "new"}]

# --- timeline --------------------------------------------------------------------------------------------------------------------------------
with db.connect() as conn:
    conn.execute("INSERT INTO taxonomy(name, terms_json, origin) VALUES ('Sanskrit Grammar', '[\"sanskrit\"]', 'auto')")
    conn.execute("INSERT INTO taxonomy(name, parent, terms_json, origin) VALUES ('KQL', 'SIEM & Detection', '[\"kql\"]', 'auto')")
    conn.execute("INSERT INTO learn_topics(topic, origin) VALUES ('edr tuning guide', 'coverage')")
    conn.execute("INSERT INTO learn_topics(topic, origin) VALUES ('my own topic', 'owner')")
    conn.execute("INSERT INTO site_stats(host, thin, blocked) VALUES ('junk.example', 4, 1)")
t = insights.timeline(insights._now())
texts = [e["text"] for e in t["events"]]
assert any("Read 2 web pages about “kubernetes security”" in x for x in texts)
assert any("Added category “Sanskrit Grammar”" in x for x in texts) and any("sub-category “KQL” under SIEM" in x for x in texts)
assert any("Keep answers short" in x for x in texts) and any("edr tuning guide" in x and "gap" in x for x in texts)
assert not any("my own topic" in x for x in texts) and any("junk.example" in x for x in texts)
assert [e["at"] for e in t["events"]] == sorted([e["at"] for e in t["events"]], reverse=True)
assert len(t["days"]) == 30 and t["days"][-1]["date"] == insights._now().strftime("%Y-%m-%d")
assert sum(d["learned"] for d in t["days"]) == 2 and sum(d["mistakes"] for d in t["days"]) == 4

# --- all ---------------------------------------------------------------------------------------------------------------------------------------------
al = insights.all_insights(999)
assert al["weeks"] == insights.MAX_WEEKS and set(al) == {"weeks", "map", "heatmap", "mistakes", "timeline"}
assert insights.all_insights(1)["weeks"] == 4
print("test_insights: all checks passed")
