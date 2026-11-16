"""
taxonomy.py — v0.19 categories and sub-categories that grow from the data instead of a fixed list.

WHAT:  titles.py has 11 built-in cybersecurity categories. This module adds to them as the library changes:
       1. NEW CATEGORIES. Files that fit no category are grouped. The AI (when free) names new categories from
          the titles and first lines of the unplaced files and lists the words that mark them; without the AI,
          words shared by at least 3 unplaced files form a group named after the word. A new category needs at
          least 2 files (AI) or 3 files (no AI), is checked against existing names so near-duplicates are folded
          into the existing category, and every file that fits is tagged.
       2. SUB-CATEGORIES. A category with 12 or more files is split into 2–6 sub-categories ("SIEM & Detection / KQL").
          Files are tagged "Parent / Child" in sources.subcats.
       3. TAGGING NEW FILES. importer._name_and_tag calls classify() so each new file gets built-in and grown
          categories and sub-categories at import time.
       4. HOUSEKEEPING. Near-duplicate grown categories are merged; a grown category left with no files is removed.
       The owner can rename, merge or delete any grown category (built-in ones are fixed and can only be extended).
WHY:   The owner: "categories need to be expanded automatically as per new data, not anything fixed."
WHEN:  A background loop (start(), every 5 minutes) runs grow() while there are unplaced files or a big category
       without sub-categories; "Find new categories now" in Learning runs it at once; classify() runs at import.
       Off-switch: setting taxonomy_auto (Learning → Categories).
LIMITS: the AI's names can be odd — that is why each grown category is listed and can be renamed/merged/deleted.
       Existing files that already carry a built-in category are not re-tagged with grown ones (only unplaced files are),
       so grown categories start from what the old list could not place.
CONNECTED TO: db.py (taxonomy table, sources.categories/subcats — schema v21), titles.py (built-in CATEGORIES,
       categorise), importer.py (_name_and_tag, list shape), coverage.py (categories come from all_top()),
       ollama_client.py (names), chat.py (chat_model, status), server.py (/taxonomy/*, start()), Learning.jsx, Library.jsx.
"""
from __future__ import annotations

import json
import re
import threading
import time

from . import db, ollama_client, titles

MIN_GROUP_AI = 2          # files needed for the AI to create a category
MIN_GROUP_PLAIN = 3       # files needed when no AI is available
SPLIT_AT = 12             # files in a category before it is split into sub-categories
MAX_SUBS = 6
MAX_NEW_PER_RUN = 3
MAX_DYNAMIC = 40          # grown top-level categories in all
BATCH = 15                # unplaced files shown to the AI at once
SAMPLE_CHARS = 1500
LOOP_SECONDS = 300
NAME_MIN, NAME_MAX = 3, 40

_STOP = set("""a an the and or of to in on for with from by at as is are was were be been this that these those it its
into than then them they you your we our can could should would will may might not no yes if else when where which who
whom what why how all any each more most some such other only own same so too very also about above after again
against before below between both during further here there over under until up down out off once page pages file
files document documents chapter section part figure table example examples using use used based new one two three
introduction overview guide notes note lesson lessons tutorial basics vol volume edition series""".split())
_TOKEN = re.compile(r"[a-z][a-z0-9+#.\-]{2,}")

_lock = threading.Lock()
_wake = threading.Event()
_started = False
_last = {"at": None, "message": "Not run yet."}


# ---------------------------------------------------------------------------
# Names and terms
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower().replace("&", " and ")).strip()


def _words(name: str) -> set[str]:
    return {w for w in _norm(name).split() if w not in _STOP and w != "and"}


