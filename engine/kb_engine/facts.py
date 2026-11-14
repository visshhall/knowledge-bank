"""
facts.py — v0.9.1: one statement, said once, with every place that said it.

WHAT:  Topics are built from "passages" (a few sentences each). The same
       sentence often sits inside several passages — in another file, on
       another page, or cut at a different place — so whole-passage repeat
       detection (exact text or 95 % similar meaning, distill.py) misses it
       and the article repeats itself. This module works one level down, on
       single statements:

         1. Split every point of a topic into statements (sentences, bullets,
            table lines; a fenced query block is one statement).
         2. A statement is a repeat of an earlier one when
              - the normalised text is identical, or
              - one statement's words are all inside the other (it only adds
                words, none that negate), AND both name exactly the same
                numbers/IDs (T1059.001 ≠ T1059.003, event
                4624 ≠ 4625 — never merged by wording alone).
            Any other overlap of 50 % or more is "borderline" (one changed
            word can flip a meaning): the local AI decides
            SAME / SUBSET / DIFFERENT / CONFLICT once, and the answer is kept
            in the fact_verdicts table so it is never asked again.
         3. Of two matching statements the LONGER one stays (it holds the
            most detail); the shorter one is removed from its point and that
            point's file + page are added as an extra source of the keeper.
            A point left with no statements of its own is folded into the
            point that kept them (citations follow it).
         Nothing is ever deleted from the bank: passages are untouched; this
         is a view computed whenever a topic is shown or written.

WHY:   The owner kept seeing the same data twice in a topic, even from the
       same file ("it needs logical reasoning to figure this out"). Rules
       settle the clear cases instantly and predictably; the AI only judges
       the few pairs rules cannot.

WHEN:  topic_points() runs every time a topic is opened (distill.topic_detail)
       and every time an article/lesson is written (writer.py, lessons.py).
       judge_all() runs after "Build topics"/"Update topics" and at the start
       of "Write remaining" — the only places the AI is asked.

CONNECTED TO: db.py (fact_verdicts, passages, topic_passages), distill.py
       (topic_detail), writer.py, lessons.py, ollama_client.py (FAST model),
       chunking.py (with_section), app/src/Topics.jsx (the "repeats folded"
       line).
"""

from __future__ import annotations

import hashlib
import re
import threading

from . import config, db, ollama_client

# Bump when the merging rules change: written articles then count as out of
# date (writer.py rewrites those that actually had repeats).
VERSION = 1

MIN_WORDS = 6          # shorter lines are headings/labels, never compared
MAYBE_JACCARD = 0.50   # partial overlap above this → ask the AI
MAYBE_CONTAIN = 0.70
MAX_POSTING = 150      # words used by more statements than this are ignored for lookup
LONGER_BY = 1.15       # a match must be this much longer to replace the earlier one
AI_PAIRS_PER_TOPIC = 80
AI_PAIRS_PER_RUN = 600
JUDGE_CHARS = 600

_MARK = re.compile(r"^\s*(?:[▪◦•●○‣>*\-]+|\(?\d{1,3}[.)])\s+")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(])")
_WORDS = re.compile(r"[a-z0-9]+(?:[.\-_][a-z0-9]+)*")
_STOP = set("""the and for are but you all any can her was one our out has had how its may who
did get him his she too use via with that this from they will have been were what when your which
their there these those into than then them also such only over more most some each other about
using used uses can could would should might must shall within without between through during""".split())


# ---------------------------------------------------------------------------
# Splitting and comparing statements
# ---------------------------------------------------------------------------

class _Unit:
    """One piece of a point's text: a statement, a heading/label, or a query block."""
    __slots__ = ("line", "raw", "fact", "code", "keep", "norm", "toks", "digits", "n")

    def __init__(self, line: int, raw: str, fact: bool, code: bool):
        self.line, self.raw, self.fact, self.code, self.keep = line, raw, fact, code, True
        self.norm, self.toks, self.digits, self.n = "", frozenset(), frozenset(), 0
        if fact:
            words = _WORDS.findall(raw.lower())
            self.norm = " ".join(words)
            self.n = len(words)
            self.toks = frozenset(w for w in words if (len(w) >= 3 or any(c.isdigit() for c in w) or w in _NEGATING) and w not in _STOP)
            self.digits = frozenset(w for w in words if any(c.isdigit() for c in w))


