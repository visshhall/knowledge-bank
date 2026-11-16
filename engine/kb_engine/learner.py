"""
learner.py — v0.16 the app learns from the web by itself (the owner chose "fully automatic, add immediately").

WHAT:  A background loop (started with the engine) that, while the switch in Learning is ON, repeatedly:
         1. takes the next TOPIC (typed by the owner, or noticed from a question "My files" could not answer),
         2. searches the web for it (websearch.py), reads the best few pages with the normal crawler
            (crawler.py: robots.txt, polite delay, same-site, never local addresses) and adds them straight
            to the library, marked as "learned" so they can be listed and removed in one click, and
         3. re-reads the WATCH addresses the owner listed, about once a day; the library's duplicate check
            means only content that changed is added.
       Everything learned goes through the normal import, so it is searchable and cited like any file.
WHY:   The owner asked for the app to crawl the web to learn things on its own. A fully automatic crawler
       can fill a library with junk, so it runs inside hard limits that are not settings the loop can skip:
         - OFF until the owner turns it on in Learning (an app should not start reading the internet silently);
         - a DAILY PAGE BUDGET (default 60 pages, owner can change 5–300) that no cycle may exceed;
         - at most PAGES_PER_TOPIC pages per topic, one topic per round, ROUND_GAP_MIN minutes between rounds;
         - only when the laptop is online and no web read of the owner's is running; skipped quietly otherwise;
         - nothing from social/video/shopping sites (websearch.SKIP_SITES);
         - a pause of PAUSE_AFTER_FAILS failed rounds in a row (the search page refusing, offline…), retried later;
         - "Remove everything it learned" deletes all learned pages (not the files he added) in one click.
WHEN:  start() is called once by the engine at startup (server.py lifespan). note_gap() is called by chat.py
       whenever "My files" finds no passages for a question.
CONNECTED TO: db.py (tables learn_topics, learn_watch, settings; sources.origin), websearch.py (finding pages),
       crawler.py (reading pages; start(..., origin="learned")), importer.py (remove_sources),
       chat.py (note_gap), server.py (/learn/*), Learning.jsx (the screen).
"""
from __future__ import annotations

import datetime as _dt
import threading
import time

from . import coverage, crawler, db, websearch

PAGES_PER_TOPIC = 4        # pages read per topic (one per site, from the search results)
WATCH_REREAD_HOURS = 24    # how often a watch address is read again
ROUND_GAP_MIN = 20         # minutes between rounds (settable, never below 5)
DAILY_DEFAULT = 60         # pages per day
DAILY_MIN, DAILY_MAX = 5, 300
MAX_TOPICS = 300           # stored topics (owner + gaps); oldest finished ones are dropped past this
PAUSE_AFTER_FAILS = 4      # rounds in a row that found nothing before pausing 3 hours
TICK_SECONDS = 30          # how often the loop wakes to see whether anything is due
CRAWL_WAIT_SECONDS = 180   # longest wait for one page read

_lock = threading.Lock()
_wake = threading.Event()
_thread: threading.Thread | None = None
_state: dict = {"state": "off", "message": "Web learning is off.", "recent": []}
_next_round = 0.0
_fails = 0

# Replaceable in tests.
search = websearch.search
is_online = websearch.online


# ---------------------------------------------------------------------------
# Settings and counters
# ---------------------------------------------------------------------------

def enabled() -> bool:
    return bool(db.get_setting("learn_on", False))


def _today() -> str:
    return _dt.date.today().isoformat()


def pages_today() -> int:
    """Pages added by learning today (the counter resets by itself when the date changes)."""
    rec = db.get_setting("learn_today", {}) or {}
    return int(rec.get("n", 0)) if rec.get("day") == _today() else 0


def _add_today(n: int) -> None:
    db.set_setting("learn_today", {"day": _today(), "n": pages_today() + n})


def daily_budget() -> int:
    return max(DAILY_MIN, min(DAILY_MAX, int(db.get_setting("learn_daily", DAILY_DEFAULT) or DAILY_DEFAULT)))