def similar(a: str, b: str) -> bool:
    """Same category under another name: same words, or a one-word difference in a short name."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return _norm(a) == _norm(b)
    j = len(wa & wb) / len(wa | wb)
    return j >= 0.6 or wa <= wb and len(wa) >= 1 and len(wb) <= 3 or wb <= wa and len(wa) <= 3


def _clean_name(name: str) -> str | None:
    name = re.sub(r"\s+", " ", re.sub(r"[\"'`*#]", "", name or "")).strip(" .-:/")
    if not (NAME_MIN <= len(name) <= NAME_MAX) or "/" in name:
        return None
    return name[0].upper() + name[1:]


def _clean_terms(terms) -> list[str]:
    out = []
    for t in terms or []:
        if not isinstance(t, str):
            continue
        t = re.sub(r"\s+", " ", t.lower()).strip(" .,;:\"'")
        if 3 <= len(t) <= 30 and t not in _STOP and t not in out:
            out.append(t)
    return out[:12]


def _hits(text_low: str, terms: list[str]) -> tuple[int, int]:
    """(distinct terms found, total occurrences) with whole-word matching."""
    d = c = 0
    for t in terms:
        n = len(re.findall(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", text_low))
        if n:
            d += 1
            c += n
    return d, c


# ---------------------------------------------------------------------------
# What exists
# ---------------------------------------------------------------------------

def _rows(conn, parent=False) -> list[dict]:
    q = "SELECT name, parent, terms_json, origin, status FROM taxonomy WHERE status = 'active' AND "
    q += "parent IS NOT NULL" if parent else "parent IS NULL"
    out = []
    for r in conn.execute(q + " ORDER BY id"):
        d = dict(r)
        try:
            d["terms"] = json.loads(d.pop("terms_json") or "[]")
        except ValueError:
            d["terms"] = []
        out.append(d)
    return out


def all_top() -> list[str]:
    """Built-in categories followed by the grown ones."""
    with db.connect() as conn:
        return list(titles.CATEGORIES) + [r["name"] for r in _rows(conn)]


def auto_enabled() -> bool:
    return bool(db.get_setting("taxonomy_auto", True))


def set_auto(on: bool) -> dict:
    db.set_setting("taxonomy_auto", bool(on))
    if on:
        _wake.set()
    return {"ok": True, "on": bool(on)}


# ---------------------------------------------------------------------------
# Tagging
# ---------------------------------------------------------------------------

def classify(text: str, title: str = "") -> tuple[list[str], list[str]]:
    """
    (categories, sub-categories) for a file. Built-in categories first (titles.categorise); when none fits,
    the grown ones (2 or more of their words, or one in the title). Sub-categories come from the chosen categories.
    """
    full = f"{title}\n{text}"
    cats = titles.categorise(text)            # built-in list judged on the text alone, as before v0.19
    low = " " + re.sub(r"\s+", " ", full.lower()) + " "
    with db.connect() as conn:
        dyn, subs = _rows(conn), _rows(conn, parent=True)
    if not cats:
        scored = []
        tl = " " + (title or "").lower() + " "
        for r in dyn:
            d, c = _hits(low, r["terms"])
            if d >= 2 or (d >= 1 and _hits(tl, r["terms"])[0] >= 1):
                scored.append((d * 3 + min(c, 30), r["name"]))
        scored.sort(reverse=True)
        if scored:
            best = scored[0][0]
            cats = [n for s, n in scored[:2] if s >= best * 0.6]
    return cats, _subtag(low, cats, subs)


def _subtag(low: str, cats: list[str], subs: list[dict]) -> list[str]:
    out = []
    for c in cats:
        best, pick = 0, None
        for s in subs:
            if s["parent"] != c:
                continue
            d, n = _hits(low, s["terms"])
            if d >= 1 and d * 3 + min(n, 20) > best:
                best, pick = d * 3 + min(n, 20), s["name"]
        if pick:
            out.append(f"{c} / {pick}")
    return out


def _sample(conn, sid: int, chars: int = SAMPLE_CHARS) -> tuple[str, str]:
    row = conn.execute("SELECT COALESCE(title, file_name) AS t FROM sources WHERE id = ?", (sid,)).fetchone()
    text = " ".join(r[0] for r in conn.execute(
        "SELECT text FROM passages WHERE source_id = ? ORDER BY page_number, ordinal LIMIT 12", (sid,)))
    return (row["t"] if row else ""), re.sub(r"\s+", " ", text)[:chars]


def _set_tags(conn, sid: int, cats=None, subs=None) -> None:
    if cats is not None:
        conn.execute("UPDATE sources SET categories = ? WHERE id = ?", (json.dumps(cats), sid))
    if subs is not None:
        conn.execute("UPDATE sources SET subcats = ? WHERE id = ?", (json.dumps(subs), sid))


def _unplaced(conn, limit: int = 400) -> list[int]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM sources WHERE status = 'extracted' AND replaced_by IS NULL AND "
        "(categories IS NULL OR categories IN ('', '[]')) ORDER BY id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------------------
# The AI (replaceable in tests) and the plain fallback
# ---------------------------------------------------------------------------

def _ask(prompt: str) -> str | None:
    """The model's reply, or None when it is not available right now (not running, or busy writing an answer)."""
    try:
        from . import chat
        if not ollama_client.is_running() or chat.status().get("state") == "running":
            return None
        r = ollama_client.generate(chat.chat_model(), prompt, system="You organise a cybersecurity study library. Reply with JSON only.",
                                   temperature=0.2, num_ctx=4096, num_predict=700)
        return r.text
    except Exception:
        return None