def _is_heading(part: str, has_marker: bool) -> bool:
    """A label such as "USE CASE 13: COMMAND AND CONTROL" or "Step 2: Investigation": no bullet,
    no closing punctuation, short — or written in capitals. Never compared as a statement."""
    p = part.strip()
    letters = [c for c in p if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        return True
    return (not has_marker) and len(p.split()) <= 10 and not p.endswith((".", "!", "?", ":", ";", ","))


def _units(text: str) -> list[_Unit]:
    """
    Cut a point's text into units. HOW: a ```fenced``` block is ONE unit (a
    query is kept or dropped whole, compared by exact text only); a line
    longer than 180 characters is cut at sentence ends; a leading bullet or
    "13." is ignored for comparing. Lines under MIN_WORDS words are labels.
    """
    out: list[_Unit] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].rstrip()
        if s.strip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            block = "\n".join(lines[i:min(j + 1, len(lines))])
            inner = "\n".join(lines[i + 1:j]).strip()
            out.append(_Unit(i, block, bool(inner), True))
            i = j + 1
            continue
        if not s.strip():
            out.append(_Unit(i, "", False, False))
        elif s.startswith(("\t", "|", "    ")):
            out.append(_Unit(i, s, len(_WORDS.findall(s.lower())) >= 3, True))
        else:
            m = _MARK.match(s)
            prefix = m.group(0) if m else ""
            body = s[len(prefix):].strip()
            parts = _SENT.split(body) if len(body) > 180 else [body]
            for k, part in enumerate(parts):
                raw = (prefix + part) if k == 0 else part
                is_fact = len(_WORDS.findall(part.lower())) >= MIN_WORDS and not _is_heading(part, bool(prefix))
                out.append(_Unit(i, raw, is_fact, False))
        i += 1
    return out


def _pair_key(a: str, b: str) -> str:
    return hashlib.sha1("\x00".join(sorted((a, b))).encode("utf-8")).hexdigest()


def load_verdicts() -> dict[str, str]:
    """All saved AI answers (key → SAME/SUBSET/DIFFERENT/CONFLICT)."""
    with db.connect() as conn:
        return {r["key"]: r["verdict"] for r in conn.execute("SELECT key, verdict FROM fact_verdicts")}


_NEGATING = frozenset("""not no never cannot cant without none neither nor disable disabled disables deny denied
denies prevent prevents prevented fail fails failed unable except""".split())