def round_gap_minutes() -> int:
    return max(5, min(240, int(db.get_setting("learn_gap_min", ROUND_GAP_MIN) or ROUND_GAP_MIN)))


def _say(state: str, message: str) -> None:
    with _lock:
        _state.update(state=state, message=message)


def _note(topic: str, url: str, result: str) -> None:
    with _lock:
        recent = _state.setdefault("recent", [])
        recent.append({"at": time.strftime("%H:%M"), "topic": topic, "url": url, "result": result})
        del recent[:-10]


# ---------------------------------------------------------------------------
# Topics and watch addresses
# ---------------------------------------------------------------------------

def _clean_topic(text: str) -> str:
    return " ".join((text or "").split())[:140]


def add_topic(topic: str, origin: str = "owner") -> dict:
    topic = _clean_topic(topic)
    if len(topic) < 3:
        return {"ok": False, "message": "Write what to learn about (at least a few letters)."}
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM learn_topics WHERE lower(topic) = lower(?)", (topic,)).fetchone():
            return {"ok": False, "message": "That topic is already on the list."}
        conn.execute("INSERT INTO learn_topics(topic, origin) VALUES (?, ?)", (topic, origin))
        n = conn.execute("SELECT COUNT(*) FROM learn_topics").fetchone()[0]
        if n > MAX_TOPICS:  # drop the oldest finished ones
            conn.execute("DELETE FROM learn_topics WHERE id IN (SELECT id FROM learn_topics WHERE status != 'pending' "
                         "ORDER BY id LIMIT ?)", (n - MAX_TOPICS,))
    _wake.set()
    return {"ok": True}


def note_gap(question: str) -> None:
    """
    chat.py: "My files" found nothing for this question. Remember it as something to learn about — only
    when web learning is on, and only questions that look like real topics (not greetings or one word).
    """
    try:
        if not enabled():
            return
        q = _clean_topic(question)
        if len(q.split()) < 3 or q.endswith("?") and len(q) < 12:
            return
        add_topic(q.rstrip("?"), origin="gap")
    except Exception:  # never let learning get in the way of an answer
        pass


def remove_topic(topic_id: int) -> dict:
    with db.connect() as conn:
        n = conn.execute("DELETE FROM learn_topics WHERE id = ?", (topic_id,)).rowcount
    return {"ok": bool(n)}


def add_watch(url: str, scope: str = "section", max_pages: int = 30) -> dict:
    clean = crawler.normalize_url(url)
    if not clean:
        return {"ok": False, "message": "That doesn't look like a web address."}
    if scope not in crawler.SCOPES:
        scope = "section"
    max_pages = max(1, min(int(max_pages or 30), 100))
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM learn_watch WHERE url = ?", (clean,)).fetchone():
            return {"ok": False, "message": "That address is already being watched."}
        conn.execute("INSERT INTO learn_watch(url, scope, max_pages) VALUES (?, ?, ?)", (clean, scope, max_pages))
    _wake.set()
    return {"ok": True}


def remove_watch(watch_id: int) -> dict:
    with db.connect() as conn:
        n = conn.execute("DELETE FROM learn_watch WHERE id = ?", (watch_id,)).rowcount
    return {"ok": bool(n)}


# ---------------------------------------------------------------------------
# Status and the learned pages
# ---------------------------------------------------------------------------

def status() -> dict:
    with db.connect() as conn:
        topics = [dict(r) for r in conn.execute(
            "SELECT id, topic, origin, status, pages_added, last_run, note FROM learn_topics "
            "ORDER BY (status = 'pending') DESC, id DESC LIMIT 100")]
        watch = [dict(r) for r in conn.execute(
            "SELECT id, url, scope, max_pages, pages_added, last_run FROM learn_watch ORDER BY id DESC")]
        learned = conn.execute("SELECT COUNT(*) FROM sources WHERE origin = 'learned'").fetchone()[0]
    with _lock:
        st = dict(_state)
        st["recent"] = list(st.get("recent", []))
    return {"on": enabled(), "state": st["state"], "message": st["message"], "recent": st["recent"],
            "pages_today": pages_today(), "daily_budget": daily_budget(), "round_gap_min": round_gap_minutes(),
            "learned_pages": learned, "topics": topics, "watch": watch}


