"""
understand.py — v0.10: the AI works out what each point IS FOR, so topics and
articles are organised by meaning instead of by where the text happened to sit.

WHAT:  For every point of a topic (after facts.py folded the repeats) the local
       AI decides
         role   what the point does for a learner:
                  definition   what something is / what a term means
                  how_it_works how or why it works, or how it is abused
                  step         one step of a procedure or attack sequence
                  detection    how to spot it: log sources, event IDs, signals
                  query        a query or command (found by rules, no AI needed)
                  response     how to prevent, contain or fix it
                  example      a concrete case, tool, malware or sample
                  note         anything else
         about  the specific thing it is about, 1-4 words ("Spearphishing
                attachment", "DNS tunneling") — this is how variants and
                related things are told apart.
       From that, structure() builds a topic's logical outline:
         sections in a teaching order (what it is → how it works → steps →
         detection → queries → response → examples → notes), points grouped by
         what they are about, steps kept in document order, plus insights the
         reasoning found: statements that CONTRADICT each other (the AI judge in
         facts.py said CONFLICT) and sections the documents never cover
         (e.g. nothing about detection).
       writer.py writes the article from this outline; the Topics screen shows
       it under "By meaning".

WHY:   The owner: "our reasoning logic is still very weak — I want the AI to
       understand how things work and show data accordingly instead of just
       merging them with no logic of what's being shown." The article used to
       get a flat list of the most central points and a fixed template, so
       related facts landed in the wrong place and nothing explained how
       things connect.

WHEN:  tag_all() runs after "Build/Update topics" and at the start of "Write
       remaining" (the only places the AI is asked); structure() runs whenever
       a topic is opened or written and uses only saved answers, so it is
       instant. Points the AI has not looked at yet get a rule-based role and
       are counted in the "not analysed yet" note.

CONNECTED TO: facts.py (folded points, contradictions), db.py (point_roles
       table, schema v13), ollama_client.py (FAST model), distill.py
       (topic_detail returns "structure"), writer.py (article material),
       app/src/Topics.jsx ("By meaning" view).
"""

from __future__ import annotations

import hashlib
import re
import threading

from . import config, db, ollama_client

# Bump when the way articles are organised changes: older articles are then written once more.
VERSION = 1

# Teaching order and the headings the owner sees (also used by the writer).
ROLES: list[tuple[str, str]] = [
    ("definition", "What it is"),
    ("how_it_works", "How it works"),
    ("step", "Steps, in order"),
    ("detection", "How to detect it"),
    ("query", "Queries and commands"),
    ("response", "What to do about it"),
    ("example", "Examples and cases"),
    ("note", "Other notes"),
]
ROLE_TITLE = dict(ROLES)
ROLE_KEYS = [k for k, _ in ROLES]

BATCH = 6                 # points per AI request
POINT_CHARS = 450         # each point is cut to this for the request
AI_POINTS_PER_RUN = 600   # most points tagged in one run; the rest next time

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Rules — used when the AI has not answered yet, and for queries
# ---------------------------------------------------------------------------

_DETECT = re.compile(r"\b(event\s*id|eventid|log(?:s|ged|ging)?\b|monitor|detect|alert|audit|sysmon|telemetry|"
                     r"indicator|ioc|siem|sigma|hunt|anomal)", re.I)
_RESPOND = re.compile(r"\b(mitigat|prevent|block|restrict|disable|harden|patch|least privilege|recommend|"
                      r"remediat|contain|isolate|should be (?:disabled|blocked|restricted))", re.I)
_DEFINE = re.compile(r"^\W*[\w\s\-/()]{2,60}?\b(is|are|refers to|means|is defined as|also known as|a type of)\b", re.I)
_EXAMPLE = re.compile(r"\b(for example|e\.g\.|such as|case study|observed|used by|malware|ransomware|apt\d*|"
                      r"campaign|sample)\b", re.I)


def rule_role(text: str) -> str:
    """Best guess from wording alone (no AI)."""
    t = text.strip()
    lines = [l for l in t.split("\n") if l.strip()]
    code = sum(1 for l in lines if l.lstrip().startswith(("```", "|", "\t")))
    if lines and (t.startswith("```") or code / len(lines) > 0.5 or "```" in t):
        return "query"
    if _DETECT.search(t):
        return "detection"
    if _RESPOND.search(t):
        return "response"
    if _DEFINE.search(t.split("\n")[0][:160]):
        return "definition"
    if _EXAMPLE.search(t):
        return "example"
    return "how_it_works"


