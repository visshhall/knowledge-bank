"""
coverage.py — v0.18 what the app knows, what it lacks, and which web sources are worth reading.

WHAT:  1. COVERAGE. For each category (the ones titles.py tags files with, e.g. "SIEM & Detection") it measures
          how many files and passages the bank holds, how fresh they are, how many are web pages the app
          learned itself, and how often answers actually cited that category in the last 60 days. From that
          a 0–100 coverage score: thin, stale or heavily-used-but-small categories score low.
       2. GAPS → TOPICS. plan_topics() picks the weakest categories (not planned in the last 14 days) and adds
          web-learning topics for them — the AI writes 2 specific search phrases from the titles already in
          that category; without the AI, plain phrases are used. learner.py then searches and reads them.
          This is "fetch data on its own about what it feels is lacking".
       3. PAGE USEFULNESS. Each learned page is judged: useful (cited in an answer), thin (almost no readable
          text after import, or the import failed), or unused (not cited yet). Thin pages are removed by the app.
       4. SITES. Per web site: useful / thin / removed-by-owner counts and a score. A site that keeps producing
          thin or removed pages and has never been cited is BLOCKED automatically — learner.py stops
          reading it; a site that gets cited is preferred. The owner can force block/allow any site.
WHY:   The owner wanted the app to find what is missing by itself and to cope with junk instead of only
       adding more data: "even though it will have junk data I want it to find patterns and learn from it".
       Here the pattern is per-site and per-category quality, measured from real use.
WHEN:  maintain() runs at the start of each web-learning round (learner.py); plan_topics() when learning is on and
       nothing is waiting; status() when Learning is opened; note_removed() when the owner removes a learned page.
LIMITS: categories are the built-in ones plus those grown by taxonomy.py; a file that fits none is "unplaced" until
       taxonomy.py groups it (it is not planned for until then).
CONNECTED TO: db.py (site_stats — schema v20; sources.origin, categories), taxonomy.py (all_top: built-in + grown categories), learner.py
       (calls maintain, plan_topics, rank_urls), importer.py (remove_sources calls note_removed; prune uses
       remove_sources), chat.py/importer.py (_cited_source_ids reads which sources answers cited),
       ollama_client.py (topic phrases), server.py (/coverage/*), Learning.jsx.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from urllib.parse import urlparse

from . import db, ollama_client, taxonomy

TARGET_SOURCES = 8        # files in a category before its "files" part is full marks
TARGET_PASSAGES = 300     # passages before its "depth" part is full marks
FRESH_DAYS = 90           # a category with nothing added in this long loses its freshness marks
WEAK_BELOW = 50           # coverage score under this = a gap
DEMAND_WEAK_BELOW = 70    # a category answers cite a lot is a gap under this
DEMAND_CITES = 3          # "a lot" = cited this many times in 60 days
PLAN_COOLDOWN_DAYS = 14   # one category is not planned again within this
MAX_PLAN_PER_RUN = 2      # categories planned per run (2 topics each)
THIN_PASSAGES = 3         # a learned page with fewer passages after import is "thin"
BLOCK_MIN_PAGES = 4       # pages seen from a site before it can be blocked
BLOCK_BAD_SHARE = 0.6     # share thin/removed that blocks a never-cited site
UNUSED_DAYS = 45          # a learned page not cited in this long is listed as unused


def _host(url: str | None) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _cited_counts(conn, days: int = 60) -> dict[int, int]:
    """source id → how many answers (last `days`) cited it."""
    from .importer import _cited_source_ids
    out: dict[int, int] = {}
    for r in conn.execute("SELECT sources_json FROM chat_messages WHERE role = 'assistant' AND sources_json IS NOT NULL "
                          "AND sources_json != '{}' AND created_at >= datetime('now', ?)", (f"-{days} days",)):
        for sid in _cited_source_ids(r["sources_json"]):
            out[int(sid)] = out.get(int(sid), 0) + 1
    return out


# ---------------------------------------------------------------------------
# 1. Coverage per category
# ---------------------------------------------------------------------------

def score_category(sources: int, passages: int, days_since_new: float | None) -> int:
    """0–100: files (50) + depth (30) + freshness (20)."""
    files = min(1.0, sources / TARGET_SOURCES) * 50
    depth = min(1.0, passages / TARGET_PASSAGES) * 30
    if days_since_new is None:
        fresh = 0.0
    else:
        fresh = 20 * max(0.0, 1 - max(0.0, days_since_new - 30) / (FRESH_DAYS * 2 - 30))
    return round(files + depth + fresh)


def categories() -> list[dict]:
    """Coverage of every category, weakest (highest priority) first."""
    names = taxonomy.all_top()   # v0.19: built-in categories plus the ones grown from the data
    stats = {n: {"category": n, "sources": 0, "passages": 0, "learned": 0, "cited": 0, "newest": None} for n in names}
    with db.connect() as conn:
        cites = _cited_counts(conn)
        rows = conn.execute(
            "SELECT s.id, s.categories, s.origin, s.added_at, "
            "(SELECT COUNT(*) FROM passages p WHERE p.source_id = s.id) AS passages "
            "FROM sources s WHERE s.status = 'extracted' AND s.replaced_by IS NULL").fetchall()
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    for r in rows:
        try:
            cats = json.loads(r["categories"] or "[]")
        except ValueError:
            cats = []
        for c in cats:
            if c not in stats:
                continue
            st = stats[c]
            st["sources"] += 1
            st["passages"] += r["passages"]
            st["learned"] += r["origin"] == "learned"
            st["cited"] += cites.get(r["id"], 0)
            if not st["newest"] or r["added_at"] > st["newest"]:
                st["newest"] = r["added_at"]
    out = []
    for st in stats.values():
        days = None
        if st["newest"]:
            try:
                days = (now - _dt.datetime.fromisoformat(st["newest"])).total_seconds() / 86400
            except ValueError:
                days = None
        st["score"] = score_category(st["sources"], st["passages"], days)
        st["weak"] = st["score"] < WEAK_BELOW or (st["cited"] >= DEMAND_CITES and st["score"] < DEMAND_WEAK_BELOW)
        st["priority"] = (100 - st["score"]) + 5 * min(st["cited"], 10)
        out.append(st)
    out.sort(key=lambda x: -x["priority"])
    return out


# ---------------------------------------------------------------------------
# 2. Gaps → web-learning topics
# ---------------------------------------------------------------------------

def _planned() -> dict:
    return db.get_setting("coverage_planned", {}) or {}


def auto_enabled() -> bool:
    return bool(db.get_setting("learn_auto_gaps", True))


def set_auto(on: bool) -> dict:
    db.set_setting("learn_auto_gaps", bool(on))
    return {"ok": True, "on": bool(on)}


def _fallback_queries(category: str, titles_: list[str]) -> list[str]:
    qs = [f"{category} fundamentals explained", f"{category} practical guide examples"]
    if titles_:
        qs[1] = f"{category} {titles_[0]}"[:120]
    return qs


def parse_queries(text: str, limit: int = 2) -> list[str]:
    """The model's reply → up to `limit` clean search phrases (JSON list, or lines)."""
    items: list = []
    m = re.search(r"\[.*\]", text or "", re.S)
    if m:
        try:
            items = [x for x in json.loads(m.group(0)) if isinstance(x, str)]
        except ValueError:
            items = []
    if not items:
        items = [re.sub(r"^\s*[-*•\d.)]+\s*", "", ln) for ln in (text or "").splitlines() if ln.strip()]
    out = []
    for it in items:
        q = " ".join(it.split()).strip(" \"'")
        if 8 <= len(q) <= 120 and q.lower() not in [o.lower() for o in out]:
            out.append(q)
    return out[:limit]