def learned_pages(limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 200))
    with db.connect() as conn:
        rows = conn.execute("SELECT id, file_name, url, learn_topic, status FROM sources WHERE origin = 'learned' "
                            "ORDER BY id DESC LIMIT ? OFFSET ?", (limit, max(0, int(offset)))).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM sources WHERE origin = 'learned'").fetchone()[0]
    return {"total": total, "pages": [dict(r) for r in rows]}


def remove_all_learned() -> dict:
    """Remove every page the app learned by itself (pages the owner added are untouched)."""
    from . import importer
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM sources WHERE origin = 'learned'")]
    if not ids:
        return {"ok": True, "removed": 0, "message": "Nothing learned by the app to remove."}
    return importer.remove_sources(ids, feedback=False)  # a bulk reset says nothing about any site


def set_enabled(on: bool) -> dict:
    db.set_setting("learn_on", bool(on))
    global _fails, _next_round
    _fails, _next_round = 0, 0.0
    _say("idle" if on else "off", "Web learning is on. The next round starts shortly." if on else "Web learning is off.")
    if not on:
        crawler_state = crawler.status()
        if crawler_state.get("state") == "running" and crawler_state.get("origin") == "learned":
            crawler.stop()
    _wake.set()
    return {"ok": True, "on": bool(on)}


def set_limits(daily_pages: int | None = None, round_gap_min: int | None = None) -> dict:
    if daily_pages is not None:
        db.set_setting("learn_daily", max(DAILY_MIN, min(DAILY_MAX, int(daily_pages))))
    if round_gap_min is not None:
        db.set_setting("learn_gap_min", max(5, min(240, int(round_gap_min))))
    return {"ok": True}