def _key(text: str) -> str:
    norm = re.sub(r"\s+", " ", text.lower()).strip()[:500]
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def load_roles() -> dict[str, tuple[str, str]]:
    """Saved AI answers: text-key → (role, about)."""
    with db.connect() as conn:
        return {r["key"]: (r["role"], r["about"] or "") for r in conn.execute("SELECT key, role, about FROM point_roles")}


# ---------------------------------------------------------------------------
# The AI step
# ---------------------------------------------------------------------------

ROLE_PROMPT = """Sort each point from a cybersecurity document by what it does for a learner. Each point sits between <point> tags and is ONE item, even if its text contains its own numbers or bullets.

Roles:
definition - says what something is, or what a term means
how_it_works - explains how or why something works, or how it is abused
step - one step of a procedure or an attack sequence
detection - how to spot it: log sources, event IDs, signals, indicators
response - how to prevent, mitigate, contain or fix it
example - a concrete case, tool, malware family or sample
note - anything else

Also give "about": the specific thing the point is about, in 1-4 words (for example "DNS tunneling" or "Spearphishing attachment"). Use the same words for the same thing.

Answer with exactly one line per point, using the point's id, like this: P1|role|about

POINTS:
{points}
"""

_LINE = re.compile(r"^\W*P(\d+)\W*\|\s*([a-z_]+)\s*\|\s*(.*?)\s*$", re.I)


def parse_answer(answer: str, count: int) -> dict[int, tuple[str, str]]:
    """'P2|detection|DNS tunneling' lines → {2: ('detection', 'DNS tunneling')}; unusable lines are ignored."""
    out: dict[int, tuple[str, str]] = {}
    for line in answer.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        n, role, about = int(m.group(1)), m.group(2).lower(), m.group(3).strip(" .*_`\"'")
        role = {"howitworks": "how_it_works", "how": "how_it_works", "steps": "step", "response": "response",
                "mitigation": "response", "queries": "query"}.get(role, role)
        if 1 <= n <= count and role in ROLE_KEYS and role != "query":
            out[n] = (role, about[:40])
    return out


def _tag_batch(texts: list[str]) -> dict[int, tuple[str, str]]:
    block = "\n\n".join(f'<point id="P{i + 1}">\n{t[:POINT_CHARS]}\n</point>' for i, t in enumerate(texts))
    r = ollama_client.generate(config.FAST_MODEL, ROLE_PROMPT.format(points=block),
                               temperature=0.0, num_ctx=3072, num_predict=24 * len(texts) + 16)
    return parse_answer(r.text or "", len(texts))


def ai_ready() -> bool:
    return ollama_client.is_running() and ollama_client.has_model(config.FAST_MODEL)


MAX_SUBJECTS = 6
_GENERIC = frozenset("""method methods communication communications abuse using based via function functions technique
techniques general attack attacks activity activities data use used usage over through into from between multiple
other alternate alternative""".split())


def group_labels(labels: list[str]) -> dict[str, str]:
    """
    Group the AI's per-point subject labels into at most MAX_SUBJECTS subjects.
    HOW (rules, deterministic): count the meaningful words across the labels;
    the word that appears in the most labels names a subject and takes every
    label containing it ("Proxy-based C2 communication", "DNS-based C2 …" →
    "C2"); repeat while a word still covers two or more of the remaining
    labels; leftover single labels keep their own name (merged into "Other
    points" only if that would exceed MAX_SUBJECTS). A small model asked to do
    this grouping itself produced nonsense, so the AI only labels and the
    grouping is done here.
    RETURNS {label: subject} (empty when there are few enough labels already).
    """
    if len(labels) <= MAX_SUBJECTS:
        return {}

    def words(label: str) -> list[str]:
        out = []
        for w in re.findall(r"[A-Za-z0-9]+", label):
            lw = w.lower()
            lw = lw[:-1] if len(lw) > 4 and lw.endswith("s") else lw
            if len(lw) >= 2 and lw not in _GENERIC and lw not in ("the", "and", "for", "with", "of", "to", "in", "os"):
                out.append(lw)
        return out

    left = {l: set(words(l)) for l in labels}
    mapping: dict[str, str] = {}
    casing: dict[str, dict[str, int]] = {}
    for l in labels:
        for w in re.findall(r"[A-Za-z0-9]+", l):
            casing.setdefault(w.lower().rstrip("s") if len(w) > 4 else w.lower(), {}).setdefault(w, 0)
            casing[w.lower().rstrip("s") if len(w) > 4 else w.lower()][w] += 1
    while left:
        counts: dict[str, int] = {}
        for ws in left.values():
            for w in ws:
                counts[w] = counts.get(w, 0) + 1
        best = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])), default=None)
        if not best or best[1] < 2:
            break
        word = best[0]
        shown = max(casing.get(word, {word: 1}).items(), key=lambda kv: kv[1])[0]
        subject = shown.upper() if (len(shown) <= 3 or any(c.isdigit() for c in shown)) else shown.capitalize()
        for l in [l for l, ws in left.items() if word in ws]:
            mapping[l] = subject
            del left[l]
    if len(set(mapping.values())) + len(left) > MAX_SUBJECTS:
        for l in left:
            mapping[l] = "Other points"
    return mapping