def _queries_for(category: str) -> list[str]:
    with db.connect() as conn:
        have = [r["t"] for r in conn.execute(
            "SELECT COALESCE(title, file_name) AS t FROM sources WHERE status = 'extracted' AND categories LIKE ? "
            "ORDER BY id DESC LIMIT 8", (f'%"{category}"%',))]
    try:
        from . import chat
        if ollama_client.is_running() and chat.status().get("state") != "running":
            prompt = (f"CATEGORY: {category}\nTITLES ALREADY IN THE LIBRARY:\n" + ("\n".join(f"- {t}" for t in have) or "(none)")
                      + "\n\nWrite 2 different web search phrases (4–9 words each) for pages that would fill what this category "
                        "is missing — practical, specific, not the titles above. JSON list of strings only.")
            r = ollama_client.generate(chat.chat_model(), prompt, system="You help build a cybersecurity study library.",
                                       temperature=0.3, num_ctx=2048, num_predict=120)
            qs = parse_queries(r.text)
            if qs:
                return qs
    except Exception:
        pass
    return _fallback_queries(category, have)


def plan_topics(force: bool = False) -> dict:
    """
    Add web-learning topics for the weakest categories. RETURNS {"ok", "added": n, "categories": [...], "message"}.
    Weak = coverage score under WEAK_BELOW, or heavily cited and under DEMAND_WEAK_BELOW. Each category is
    planned at most once per PLAN_COOLDOWN_DAYS (unless `force`, the "Fill the gaps now" button).
    """
    from . import learner
    planned = _planned()
    today = _dt.date.today()
    chosen, added = [], 0
    for c in categories():
        if len(chosen) >= MAX_PLAN_PER_RUN:
            break
        if not c["weak"]:
            continue
        last = planned.get(c["category"])
        if last and not force and (today - _dt.date.fromisoformat(last)).days < PLAN_COOLDOWN_DAYS:
            continue
        for q in _queries_for(c["category"]):
            if learner.add_topic(q, origin="coverage").get("ok"):
                added += 1
        planned[c["category"]] = today.isoformat()
        chosen.append(c["category"])
    db.set_setting("coverage_planned", planned)
    msg = (f"Added {added} topic{'s' if added != 1 else ''} for: {', '.join(chosen)}." if added else
           "No category is weak enough to fill right now." if not chosen else "Those topics were already on the list.")
    return {"ok": True, "added": added, "categories": chosen, "message": msg}