def _relation(f: _Unit, g: _Unit, verdicts: dict[str, str], pending: list | None) -> bool:
    """
    Do statements f and g say the same thing?
      - identical text, or the same words in another order/spacing → yes
      - one statement's words are ALL inside the other (it only adds words)
        and the extra words don't negate anything → yes
      - anything else that overlaps ≥ 50 % → "borderline": a single changed
        word can flip a meaning ("symmetrically" vs "asymmetrically"), so only
        the saved AI answer decides; with none yet the pair is queued in
        `pending` and counts as different (never merged by guesswork).
    Different numbers/IDs, or queries/tables that are not identical → no.
    """
    if f.norm == g.norm:
        return True
    if f.code or g.code:
        return False                      # queries and tables: exact text only
    if f.digits != g.digits:
        return False                      # different numbers/IDs → different facts
    small, big = (f, g) if len(f.toks) <= len(g.toks) else (g, f)
    if not small.toks or small.n < MIN_WORDS:
        return False
    if f.toks == g.toks:
        return True
    if small.toks <= big.toks:
        if not ((big.toks - small.toks) & _NEGATING):
            return True
    if len(f.toks - g.toks) == 1 and len(g.toks - f.toks) == 1:
        return False                      # one word swapped (link/attachment, symmetric/asymmetric): a different fact
    inter = len(f.toks & g.toks)
    union = len(f.toks | g.toks)
    if union and (inter / union >= MAYBE_JACCARD or inter / len(small.toks) >= MAYBE_CONTAIN):
        key = _pair_key(f.norm, g.norm)
        v = verdicts.get(key)
        if v is None:
            if pending is not None:
                pending.append((key, f.raw, g.raw))
            return False
        if v not in ("SAME", "SUBSET"):
            return False
        # The small model can be too generous ("local" vs "remote" drives): the
        # statement that would be dropped may add at most a few words of its own.
        short = f if f.n <= g.n else g
        other = g if short is f else f
        extra = len(short.toks - other.toks)
        return extra <= max(3, len(short.toks) // 4)
    return False


def _add_sources(target: dict, extra: list[dict]) -> None:
    have = {(s["source_id"], s["page"]) for s in target["sources"]}
    for s in extra:
        k = (s["source_id"], s["page"])
        if k not in have:
            target["sources"].append(dict(s))
            have.add(k)


def _rebuild(units: list[_Unit]) -> str:
    """Join the surviving units back into text; labels survive only with a statement that follows them."""
    out: list[str] = []
    heads: list[str] = []
    by_line: dict[int, list[_Unit]] = {}
    for u in units:
        by_line.setdefault(u.line, []).append(u)
    for li in sorted(by_line):
        parts = by_line[li]
        if not any(u.fact for u in parts):
            raw = " ".join(u.raw for u in parts).strip()
            if raw:
                heads.append(raw)
            elif out and out[-1] != "":
                out.append("")
            continue
        kept = [u.raw for u in parts if (not u.fact) or u.keep]
        if any(u.fact and u.keep for u in parts):
            out.extend(heads)
            heads = []
            out.append(" ".join(kept))
        else:
            heads = []                    # the labels belonged to repeated content
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def plan(points: list[dict], verdicts: dict[str, str] | None = None,
         pending: list | None = None) -> tuple[list[dict], dict[int, int], dict]:
    """
    Merge repeated statements across a topic's points.

    points: dicts with "id", "text", "order" (source, page, ordinal) and
            "sources" [{"source_id","file_name","page"}], in display order.
    RETURNS (points, absorbed, stats):
      points   the same dicts (copies) with trimmed "text", extra "sources"
               and "merged" (statements folded in); fully repeated points
               are gone.
      absorbed {removed point id: id of the point that kept its content}
      stats    {"merged": statements folded, "absorbed": points removed}
    `pending` (a list) collects borderline pairs that still need the AI.
    """
    verdicts = load_verdicts() if verdicts is None else verdicts
    pts = [dict(p, sources=[dict(s) for s in p["sources"]], merged=0) for p in points]
    units = [_units(p["text"]) for p in pts]
    exact: dict[str, tuple[int, _Unit]] = {}
    index: dict[str, list[tuple[int, _Unit]]] = {}
    first_owner: dict[int, int] = {}
    merged = 0
    for pi in sorted(range(len(pts)), key=lambda i: tuple(pts[i].get("order") or (0, 0, 0))):
        for u in units[pi]:
            if not u.fact:
                continue
            hit: tuple[int, _Unit] | None = None
            g = exact.get(u.norm)
            if g and g[1].keep:
                hit = g
            elif not u.code:
                counts: dict[int, tuple[int, _Unit, int]] = {}
                for w in u.toks:
                    posting = index.get(w, ())
                    if len(posting) > MAX_POSTING:
                        continue
                    for gp, gu in posting:
                        if gu.keep:
                            c = counts.get(id(gu))
                            counts[id(gu)] = (gp, gu, (c[2] if c else 0) + 1)
                best = sorted(counts.values(), key=lambda c: -c[2])[:25]
                for gp, gu, shared in best:
                    if shared >= 3 and _relation(u, gu, verdicts, pending):
                        hit = (gp, gu)
                        break
            if hit is None:
                exact.setdefault(u.norm, (pi, u))
                for w in u.toks:
                    index.setdefault(w, []).append((pi, u))
                continue
            gp, gu = hit
            merged += 1
            if u.n > gu.n * LONGER_BY and not u.code:
                gu.keep = False                         # the new, longer one stays
                pts[pi]["merged"] += 1
                _add_sources(pts[pi], pts[gp]["sources"])
                first_owner.setdefault(gp, pi)
                exact[u.norm] = (pi, u)
                for w in u.toks:
                    index.setdefault(w, []).append((pi, u))
            else:
                u.keep = False                          # the earlier one stays
                pts[gp]["merged"] += 1
                _add_sources(pts[gp], pts[pi]["sources"])
                first_owner.setdefault(pi, gp)

    absorbed: dict[int, int] = {}
    gone: set[int] = set()
    for pi, us in enumerate(units):
        facts = [u for u in us if u.fact]
        if facts and not any(u.keep for u in facts):
            gone.add(pi)

    def owner(pi: int) -> int:
        seen = set()
        while pi in gone and pi in first_owner and pi not in seen:
            seen.add(pi)
            pi = first_owner[pi]
        return pi

    result = []
    for pi, p in enumerate(pts):
        if pi in gone:
            o = owner(pi)
            if o in gone or o == pi:
                gone.discard(pi)                         # cycle guard: keep it
            else:
                absorbed[p["id"]] = pts[o]["id"]
                continue
        if any(u.fact and not u.keep for u in units[pi]):
            p["text"] = _rebuild(units[pi]) or p["text"]
        result.append(p)
    return result, absorbed, {"merged": merged, "absorbed": len(absorbed)}


# ---------------------------------------------------------------------------
# A topic's points, as the screen and the writer see them
# ---------------------------------------------------------------------------

def topic_points(conn, topic_id: int) -> tuple[list[dict], dict[int, int], dict]:
    """
    The topic's points after repeat folding, most central first.
    Each: {"id" (repeat-group id), "passage_id", "text" (raw), "section", "fit",
    "order", "sources", "merged"}. RETURNS (points, absorbed, stats) like plan().
    """
    rows = conn.execute(
        """
        SELECT p.id, p.cluster_id, p.text, p.page_number, p.ordinal, p.section,
               COALESCE(s.title, s.file_name) AS file_name, s.id AS source_id, tp.fit
        FROM topic_passages tp
        JOIN passages p ON p.id = tp.passage_id
        JOIN sources s ON s.id = p.source_id
        WHERE tp.topic_id = ?
        ORDER BY tp.fit DESC
        """, (topic_id,)).fetchall()
    points: dict[int, dict] = {}
    for r in rows:
        key = r["cluster_id"] or r["id"]
        p = points.get(key)
        if p is None:
            p = points[key] = {"id": key, "passage_id": r["id"], "text": r["text"], "section": r["section"],
                               "fit": round(r["fit"], 3), "order": [r["source_id"], r["page_number"], r["ordinal"]],
                               "sources": []}
        p["sources"].append({"source_id": r["source_id"], "file_name": r["file_name"], "page": r["page_number"]})
    return plan(list(points.values()))


def count_repeats(topic_id: int) -> int:
    """How many statements of this topic are repeats (0 = nothing to fold)."""
    with db.connect() as conn:
        return topic_points(conn, topic_id)[2]["merged"]


# ---------------------------------------------------------------------------
# The AI judge (borderline pairs only)
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """Two statements from cybersecurity documents.

A: {a}

B: {b}

A reader must lose NOTHING if only the longer statement is kept. If they name different
things (a different type, variant, product, tool, protocol, command, place, step or
condition), say DIFFERENT, even when the sentences look alike.

Answer with exactly one word:
SAME - same fact in other words
SUBSET - one is completely included in the other, which only adds detail
DIFFERENT - they state different facts, or each has information the other lacks
CONFLICT - they contradict each other
"""

_judge_lock = threading.Lock()


def _ask_judge(a: str, b: str) -> str | None:
    """One pair → SAME/SUBSET/DIFFERENT/CONFLICT, or None if the answer is unusable."""
    r = ollama_client.generate(config.FAST_MODEL, JUDGE_PROMPT.format(a=a[:JUDGE_CHARS], b=b[:JUDGE_CHARS]),
                               temperature=0.0, num_ctx=1536, num_predict=8)
    text = (r.text or "").upper()
    for word in ("SUBSET", "SAME", "CONFLICT", "DIFFERENT"):
        if word in text:
            return word
    return None


def judge_topic(topic_id: int, budget: int = AI_PAIRS_PER_TOPIC) -> int:
    """Ask the AI about this topic's open borderline pairs. RETURNS answers saved."""
    return _judge_points_of(topic_id, budget)


def _judge_points_of(topic_id: int, budget: int) -> int:
    pending: list = []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.cluster_id, p.text, p.page_number, p.ordinal, p.source_id FROM topic_passages tp "
            "JOIN passages p ON p.id = tp.passage_id WHERE tp.topic_id = ? ORDER BY tp.fit DESC", (topic_id,)).fetchall()
    pts: dict[int, dict] = {}
    for r in rows:
        k = r["cluster_id"] or r["id"]
        pts.setdefault(k, {"id": k, "text": r["text"], "order": [r["source_id"], r["page_number"], r["ordinal"]],
                           "sources": []})
    plan(list(pts.values()), load_verdicts(), pending)
    seen, saved = set(), 0
    for key, a, b in pending:
        if key in seen:
            continue
        seen.add(key)
        if saved >= budget:
            break
        try:
            v = _ask_judge(a, b)
        except ollama_client.OllamaError:
            break
        if v:
            with db.connect() as conn:
                conn.execute("INSERT OR REPLACE INTO fact_verdicts(key, verdict) VALUES (?, ?)", (key, v))
            saved += 1
    return saved


def ai_ready() -> bool:
    return ollama_client.is_running() and ollama_client.has_model(config.FAST_MODEL)


def judge_all(progress=None) -> int:
    """
    Judge borderline pairs for every non-data topic (at most AI_PAIRS_PER_RUN
    in total, so a run stays short; the rest is done next time). Safe when the
    AI isn't available: does nothing. RETURNS answers saved.
    """
    if not ai_ready() or not _judge_lock.acquire(blocking=False):
        return 0
    try:
        with db.connect() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT t.id FROM topics t WHERE t.kind != 'data' ORDER BY "
                "(SELECT COUNT(*) FROM topic_passages tp WHERE tp.topic_id = t.id) DESC")]
        total = 0
        for n, tid in enumerate(ids, 1):
            if total >= AI_PAIRS_PER_RUN:
                break
            if progress:
                progress(n, len(ids))
            total += _judge_points_of(tid, min(AI_PAIRS_PER_TOPIC, AI_PAIRS_PER_RUN - total))
        return total
    except ollama_client.OllamaError:
        return 0
    finally:
        _judge_lock.release()