def _consolidate_subjects(topic_id: int, title: str) -> None:
    """
    Make points about the same thing share one subject (group_labels) and save
    it, so related points really sit together in the outline.
    """
    from . import facts
    with db.connect() as conn:
        points, _a, _s = facts.topic_points(conn, topic_id)
    roles = load_roles()
    labels = sorted({roles[_key(p["text"])][1] for p in points if _key(p["text"]) in roles and roles[_key(p["text"])][1]})
    mapping = group_labels(labels)
    if not mapping:
        return
    with db.connect() as conn:
        for p in points:
            k = _key(p["text"])
            if k in roles and roles[k][1] in mapping:
                conn.execute("UPDATE point_roles SET about = ? WHERE key = ?", (mapping[roles[k][1]], k))


def tag_topic(topic_id: int, budget: int = 10_000) -> int:
    """Ask the AI about this topic's points it has not seen yet. RETURNS points tagged."""
    from . import facts
    with db.connect() as conn:
        points, _a, _s = facts.topic_points(conn, topic_id)
    known = load_roles()
    todo = [p for p in points if _key(p["text"]) not in known and rule_role(p["text"]) != "query"][:budget]
    done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            answers = _tag_batch([p["text"] for p in batch])
        except ollama_client.OllamaError:
            break
        with db.connect() as conn:
            for n, (role, about) in answers.items():
                conn.execute("INSERT OR REPLACE INTO point_roles(key, role, about) VALUES (?, ?, ?)",
                             (_key(batch[n - 1]["text"]), role, about))
        done += len(answers)
    if done:
        try:
            with db.connect() as conn:
                title = conn.execute("SELECT title FROM topics WHERE id = ?", (topic_id,)).fetchone()["title"]
            _consolidate_subjects(topic_id, title)
        except Exception:
            pass                                     # grouping is a bonus; the roles are already saved
    return done


def tag_all(progress=None) -> int:
    """
    Tag every non-data topic's untagged points (at most AI_POINTS_PER_RUN per run;
    the rest next time). Does nothing when the AI isn't available or a run is
    already going. RETURNS points tagged.
    """
    if not ai_ready() or not _lock.acquire(blocking=False):
        return 0
    try:
        with db.connect() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM topics WHERE kind != 'data' ORDER BY id")]
        total = 0
        for n, tid in enumerate(ids, 1):
            if total >= AI_POINTS_PER_RUN:
                break
            if progress:
                progress(n, len(ids))
            total += tag_topic(tid, AI_POINTS_PER_RUN - total)
        return total
    except ollama_client.OllamaError:
        return 0
    finally:
        _lock.release()


# ---------------------------------------------------------------------------
# The outline
# ---------------------------------------------------------------------------

def _about_key(about: str) -> str:
    a = re.sub(r"[^a-z0-9 ]+", " ", about.lower())
    a = re.sub(r"\b(\w{4,})s\b", r"\1", a)           # plural → singular, so "proxies"/"proxy" meet
    return re.sub(r"\s+", " ", a).strip()


def annotate(points: list[dict], roles: dict[str, tuple[str, str]] | None = None) -> int:
    """Put "role", "about" and "analysed" (True when the AI answered) on every point. RETURNS how many were analysed."""
    roles = load_roles() if roles is None else roles
    analysed = 0
    for p in points:
        got = roles.get(_key(p["text"]))
        rule = rule_role(p["text"])
        if rule == "query":
            p["role"], p["about"], p["analysed"] = "query", "", True
        elif got:
            p["role"], p["about"], p["analysed"] = got[0], got[1], True
        else:
            p["role"], p["about"], p["analysed"] = rule, "", False
        analysed += 1 if p["analysed"] else 0
    return analysed