# ---------------------------------------------------------------------------
# 3 + 4. Learned pages and sites
# ---------------------------------------------------------------------------

def note_removed(urls: list[str]) -> None:
    """The owner removed these learned pages by hand: count it against their sites."""
    try:
        with db.connect() as conn:
            for u in urls:
                h = _host(u)
                if h:
                    conn.execute("INSERT INTO site_stats(host, removed) VALUES (?, 1) "
                                 "ON CONFLICT(host) DO UPDATE SET removed = removed + 1", (h,))
    except Exception:
        pass


def _learned(conn) -> list[dict]:
    cites = _cited_counts(conn, 365)
    rows = conn.execute(
        "SELECT s.id, s.url, s.status, s.file_name, s.learn_topic, s.added_at, "
        "(SELECT COUNT(*) FROM passages p WHERE p.source_id = s.id) AS passages "
        "FROM sources s WHERE s.origin = 'learned' AND s.status IN ('extracted', 'failed')").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["cited"] = cites.get(r["id"], 0)
        d["thin"] = r["status"] == "failed" or r["passages"] < THIN_PASSAGES
        d["verdict"] = "useful" if d["cited"] else ("thin" if d["thin"] else "unused")
        out.append(d)
    return out


def maintain() -> dict:
    """
    Judge learned pages and sites. Removes thin learned pages (nothing readable), then recomputes each site's
    numbers and blocks sites that keep producing junk. RETURNS {"pruned": n, "blocked": [hosts], "unblocked": [hosts]}.
    """
    from . import importer
    with db.connect() as conn:
        pages = _learned(conn)
    thin_ids = [p["id"] for p in pages if p["thin"] and not p["cited"]]
    pruned = 0
    if thin_ids:
        r = importer.remove_sources(thin_ids, feedback=False)
        pruned = r.get("removed", 0)
    thin_by_host: dict[str, int] = {}
    for p in pages:
        if p["id"] in thin_ids:
            thin_by_host[_host(p["url"])] = thin_by_host.get(_host(p["url"]), 0) + 1
    blocked_now, unblocked = [], []
    with db.connect() as conn:
        rows = conn.execute("SELECT host, removed, thin, manual, blocked FROM site_stats").fetchall()
        known = {r["host"]: dict(r) for r in rows}
        by_host: dict[str, dict] = {}
        for p in pages:
            if p["id"] in thin_ids:
                continue
            h = by_host.setdefault(_host(p["url"]), {"pages": 0, "useful": 0})
            h["pages"] += 1
            h["useful"] += bool(p["cited"])
        hosts = set(by_host) | set(thin_by_host) | set(known)
        for h in hosts:
            if not h:
                continue
            old = known.get(h, {"removed": 0, "thin": 0, "manual": 0, "blocked": 0})
            thin_total = old["thin"] + thin_by_host.get(h, 0)       # pruned thin pages are remembered here
            cur = by_host.get(h, {"pages": 0, "useful": 0})
            seen = cur["pages"] + thin_total + old["removed"]
            bad = thin_total + old["removed"]
            useful = cur["useful"]
            score = useful * 3 + cur["pages"] - 2 * thin_total - 3 * old["removed"]
            if old["manual"] == 1:
                blocked = 1
            elif old["manual"] == 2:
                blocked = 0
            else:
                blocked = int(seen >= BLOCK_MIN_PAGES and bad / seen >= BLOCK_BAD_SHARE and useful == 0)
            if blocked and not old["blocked"]:
                blocked_now.append(h)
            if old["blocked"] and not blocked:
                unblocked.append(h)
            conn.execute("INSERT INTO site_stats(host, pages, useful, thin, removed, score, blocked, manual, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(host) DO UPDATE SET "
                         "pages = excluded.pages, useful = excluded.useful, thin = excluded.thin, score = excluded.score, "
                         "blocked = excluded.blocked, updated_at = excluded.updated_at",
                         (h, cur["pages"], useful, thin_total, old["removed"], score, blocked, old["manual"]))
    return {"pruned": pruned, "blocked": blocked_now, "unblocked": unblocked}


