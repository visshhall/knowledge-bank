"""
test_learner.py — checks for learner.py (v0.16 web learning) and websearch.parse_results.
Run with   python -I tests/test_learner.py   from the engine folder. No internet and no AI: a small test
website is served from this computer and the web search is replaced by a function returning its pages.
WHAT: off by default and nothing happens while off; topics from the owner and from unanswered questions
      (only when on, only real topics); a round reads pages one per search result, marks them origin
      'learned' with the topic, counts them in today's budget and stops at the daily budget; offline and
      "search found nothing" rounds are handled and several empty rounds pause the loop; a watch address is
      re-read and only changed content is added; the owner's own web read blocks a round; rounds respect the
      gap between them; "remove everything it learned" removes learned pages and leaves the owner's own;
      the search-result parser (DuckDuckGo lite layout) skips social/video sites and repeats from one site.
WHEN: before a release that touches learner.py, websearch.py or the learned-page marking in crawler.py.
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-learn-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import crawler, db, importer, learner, websearch  # noqa: E402

assert db.init_db() == 22
importer._ensure_worker = lambda: None
crawler.ALLOW_PRIVATE = True
crawler.MIN_DELAY = 0.0
learner.CRAWL_WAIT_SECONDS = 20

LONG = "This is readable text about Sentinel analytics rules and KQL joins for the learning test. " * 6
changed = {"yes": False}


def page(title, extra=""):
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{LONG}{extra}</p></main></body></html>".encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/robots.txt":
            body, ct = b"User-agent: *\nDisallow: /nope/\n", "text/plain"
        elif p.startswith("/nope/"):
            body, ct = page("blocked"), "text/html"
        elif p == "/w/":
            body, ct = page("Watched", " changed!" if changed["yes"] else ""), "text/html"
        else:
            body, ct = page(f"Page {p}"), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

searches = []
results = {"urls": []}
learner.search = lambda q, limit=5: (searches.append(q), results["urls"][:limit])[1]
online = {"yes": True}
learner.is_online = lambda: online["yes"]


def learned():
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sources WHERE origin = 'learned'")]


def due():
    learner._next_round = 0.0


# --- off by default --------------------------------------------------------------------------------------
assert learner.enabled() is False and learner.run_round() == "off"
learner.note_gap("how do I tune a sentinel analytics rule")            # off → not remembered
assert learner.status()["topics"] == []

# --- owner topic, one round --------------------------------------------------------------------------------
learner.set_enabled(True)
assert learner.add_topic("Sentinel analytics rules")["ok"] and learner.add_topic("sentinel analytics RULES")["ok"] is False
assert learner.add_topic("x")["ok"] is False
results["urls"] = [f"{BASE}/a1", f"{BASE}/a2", f"{BASE}/a3", f"{BASE}/a4", f"{BASE}/a5"]
due()
assert learner.run_round() == "topic"
L = learned()
assert len(L) == learner.PAGES_PER_TOPIC and all(s["learn_topic"] == "Sentinel analytics rules" for s in L), L
assert learner.pages_today() == 4 and searches == ["Sentinel analytics rules"]
st = learner.status()
assert st["topics"][0]["status"] == "done" and st["topics"][0]["pages_added"] == 4 and st["learned_pages"] == 4
assert learner.run_round() == "waiting"                               # the gap between rounds is respected

# --- gap questions (only real topics) -----------------------------------------------------------------------
learner.note_gap("hi")
learner.note_gap("how do I tune a sentinel analytics rule?")
topics = [t["topic"] for t in learner.status()["topics"]]
assert "how do I tune a sentinel analytics rule" in topics and "hi" not in topics
assert [t for t in learner.status()["topics"] if t["origin"] == "gap"]

# --- the owner's own web read blocks a round ---------------------------------------------------------------
learner.add_topic("owner topic two")
due()
orig = crawler.status
crawler.status = lambda: {"state": "running"}
assert learner.run_round() == "busy"
crawler.status = orig

# --- owner topics come before gaps; budget limits ------------------------------------------------------------
db.set_setting("learn_auto_gaps", False)   # v0.18: gap planning is tested in test_coverage.py, not here
db.set_setting("learn_daily", 5)
results["urls"] = [f"{BASE}/b1", f"{BASE}/b2", f"{BASE}/b3"]
due()
assert learner.run_round() == "topic" and searches[-1] == "owner topic two"
assert learner.pages_today() == 5, learner.pages_today()              # stopped at the budget of 5
due()
assert learner.run_round() == "budget"

# --- offline and empty-search rounds ---------------------------------------------------------------------------
db.set_setting("learn_daily", 300)
online["yes"] = False
due()
assert learner.run_round() == "offline"
online["yes"] = True
results["urls"] = []
for i in range(learner.PAUSE_AFTER_FAILS):
    learner.add_topic(f"nothing found topic {i}")
for i in range(learner.PAUSE_AFTER_FAILS):
    due()
    assert learner.run_round() == "topic"
assert "resting" in learner.status()["message"] and learner._next_round > time.time() + 3000
failed = [t for t in learner.status()["topics"] if t["status"] == "failed"]
assert len(failed) == learner.PAUSE_AFTER_FAILS

# --- watch address: read, then only changes ----------------------------------------------------------------------
with db.connect() as conn:
    conn.execute("UPDATE learn_topics SET status = 'done'")           # nothing pending → the watch is next
assert learner.add_watch(f"{BASE}/w/", "page", 5)["ok"] and learner.add_watch(f"{BASE}/w/", "page", 5)["ok"] is False
assert learner.add_watch("not a url")["ok"] is False
before = len(learned())
due()
assert learner.run_round() == "watch" and len(learned()) == before + 1
w = learner.status()["watch"][0]
assert w["pages_added"] == 1 and w["last_run"]
due()
assert learner.run_round() == "idle"                                  # read within the last day → nothing due
with db.connect() as conn:
    conn.execute("UPDATE learn_watch SET last_run = '2000-01-01 00:00:00'")
due()
assert learner.run_round() == "watch" and len(learned()) == before + 1  # unchanged page → nothing added
with db.connect() as conn:
    conn.execute("UPDATE learn_watch SET last_run = '2000-01-01 00:00:00'")
changed["yes"] = True
due()
assert learner.run_round() == "watch" and len(learned()) == before + 2   # changed content is added

# --- the owner's own files stay when everything learned is removed ---------------------------------------------------
r = crawler.start(f"{BASE}/mine", scope="page")
assert r["ok"]
while crawler.status()["state"] == "running":
    time.sleep(0.1)
with db.connect() as conn:
    mine = conn.execute("SELECT COUNT(*) FROM sources WHERE origin IS NULL").fetchone()[0]
assert mine >= 1
out = learner.remove_all_learned()
assert out["ok"] and learned() == []
with db.connect() as conn:
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE origin IS NULL").fetchone()[0] == mine
assert learner.learned_pages()["total"] == 0

# --- switching off, limits ----------------------------------------------------------------------------------------------
learner.set_limits(daily_pages=1000, round_gap_min=1)
assert learner.daily_budget() == 300 and learner.round_gap_minutes() == 5
learner.set_enabled(False)
assert learner.run_round() == "off" and learner.status()["on"] is False
assert learner.remove_topic(learner.status()["topics"][0]["id"])["ok"]

# --- search result parser ---------------------------------------------------------------------------------------------------
html = ('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D1&rut=x">yt</a>'
        '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fin.security%2Fpost-1&rut=x">1</a>'
        '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fin.security%2Fpost-2&rut=x">2 same site</a>'
        '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa%3Fb%3D1&rut=x">3</a>'
        '<a href="//duckduckgo.com/l/?uddg=ftp%3A%2F%2Fexample.net%2Ff&rut=x">ftp</a>'
        '<a href="//duckduckgo.com/y.js?ad=1">ad</a>')
assert websearch.parse_results(html, 5) == ["https://in.security/post-1", "https://example.org/a?b=1"]
assert websearch.parse_results(html, 1) == ["https://in.security/post-1"] and websearch.parse_results("", 5) == []
assert websearch.search("   ") == []
print("test_learner: all checks passed")