def structure(points: list[dict], conflicts: list[dict] | None = None, kind: str = "subject") -> dict | None:
    """
    The topic's logical outline.
    points   facts.topic_points() output (most central first)
    RETURNS {"sections": [{"key","title","groups":[{"about","point_ids"}]}],
             "analysed", "total", "insights": [{"kind","text",...}]} or None for spreadsheet topics.
    """
    if kind == "data" or not points:
        return None
    analysed = annotate(points) if not all("role" in p for p in points) else sum(1 for p in points if p.get("analysed"))
    by_role: dict[str, list[dict]] = {k: [] for k in ROLE_KEYS}
    for p in points:                                  # points arrive most central first
        by_role[p["role"]].append(p)
    sections = []
    for key in ROLE_KEYS:
        pts = by_role[key]
        if not pts:
            continue
        if key == "step":
            pts = sorted(pts, key=lambda p: tuple(p.get("order") or (0, 0, 0)))   # a procedure keeps its order
        groups: dict[str, dict] = {}
        for p in pts:
            g = groups.setdefault(_about_key(p["about"]) if p["about"] else "", {"about": p["about"] or None, "point_ids": []})
            g["point_ids"].append(p["id"])
        ordered = list(groups.values())
        if len(ordered) == 1:
            ordered[0]["about"] = None                # one subject: no sub-headings needed
        sections.append({"key": key, "title": ROLE_TITLE[key], "groups": ordered})

    insights: list[dict] = []
    for c in conflicts or []:
        insights.append({"kind": "conflict", "text": "These two statements contradict each other.",
                         "a": c["a"], "b": c["b"], "a_point": c.get("a_point"), "b_point": c.get("b_point")})
    have = {s["key"] for s in sections}
    if len(points) >= 3 and have & {"definition", "how_it_works", "step"}:
        for key, msg in (("detection", "Your files don't say how to detect this."),
                         ("response", "Your files don't say how to prevent or respond to this.")):
            if key not in have:
                insights.append({"kind": "gap", "text": msg})
    if analysed < len(points):
        insights.append({"kind": "pending", "text": f"{len(points) - analysed} of {len(points)} points are not analysed "
                                                    f"yet — they are placed by wording until the AI has looked at them."})
    return {"sections": sections, "analysed": analysed, "total": len(points), "insights": insights}


# ---------------------------------------------------------------------------
# Material for the article writer
# ---------------------------------------------------------------------------

def writer_material(points: list[dict], conflicts: list[dict], direct_limit: int) -> tuple[list[dict], list[dict], str]:
    """
    Choose and arrange the points the article is written from.
    HOW: every section gets a share of the `direct_limit` slots (round-robin,
    most central first), so a topic with many "how it works" points can't push
    out its detection or response points; the direct points are laid out under
    their section headings (and sub-headings per subject), numbered in that
    order. Points that don't fit go to the writer's note-taking passes.
    RETURNS (direct points in prompt order, extra points, text for the prompt).
    """
    if not all("role" in p for p in points):
        annotate(points)
    queues = {k: [p for p in points if p["role"] == k] for k in ROLE_KEYS}
    chosen: list[dict] = []
    while len(chosen) < direct_limit and any(queues.values()):
        for k in ROLE_KEYS:
            if queues[k] and len(chosen) < direct_limit:
                chosen.append(queues[k].pop(0))
    chosen_ids = {p["id"] for p in chosen}
    extra = [p for p in points if p["id"] not in chosen_ids]
    ordered: list[dict] = []
    parts: list[str] = []
    for key in ROLE_KEYS:
        mine = [p for p in chosen if p["role"] == key]
        if not mine:
            continue
        if key == "step":
            mine.sort(key=lambda p: tuple(p.get("order") or (0, 0, 0)))
        subjects = {_about_key(p["about"]) for p in mine if p["about"]}
        parts.append(f"### {ROLE_TITLE[key]}")
        last = None
        for p in sorted(mine, key=lambda p: _about_key(p["about"]) if len(subjects) > 1 and key != "step" else ""):
            if len(subjects) > 1 and key != "step" and _about_key(p["about"]) != last:
                last = _about_key(p["about"])
                parts.append(f"#### About: {p['about'] or 'general'}")
            ordered.append(p)
            parts.append(f"[{len(ordered)}] " + p.get("_prompt_text", p["text"]))
    return ordered, extra, "\n\n".join(parts)