def rank_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    """
    Search results → (urls worth reading best first, hosts skipped because they are blocked).
    Known good sites first (higher score), unknown sites in their original order, blocked sites dropped.
    """
    with db.connect() as conn:
        stats = {r["host"]: r for r in conn.execute("SELECT host, score, blocked FROM site_stats")}
    keep, skipped = [], []
    for i, u in enumerate(urls):
        h = _host(u)
        st = stats.get(h)
        if st and st["blocked"]:
            skipped.append(h)
            continue
        keep.append((-(st["score"] if st else 0), i, u))
    keep.sort()
    return [u for _, _, u in keep], skipped


def set_site(host: str, action: str) -> dict:
    """The owner forces a site blocked ('block'), allowed ('allow') or back to the app's own judgement ('auto')."""
    host = _host(host if "//" in host else f"https://{host}")
    if not host or action not in ("block", "allow", "auto"):
        return {"ok": False, "message": "Unknown site or action."}
    manual = {"block": 1, "allow": 2, "auto": 0}[action]
    with db.connect() as conn:
        conn.execute("INSERT INTO site_stats(host, manual, blocked) VALUES (?, ?, ?) "
                     "ON CONFLICT(host) DO UPDATE SET manual = excluded.manual", (host, manual, 1 if manual == 1 else 0))
    maintain()
    return {"ok": True}


def prune_unused(days: int = UNUSED_DAYS) -> dict:
    """The "Remove unused pages" button: learned pages older than `days` that no answer ever cited."""
    from . import importer
    with db.connect() as conn:
        ids = [p["id"] for p in _learned(conn) if not p["cited"]
               and p["added_at"] <= (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")]
    if not ids:
        return {"ok": True, "removed": 0, "message": f"No learned page is older than {days} days and unused."}
    return importer.remove_sources(ids, feedback=False)


def status() -> dict:
    cats = categories()
    with db.connect() as conn:
        pages = _learned(conn)
        sites = [dict(r) for r in conn.execute(
            "SELECT host, pages, useful, thin, removed, score, blocked, manual FROM site_stats "
            "WHERE pages + thin + removed > 0 OR manual != 0 ORDER BY blocked DESC, score DESC LIMIT 40")]
    counts = {"useful": 0, "unused": 0, "thin": 0}
    for p in pages:
        counts[p["verdict"]] += 1
    return {"auto": auto_enabled(), "categories": cats, "weak": [c["category"] for c in cats if c["weak"]],
            "learned": {"total": len(pages), **counts}, "sites": sites,
            "planned": _planned()}