def run_now() -> dict:
    """The "Learn now" button: do a round at the next tick (only if on and within the daily budget)."""
    global _next_round
    if not enabled():
        return {"ok": False, "message": "Turn web learning on first."}
    _next_round = 0.0
    _wake.set()
    return {"ok": True}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def start() -> None:
    """Start the background loop once (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _say("idle" if enabled() else "off", "Web learning is on." if enabled() else "Web learning is off.")
    _thread = threading.Thread(target=_loop, name="kb-learner", daemon=True)
    _thread.start()


def _loop() -> None:
    while True:
        _wake.wait(TICK_SECONDS)
        _wake.clear()
        try:
            run_round()
        except Exception as exc:  # the loop must survive anything
            _say("error", f"Web learning hit a problem and will try again later: {exc}")


def _read_one(url: str, scope: str, max_pages: int, topic: str) -> int:
    """Read one address with the crawler and wait for it; returns the pages added."""
    r = crawler.start(url, scope=scope, max_pages=max_pages, origin="learned", topic=topic)
    if not r.get("ok"):
        return 0
    deadline = time.time() + CRAWL_WAIT_SECONDS + (max_pages * 6 if scope != "page" else 0)
    while time.time() < deadline:
        st = crawler.status()
        if st.get("state") != "running":
            return int(st.get("stored", 0))
        if not enabled():
            crawler.stop()
        time.sleep(0.5)
    crawler.stop()
    return int(crawler.status().get("stored", 0))


def run_round(now: float | None = None) -> str:
    """
    One round if one is due. RETURNS what happened: "off", "waiting", "busy", "budget", "offline", "idle",
    "topic" or "watch" (used by the tests). Public so tests can call it without waiting for the clock.
    """
    global _next_round, _fails
    now = now if now is not None else time.time()
    if not enabled():
        return "off"
    if now < _next_round:
        return "waiting"
    if crawler.status().get("state") == "running":
        return "busy"  # the owner is reading a page himself; never compete with him
    left = daily_budget() - pages_today()
    if left <= 0:
        _say("idle", f"Today's budget of {daily_budget()} pages is used up. It continues tomorrow.")
        _next_round = now + 1800
        return "budget"
    with db.connect() as conn:
        topic = conn.execute("SELECT id, topic FROM learn_topics WHERE status = 'pending' "
                             "ORDER BY (origin = 'owner') DESC, id LIMIT 1").fetchone()
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=WATCH_REREAD_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        watch = conn.execute("SELECT id, url, scope, max_pages FROM learn_watch WHERE last_run IS NULL OR last_run < ? "
                             "ORDER BY last_run IS NOT NULL, last_run LIMIT 1", (cutoff,)).fetchone()
    # v0.18: judge the pages learned so far; remove thin ones, block sites that keep giving junk.
    try:
        m = coverage.maintain()
        if m["pruned"]:
            _note("(clean-up)", "", f"removed {m['pruned']} page{'s' if m['pruned'] != 1 else ''} with almost no readable text")
        for h in m["blocked"]:
            _note("(clean-up)", h, "site blocked — mostly thin or removed pages, never cited")
    except Exception:
        pass
    if not topic and not watch and coverage.auto_enabled():
        # Nothing to do: look for what the library lacks and make topics for it (at most every 12 hours).
        last = db.get_setting("coverage_checked", 0) or 0
        if now - last > 12 * 3600:
            db.set_setting("coverage_checked", now)
            plan = coverage.plan_topics()
            if plan["added"]:
                _say("idle", plan["message"])
                _note("(gaps)", "", plan["message"])
                _next_round = 0.0
                return "planned"
    if not topic and not watch:
        _say("idle", "Web learning is on. Nothing to learn right now — add a topic or a watch address, or it will "
                     "pick up questions your files could not answer.")
        return "idle"
    if not is_online():
        _say("idle", "No internet connection right now. It will try again later.")
        _next_round = now + 600
        return "offline"
    gap = round_gap_minutes() * 60
    if topic:
        _say("reading", f"Learning about “{topic['topic']}”…")
        urls, blocked = coverage.rank_urls(search(topic["topic"], limit=PAGES_PER_TOPIC + 3))  # v0.18: good sites first, junk sites skipped
        urls = urls[:PAGES_PER_TOPIC]
        for h in blocked:
            _note(topic["topic"], h, "skipped — this site keeps giving thin or removed pages")
        added = 0
        if not urls:
            _fails += 1
            note = "no pages found (or the search page did not answer)"
            _note(topic["topic"], "", note)
        else:
            for url in urls:
                if added >= left or not enabled():
                    break
                n = _read_one(url, "page", 1, topic["topic"])
                added += n
                _note(topic["topic"], url, "added" if n else "skipped (nothing new or not readable)")
            _fails = 0 if added else _fails + 1
        _add_today(added)
        with db.connect() as conn:
            conn.execute("UPDATE learn_topics SET status = ?, pages_added = ?, last_run = datetime('now'), note = ? WHERE id = ?",
                         ("done" if urls else "failed", added, None if urls else "No pages found", topic["id"]))
        _say("idle", f"Learned {added} page{'s' if added != 1 else ''} about “{topic['topic']}”.")
        kind = "topic"
    else:
        _say("reading", f"Re-reading {watch['url']}…")
        added = _read_one(watch["url"], watch["scope"], min(watch["max_pages"], max(1, left)), watch["url"])
        _add_today(added)
        with db.connect() as conn:
            conn.execute("UPDATE learn_watch SET last_run = datetime('now'), pages_added = pages_added + ? WHERE id = ?",
                         (added, watch["id"]))
        _note(watch["url"], watch["url"], f"{added} new page{'s' if added != 1 else ''}")
        _say("idle", f"Re-read {watch['url']}: {added} new page{'s' if added != 1 else ''}.")
        _fails = 0
        kind = "watch"
    _next_round = time.time() + gap
    if _fails >= PAUSE_AFTER_FAILS:
        _fails = 0
        _next_round = time.time() + 3 * 3600
        _say("idle", "Several rounds found nothing, so web learning is resting for 3 hours.")
    return kind