def _json(text: str | None):
    m = re.search(r"[\[{].*[\]}]", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _tokens(text: str) -> list[str]:
    return [w for w in _TOKEN.findall((text or "").lower()) if w not in _STOP and not w.isdigit()]


def _grams(text: str) -> set[str]:
    toks = _tokens(text)
    g = set(toks)
    g.update(f"{a} {b}" for a, b in zip(toks, toks[1:]))
    return g


def plain_groups(docs: dict[int, str], min_group: int, max_groups: int, max_share: float = 0.6,
                 avoid: set[str] | None = None, heads: dict[int, str] | None = None) -> list[dict]:
    """
    Without the AI: groups of files sharing a distinctive word or phrase.
    docs {file id: title + first lines}; heads {file id: title} breaks ties toward words that appear in titles. RETURNS [{"name", "terms", "files"}], biggest first. A word is distinctive when
    at least `min_group` files have it but not more than `max_share` of all files (so "security" never wins).
    """
    avoid = avoid or set()
    grams = {i: _grams(t) for i, t in docs.items()}
    head_grams = {i: _grams(t) for i, t in (heads or {}).items()}
    pool = set(docs)
    total = len(docs)
    out = []
    while len(out) < max_groups and len(pool) >= min_group:
        df: dict[str, int] = {}
        for i in pool:
            for g in grams[i]:
                df[g] = df.get(g, 0) + 1
        limit = max(min_group, int(max_share * total)) if total >= 6 else len(pool)   # share of ALL files, not of what is left
        cands = [(n, len(g.split()), g) for g, n in df.items()
                 if min_group <= n <= limit and not any(w in avoid for w in g.split())]
        if not cands:
            break
        in_titles = lambda g: sum(1 for i in pool if g in head_grams.get(i, ()))  # noqa: E731
        cands.sort(key=lambda x: (-x[0], -in_titles(x[2]), -x[1], x[2]))
        top = cands[0][2]
        files = {i for i in pool if top in grams[i]}
        co: dict[str, int] = {}
        for i in files:
            for g in grams[i]:
                if g != top:
                    co[g] = co.get(g, 0) + 1
        terms = [top] + [g for g, n in sorted(co.items(), key=lambda x: (-x[1], x[0]))
                         if n >= max(2, len(files) // 2) and g not in avoid][:7]
        out.append({"name": " ".join(w.upper() if len(w) <= 3 else w.title() for w in top.split()),
                    "terms": _clean_terms(terms), "files": sorted(files)})
        pool -= files
    return out


# ---------------------------------------------------------------------------
# Growing
# ---------------------------------------------------------------------------

def _exists(name: str) -> str | None:
    """The existing category (built-in or grown) this name is the same as, if any."""
    for n in all_top():
        if similar(name, n):
            return n
    return None


def _add_category(conn, name: str, terms: list[str], parent: str | None = None) -> bool:
    if conn.execute("SELECT 1 FROM taxonomy WHERE lower(name) = lower(?) AND IFNULL(parent,'') = IFNULL(?, '')",
                    (name, parent)).fetchone():
        return False
    conn.execute("INSERT INTO taxonomy(name, parent, terms_json, origin) VALUES (?, ?, ?, 'auto')",
                 (name, parent, json.dumps(terms)))
    return True


def _grow_top(summary: dict) -> None:
    with db.connect() as conn:
        ids = _unplaced(conn)
    if len(ids) < MIN_GROUP_AI:
        return
    # 1. Place unplaced files into categories that grew since they were imported.
    with db.connect() as conn:
        placed = 0
        for sid in ids:
            t, s = _sample(conn, sid)
            cats, subs = classify(s, t)
            if cats:
                _set_tags(conn, sid, cats, subs)
                placed += 1
    summary["placed"] += placed
    with db.connect() as conn:
        ids = _unplaced(conn)
    dynamic_now = 0
    with db.connect() as conn:
        dynamic_now = len(_rows(conn))
    room = min(MAX_NEW_PER_RUN, MAX_DYNAMIC - dynamic_now)
    if room <= 0 or len(ids) < MIN_GROUP_AI:
        return
    with db.connect() as conn:
        smp = {sid: _sample(conn, sid, 600) for sid in ids}
    docs = {sid: " ".join(v) for sid, v in smp.items()}
    heads = {sid: v[0] for sid, v in smp.items()}
    groups: list[dict] = []
    batch = ids[:BATCH]
    listing = "\n".join(f"{n}. {docs[sid][:260]}" for n, sid in enumerate(batch, 1))
    reply = _ask("EXISTING CATEGORIES: " + ", ".join(all_top()) + "\n\nFILES THAT FIT NONE OF THEM:\n" + listing +
                 '\n\nPropose up to 3 NEW categories (2–4 word names) that each cover at least 2 of these files. '
                 'JSON: [{"name": "...", "terms": ["6 to 10 lowercase words or phrases that mark this category"], "files": [1, 4]}]')
    data = _json(reply)
    if isinstance(data, dict):
        data = data.get("categories")
    if isinstance(data, list):
        for g in data:
            try:
                name, terms = _clean_name(g.get("name", "")), _clean_terms(g.get("terms"))
                files = [batch[int(n) - 1] for n in g.get("files", []) if 1 <= int(n) <= len(batch)]
            except (AttributeError, TypeError, ValueError):
                continue
            if name and len(terms) >= 3 and len(set(files)) >= MIN_GROUP_AI:
                groups.append({"name": name, "terms": terms, "files": sorted(set(files))})
        summary["ai"] = True
    if not groups:
        groups = plain_groups(docs, MIN_GROUP_PLAIN, room, avoid={w for n in all_top() for w in _words(n)}, heads=heads)
    for g in groups[:room]:
        same = _exists(g["name"])
        with db.connect() as conn:
            if same:                                    # the AI named an existing category differently → extend it
                if same not in titles.CATEGORIES:
                    row = conn.execute("SELECT terms_json FROM taxonomy WHERE name = ?", (same,)).fetchone()
                    if row:
                        merged = _clean_terms(json.loads(row["terms_json"]) + g["terms"])
                        conn.execute("UPDATE taxonomy SET terms_json = ? WHERE name = ?", (json.dumps(merged), same))
                name = same
            else:
                name = g["name"]
                if _add_category(conn, name, g["terms"]):
                    summary["new"].append(name)
            for sid in g["files"]:
                cats = [name]
                _set_tags(conn, sid, cats, [])
                summary["placed"] += 1


def _grow_subs(summary: dict) -> None:
    with db.connect() as conn:
        top = list(titles.CATEGORIES) + [r["name"] for r in _rows(conn)]
        have = {r["parent"] for r in _rows(conn, parent=True)}
        counts = {n: [r["id"] for r in conn.execute(
            "SELECT id FROM sources WHERE status = 'extracted' AND replaced_by IS NULL AND categories LIKE ?",
            (f'%"{n}"%',))] for n in top}
    for name in top:
        ids = counts[name]
        if name in have or len(ids) < SPLIT_AT:
            continue
        with db.connect() as conn:
            smp = {sid: _sample(conn, sid, 700) for sid in ids[:60]}
        docs = {sid: " ".join(v) for sid, v in smp.items()}
        heads = {sid: v[0] for sid, v in smp.items()}
        groups = []
        listing = "\n".join(f"- {t[:120]}" for t in list(docs.values())[:30])
        data = _json(_ask(f"CATEGORY: {name}\nFILES IN IT:\n{listing}\n\nSplit it into 2 to {MAX_SUBS} sub-categories (2–4 word names). "
                          'JSON: [{"name": "...", "terms": ["5 to 8 lowercase words or phrases that mark it"]}]'))
        if isinstance(data, dict):
            data = data.get("subcategories") or data.get("categories")
        if isinstance(data, list):
            for g in data[:MAX_SUBS]:
                try:
                    n, terms = _clean_name(g.get("name", "")), _clean_terms(g.get("terms"))
                except AttributeError:
                    continue
                if n and len(terms) >= 2 and not similar(n, name):
                    groups.append({"name": n, "terms": terms})
        if not groups:
            groups = [{"name": g["name"], "terms": g["terms"]}
                      for g in plain_groups(docs, MIN_GROUP_PLAIN, MAX_SUBS, max_share=0.7, avoid=_words(name), heads=heads)]
        if len(groups) < 2:
            continue
        with db.connect() as conn:
            for g in groups:
                if _add_category(conn, g["name"], g["terms"], parent=name):
                    summary["subs"].append(f"{name} / {g['name']}")
        retag_subs(name)


def retag_subs(category: str) -> int:
    """Re-tag every file of a category with its sub-categories (after sub-categories change)."""
    n = 0
    with db.connect() as conn:
        subs = [s for s in _rows(conn, parent=True) if s["parent"] == category]
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sources WHERE status = 'extracted' AND replaced_by IS NULL AND categories LIKE ?",
            (f'%"{category}"%',))]
        for sid in ids:
            t, s = _sample(conn, sid)
            low = " " + re.sub(r"\s+", " ", f"{t}\n{s}".lower()) + " "
            tags = _subtag(low, [category], subs)
            old = conn.execute("SELECT subcats FROM sources WHERE id = ?", (sid,)).fetchone()["subcats"]
            keep = [x for x in json.loads(old or "[]") if not x.startswith(category + " / ")]
            _set_tags(conn, sid, subs=keep + tags)
            n += bool(tags)
    return n


def _housekeeping(summary: dict) -> None:
    """Fold near-duplicate grown categories together; drop grown categories with no files left."""
    with db.connect() as conn:
        dyn = _rows(conn)
    for i, a in enumerate(dyn):
        for b in dyn[i + 1:]:
            if similar(a["name"], b["name"]):
                merge(b["name"], a["name"])
                summary["merged"].append(f"{b['name']} → {a['name']}")
    with db.connect() as conn:
        for r in _rows(conn):
            n = conn.execute("SELECT COUNT(*) FROM sources WHERE categories LIKE ?", (f'%"{r["name"]}"%',)).fetchone()[0]
            if n == 0:
                conn.execute("DELETE FROM taxonomy WHERE name = ? OR parent = ?", (r["name"], r["name"]))
                summary["dropped"].append(r["name"])


def grow() -> dict:
    """One pass: place files, add categories, split big ones, tidy. RETURNS {"new", "subs", "placed", "merged", "dropped", "ai", "message"}."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "Already looking for categories."}
    summary = {"ok": True, "new": [], "subs": [], "placed": 0, "merged": [], "dropped": [], "ai": False}
    try:
        _grow_top(summary)
        _grow_subs(summary)
        _housekeeping(summary)
    except Exception as exc:
        summary.update(ok=False, error=str(exc))
    finally:
        _lock.release()
    bits = []
    if summary["new"]:
        bits.append("new categories: " + ", ".join(summary["new"]))
    if summary["subs"]:
        bits.append(f"{len(summary['subs'])} sub-categor{'y' if len(summary['subs']) == 1 else 'ies'}")
    if summary["placed"] and not summary["new"]:
        bits.append(f"{summary['placed']} file{'s' if summary['placed'] != 1 else ''} placed")
    summary["message"] = ("Added " + "; ".join(bits) + ".") if bits else "Nothing new to add right now."
    _last.update(at=time.strftime("%H:%M"), message=summary["message"])
    return summary


# ---------------------------------------------------------------------------
# Owner controls
# ---------------------------------------------------------------------------

def _is_grown(name: str) -> bool:
    with db.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM taxonomy WHERE name = ? AND parent IS NULL", (name,)).fetchone())


def _replace_tag(old: str, new: str | None) -> None:
    """Rename (new = name) or remove (new = None) a top-level tag on every file; sub-category tags follow."""
    with db.connect() as conn:
        for r in conn.execute("SELECT id, categories, subcats FROM sources WHERE categories LIKE ? OR subcats LIKE ?",
                              (f'%"{old}"%', f'%"{old} / %')).fetchall():
            cats = [c for c in json.loads(r["categories"] or "[]")]
            cats = [new if c == old else c for c in cats if not (c == old and new is None)]
            seen = []
            for c in cats:
                if c not in seen:
                    seen.append(c)
            subs = []
            for x in json.loads(r["subcats"] or "[]"):
                if x.startswith(old + " / "):
                    if new:
                        subs.append(f"{new} / {x[len(old) + 3:]}")
                else:
                    subs.append(x)
            _set_tags(conn, r["id"], seen, subs)


def rename(name: str, new: str) -> dict:
    new = _clean_name(new)
    if not new or not _is_grown(name):
        return {"ok": False, "message": "Only categories the app added can be renamed, to a name of 3–40 letters."}
    if new != name and any(_norm(new) == _norm(n) for n in all_top()):
        return {"ok": False, "message": "A category with that name already exists."}
    with db.connect() as conn:
        conn.execute("UPDATE taxonomy SET name = ?, origin = 'owner' WHERE name = ? AND parent IS NULL", (new, name))
        conn.execute("UPDATE taxonomy SET parent = ? WHERE parent = ?", (new, name))
    _replace_tag(name, new)
    return {"ok": True}


def merge(name: str, into: str) -> dict:
    """Move every file of grown category `name` into `into` (built-in or grown) and remove `name`."""
    if not _is_grown(name) or name == into or into not in all_top():
        return {"ok": False, "message": "Choose another category to merge into."}
    with db.connect() as conn:
        row = conn.execute("SELECT terms_json FROM taxonomy WHERE name = ?", (name,)).fetchone()
        if into not in titles.CATEGORIES and row:
            t = conn.execute("SELECT terms_json FROM taxonomy WHERE name = ?", (into,)).fetchone()
            conn.execute("UPDATE taxonomy SET terms_json = ? WHERE name = ?",
                         (json.dumps(_clean_terms(json.loads(t["terms_json"]) + json.loads(row["terms_json"]))), into))
        conn.execute("DELETE FROM taxonomy WHERE parent = ?", (name,))
        conn.execute("DELETE FROM taxonomy WHERE name = ? AND parent IS NULL", (name,))
        for r in conn.execute("SELECT id, categories, subcats FROM sources WHERE categories LIKE ?", (f'%"{name}"%',)).fetchall():
            cats = []
            for c in json.loads(r["categories"] or "[]"):
                c = into if c == name else c
                if c not in cats:
                    cats.append(c)
            subs = [x for x in json.loads(r["subcats"] or "[]") if not x.startswith(name + " / ")]
            _set_tags(conn, r["id"], cats, subs)
    return {"ok": True}


def delete(name: str) -> dict:
    """Remove a grown category: its files become unplaced (the next pass may group them again — merge instead to keep them)."""
    if not _is_grown(name):
        return {"ok": False, "message": "Only categories the app added can be deleted."}
    with db.connect() as conn:
        conn.execute("DELETE FROM taxonomy WHERE parent = ?", (name,))
        conn.execute("DELETE FROM taxonomy WHERE name = ? AND parent IS NULL", (name,))
    _replace_tag(name, None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Status and the background loop
# ---------------------------------------------------------------------------

def status() -> dict:
    with db.connect() as conn:
        dyn = {r["name"]: r for r in _rows(conn)}
        subs = _rows(conn, parent=True)
        srcs = conn.execute("SELECT categories, subcats FROM sources WHERE status = 'extracted' AND replaced_by IS NULL").fetchall()
        unplaced = len(_unplaced(conn, 100000))
    counts: dict[str, int] = {}
    subcounts: dict[str, int] = {}
    for s in srcs:
        for c in json.loads(s["categories"] or "[]"):
            counts[c] = counts.get(c, 0) + 1
        for x in json.loads(s["subcats"] or "[]"):
            subcounts[x] = subcounts.get(x, 0) + 1
    tops = []
    for name in list(titles.CATEGORIES) + list(dyn):
        tops.append({"name": name, "grown": name in dyn, "origin": dyn[name]["origin"] if name in dyn else "builtin",
                     "terms": dyn[name]["terms"] if name in dyn else [], "files": counts.get(name, 0),
                     "subs": [{"name": s["name"], "files": subcounts.get(f"{name} / {s['name']}", 0)}
                              for s in subs if s["parent"] == name]})
    return {"auto": auto_enabled(), "categories": tops, "unplaced": unplaced, "last": dict(_last)}


def _due() -> bool:
    with db.connect() as conn:
        if len(_unplaced(conn, 50)) >= MIN_GROUP_AI:
            return True
        have = {r["parent"] for r in _rows(conn, parent=True)}
        for n in list(titles.CATEGORIES) + [r["name"] for r in _rows(conn)]:
            if n not in have and conn.execute("SELECT COUNT(*) FROM sources WHERE status = 'extracted' AND replaced_by IS NULL "
                                              "AND categories LIKE ?", (f'%"{n}"%',)).fetchone()[0] >= SPLIT_AT:
                return True
    return False


def _loop() -> None:
    time.sleep(60)
    while True:
        try:
            if auto_enabled() and _due():
                grow()
        except Exception:
            pass
        _wake.wait(LOOP_SECONDS)
        _wake.clear()


def start() -> None:
    """server.py lifespan: background loop (idle when there is nothing to place or split)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="taxonomy", daemon=True).start()
