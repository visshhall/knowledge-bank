"""
lessons.py — designs a visual, step-by-step lesson for every topic, automatically.

WHAT:  build_lesson(topic_id) runs four stages:

         1. PROFILE (plain code, no AI) — looks at the topic's material and
            recognises what kind of knowledge it is: a process, an attack
            chain, layers, a hierarchy, a comparison, queries, MITRE
            techniques, spreadsheet tables, binary/IP/CIDR maths, definitions.
         2. PLAN (AI) — the writing model designs 3–7 teaching steps. For each
            step it writes a short explanation and may choose ONE visual from
            a fixed menu (flow, chain, stack, tree, compare, cards, query),
            filling in only words and connections. It also writes a short quiz.
            It cannot invent new diagram kinds or draw anything itself.
         3. CALCULATE (plain code) — things that can be computed are never
            left to the AI: spreadsheet tables are shown from the real grid,
            number patterns in them (doubling, halving, powers of two,
            constant steps) are calculated, and binary/IP/CIDR topics get the
            interactive bit calculator.
         4. VERIFY (plain code) — every number, ID, technique code, IP, CIDR,
            query line and `code` in the AI's text and diagrams must appear in
            the topic's own sources. Anything that doesn't is removed:
            a sentence, a list item, a diagram node (with its arrows), a quiz
            question. A diagram left with too few parts is dropped and the
            step stays as text. What was removed is recorded and shown.

WHY:   Owner request (14 Nov 2026): whatever he imports, the app should decide
       by itself how to explain it — diagram, text or both — "without any
       mistake" and with "proper diagrams, not random". Design choices that
       follow from that:
         - A fixed menu of diagram kinds + automatic layout in the app
           (Lesson.jsx) means diagrams are always clean; the AI never draws.
         - Numbers come from code wherever possible; the AI's numbers are
           only kept if they exist in the sources.
         - Honest limit: wording can still be imperfect; facts can't be
           invented. Every step keeps citation markers to its sources, and
           "Regenerate lesson" redoes a lesson.

WHEN:  - After each article is written (writer.py calls build_lesson), so it is
         part of the overnight "Write articles" job.
       - On demand: "Regenerate lesson" on a topic (POST /lesson/regenerate).

CONNECTED TO: db.py (topics, topic_passages, passages, sources, doc_tables,
       lessons), ollama_client.py, writer.py (shares the model choice and
       calls this), server.py (/lesson, /lesson/regenerate),
       app/src/Lesson.jsx (draws everything).
"""

import json
import math
import re

from . import chunking, db, ollama_client

NUM_CTX = 5120            # article (≤4,500 chars) + instructions + answer
MAX_OUTPUT = 1500         # tokens for the lesson JSON
MAX_STEPS = 7
MAX_QUIZ = 4
ARTICLE_MAX_CHARS = 4500
POINT_MAX_CHARS = 600

# ---------------------------------------------------------------------------
# 1. PROFILE — plain-code recognition of what kind of knowledge this is
# ---------------------------------------------------------------------------

_RX = {
    "steps": re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|step\s*\d+)\s+|\bthen\b|\bnext\b|\bfinally\b", re.I),
    "chain": re.compile(r"\b(?:initial access|execution|persistence|privilege escalation|lateral movement|"
                        r"exfiltration|kill chain|attack chain|stage|phase)\b", re.I),
    "layers": re.compile(r"\b(?:layer|tier|osi|stack|level)\b", re.I),
    "hierarchy": re.compile(r"\b(?:consists of|contains|includes|types of|categories|sub-?type|parent|child)\b", re.I),
    "compare": re.compile(r"\b(?:vs\.?|versus|compared|difference|whereas|unlike|while)\b", re.I),
    "query": re.compile(r"(?m)^\s*\||\b(?:where|summarize|project|extend)\b.*==|index=", re.I),
    "mitre": re.compile(r"\bT\d{4}(?:\.\d{3})?\b"),
    "ipmath": re.compile(r"\b(?:cidr|subnet|netmask|subnet mask|broadcast|network id)\b|\b255\.\d{1,3}\.|/(?:[1-9]|[12]\d|3[0-2])\b", re.I),
    "define": re.compile(r"\b(?:is a|is an|refers to|means|defined as)\b", re.I),
}


def profile(texts: list[str], tables: list[dict]) -> dict:
    """
    Count recognisable features in the material.
    RETURNS {"features": {name: hits}, "suggest": [visual kinds], "tables": n}
    The suggestions are passed to the AI as hints, and decide which
    calculated blocks (tables, ip calculator) are added.
    """
    joined = "\n".join(texts)
    feats = {k: len(rx.findall(joined)) for k, rx in _RX.items()}
    suggest: list[str] = []
    if feats["steps"] >= 2:
        suggest.append("flow")
    if feats["chain"] >= 2:
        suggest.append("chain")
    if feats["layers"] >= 2:
        suggest.append("stack")
    if feats["hierarchy"] >= 2:
        suggest.append("tree")
    if feats["compare"] >= 1:
        suggest.append("compare")
    if feats["query"] >= 1:
        suggest.append("query")
    if feats["define"] >= 2 or feats["mitre"] >= 2:
        suggest.append("cards")
    return {"features": feats, "suggest": suggest or ["cards"], "tables": len(tables),
            "ipmath": feats["ipmath"] >= 3}


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------

def _material(topic_id: int) -> dict:
    """
    Everything the lesson may use: the topic's distinct points (numbered as
    in the article's citations when there is one), the written article, and
    the real spreadsheet grids belonging to this topic's sources/pages.
    """
    with db.connect() as conn:
        t = conn.execute("SELECT id, title, body_markdown, citations, status FROM topics WHERE id = ?",
                         (topic_id,)).fetchone()
        if not t:
            return {}
        rows = conn.execute(
            """SELECT p.id, p.cluster_id, p.text, p.section, p.source_id, p.page_number FROM topic_passages tp
               JOIN passages p ON p.id = tp.passage_id WHERE tp.topic_id = ? ORDER BY tp.fit DESC""",
            (topic_id,),
        ).fetchall()
        pages = {(r["source_id"], r["page_number"]) for r in rows}
        tables = []
        for sid, page in sorted(pages):
            for tb in conn.execute(
                "SELECT d.id, d.name, d.rows_json, s.file_name FROM doc_tables d JOIN sources s "
                "ON s.id = d.source_id WHERE d.source_id = ? AND d.page_number = ?", (sid, page)
            ):
                tables.append({"id": tb["id"], "name": tb["name"], "file": tb["file_name"],
                               "rows": json.loads(tb["rows_json"])})
    seen, points = set(), []
    for r in rows:
        key = r["cluster_id"] or r["id"]
        if key not in seen:
            seen.add(key)
            points.append({"passage_id": key, "text": chunking.with_section(r["text"], r["section"])})
    citations = json.loads(t["citations"]) if t["citations"] else {}
    if not citations:  # no article yet: number the most central points ourselves
        citations = {str(i + 1): p["passage_id"] for i, p in enumerate(points[:8])}
    return {"title": t["title"], "article": t["body_markdown"] if t["status"] == "written" else None,
            "citations": citations, "points": points, "tables": tables}


# ---------------------------------------------------------------------------
# 3. CALCULATE — blocks made by code, never by the AI
# ---------------------------------------------------------------------------

def _num(cell: str) -> float | None:
    try:
        return float(str(cell).replace(",", ""))
    except ValueError:
        return None


def _patterns(rows: list[list[str]]) -> list[str]:
    """
    Find exact number patterns in a table's rows (runs of ≥4 numbers):
    doubling, halving, other constant ratios, constant steps, powers of two.
    Every note is a calculation on the real cells — nothing is guessed.
    """
    notes: list[str] = []
    for row in rows:
        label = next((c for c in row if c and _num(c) is None), "")
        nums = [n for n in (_num(c) for c in row if c) if n is not None]
        if len(nums) < 4 or any(n == 0 for n in nums):
            continue
        ratios = {round(b / a, 9) for a, b in zip(nums, nums[1:])}
        diffs = {round(b - a, 9) for a, b in zip(nums, nums[1:])}
        what = f'"{label}"' if label else "A row"
        if ratios == {2.0}:
            notes.append(f"{what}: each value is double the one before it.")
        elif ratios == {0.5}:
            notes.append(f"{what}: each value is half the one before it.")
        elif len(ratios) == 1:
            notes.append(f"{what}: each value is ×{ratios.pop():g} the one before it.")
        elif len(diffs) == 1:
            notes.append(f"{what}: each value goes up by {diffs.pop():g}.")
        if all(n >= 1 and float(n).is_integer() and (int(n) & (int(n) - 1)) == 0 for n in nums):
            first, last = int(math.log2(nums[0])), int(math.log2(nums[-1]))
            notes.append(f"{what}: every value is a power of 2 (2^{first} … 2^{last}).")
    return list(dict.fromkeys(notes))[:6]


def _calculated_steps(mat: dict, prof: dict) -> list[dict]:
    """Steps that come straight from data: real tables + patterns, IP calculator."""
    steps: list[dict] = []
    for tb in mat["tables"][:3]:
        rows = [r for r in tb["rows"] if any(r)]
        if not rows:
            continue
        steps.append({
            # Spreadsheet sheets vs tables found inside PDFs (v0.6.2+).
            "title": (f"From your spreadsheet: {tb['name']}"
                      if tb["file"].lower().endswith((".xlsx", ".xlsm", ".csv"))
                      else f"From your document: {tb['name'].replace('Table', 'table', 1)}"),
            "text": "This is the exact table from " + tb["file"] + ".",
            "cites": [],
            "computed": True,
            "visual": {"type": "table", "name": tb["name"], "rows": rows[:60], "patterns": _patterns(rows)},
        })
    if prof.get("ipmath"):
        steps.append({
            "title": "Try it: how CIDR, masks and hosts connect",
            "text": "Move the slider. The bits, mask and host counts are calculated live.",
            "cites": [],
            "computed": True,
            "visual": {"type": "ipcalc"},
        })
    return steps


# ---------------------------------------------------------------------------
# 2. PLAN — the AI designs the teaching steps from a fixed menu
# ---------------------------------------------------------------------------

SYSTEM = (
    "You design short visual lessons for a cybersecurity analyst. Use ONLY facts from the material. "
    "Never invent numbers, IDs, commands or names. Reply with JSON only, no other text."
)

MENU = """Visual kinds you may use (pick the one that truly fits each step, or null for text only):
- "flow": a process with arrows. {"type":"flow","nodes":[{"id":"a","label":"short label"}],"edges":[{"from":"a","to":"b","label":"optional"}]}  (3-9 nodes)
- "chain": stages in strict order, e.g. an attack chain or timeline. {"type":"chain","stages":[{"label":"...","detail":"..."}]}  (2-7 stages)
- "stack": layers from top to bottom. {"type":"stack","layers":[{"label":"...","detail":"..."}]}  (2-7 layers)
- "tree": a hierarchy. {"type":"tree","root":"...","children":[{"label":"...","children":[{"label":"..."}]}]}  (max 3 levels)
- "compare": side-by-side comparison. {"type":"compare","columns":["A","B"],"rows":[{"label":"...","cells":["...","..."]}]}
- "cards": key terms or techniques. {"type":"cards","items":[{"label":"...","detail":"..."}]}  (2-8 items)
- "query": walk through a query line by line, copying each line EXACTLY from the material. {"type":"query","lines":[{"code":"...","explain":"..."}]}
Labels: max 6 words. Details: max 20 words."""

PROMPT = """Design a lesson that teaches "{title}" simply, step by step.

{menu}

Recognised in this material: {hints}. Prefer those kinds where they fit; use null when text is clearer.

Return JSON exactly in this shape:
{{"steps":[{{"title":"...","text":"1-3 short sentences","cites":[1],"visual":null}}],
 "quiz":[{{"q":"...","options":["...","...","...","..."],"answer":0,"cite":1}}]}}
{n_steps}; up to {n_quiz} quiz questions. "cites" are the [n] source numbers each step uses.

MATERIAL:
{material}
"""


def _plan(mat: dict, prof: dict, model: str) -> dict | None:
    """Ask the model for the lesson JSON. Returns the parsed dict or None."""
    if mat["article"]:
        material = mat["article"][:ARTICLE_MAX_CHARS]
    else:
        nums = {v: k for k, v in mat["citations"].items()}
        material = "\n\n".join(
            f"[{nums[p['passage_id']]}] {p['text'][:POINT_MAX_CHARS]}"
            for p in mat["points"] if p["passage_id"] in nums
        )
    prompt = PROMPT.format(title=mat["title"], menu=MENU, hints=", ".join(prof["suggest"]),
                           n_steps=f"3-{MAX_STEPS} steps", n_quiz=MAX_QUIZ, material=material)
    try:
        r = ollama_client.generate(model, prompt, system=SYSTEM, temperature=0.2,
                                   num_ctx=NUM_CTX, num_predict=MAX_OUTPUT)
    except ollama_client.OllamaError:
        return None
    m = re.search(r"\{.*\}", r.text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# 4. VERIFY — remove anything that isn't in the sources
# ---------------------------------------------------------------------------

_FACT = re.compile(
    r"`[^`]+`"                                  # inline code
    r"|\bT\d{4}(?:\.\d{3})?\b"                  # MITRE technique IDs
    r"|\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b"  # IPs / masks / CIDR blocks
    r"|(?<![\w/])/\d{1,2}\b"                    # CIDR suffix like /24
    r"|\b\d[\d,]*\.?\d*\b"                      # numbers (any length)
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace(",", "")).strip()


class Checker:
    """
    Holds the topic's source text and counts what it removes.
    A fact passes if its normalised form appears in the sources. Numbers
    must match as whole numbers ("98" does not pass because "980" exists).
    Single-digit numbers are checked together with the word after them:
    "7 controls" passes only if the sources say "7 controls" — unless that
    word is a plain counting word for the lesson itself ("3 steps",
    "4 octets"), which is not a claim about the world. (v0.6: tightened
    after a mock test showed "bypasses 7 controls" slipping through.)
    """

    def __init__(self, sources: list[str]):
        self.corpus = _norm("\n".join(sources))
        self.removed: list[str] = []

    # Words that count parts of the lesson or of a standard structure, not
    # facts that need a source ("3 steps", "4 octets", "8 bits").
    COUNT_WORDS = {"step", "steps", "stage", "stages", "part", "parts", "layer", "layers",
                   "octet", "octets", "bit", "bits", "question", "questions", "phase",
                   "phases", "level", "levels", "way", "ways", "type", "types", "kind",
                   "kinds", "column", "columns", "row", "rows", "line", "lines",
                   # small connecting words: "layer 7 is…", "step 1 of…" make no claim
                   "of", "and", "or", "to", "in", "is", "are", "the", "a", "an", "for",
                   "on", "at", "by", "with", "then", "than", "as"}

    def _in_corpus(self, t: str) -> bool:
        n = _norm(t)
        if re.fullmatch(r"[\d.]+", n):  # plain number: whole-number match only
            return re.search(rf"(?<![\d.]){re.escape(n)}(?![\d]|\.\d)", self.corpus) is not None
        return n in self.corpus

    def ok_fact(self, token: str, context: str = "") -> bool:
        t = token.strip("`").strip()
        if re.fullmatch(r"\d", t):
            m = re.search(rf"(?<![\w.]){t}\s+([a-z]+)", context.lower())
            if not m or m.group(1) in self.COUNT_WORDS:
                return True
            return f"{t} {m.group(1)}" in self.corpus
        return self._in_corpus(t)

    def _bad(self, text: str) -> list[str]:
        return [f for f in _FACT.findall(text) if not self.ok_fact(f, text)]

    def clean_text(self, text: str, max_len: int = 600) -> str:
        """Keep only sentences whose facts are all in the sources."""
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", str(text or "").strip()):
            bad = self._bad(sentence)
            if bad:
                self.removed.append(f"sentence with {', '.join(bad[:3])}")
            elif sentence:
                kept.append(sentence)
        return " ".join(kept)[:max_len]

    def ok_label(self, text: str) -> bool:
        bad = self._bad(str(text or ""))
        if bad:
            self.removed.append(f"diagram item with {', '.join(bad[:3])}")
        return not bad

    def ok_code(self, line: str) -> bool:
        """A query line is kept only if it appears in the sources (spacing ignored)."""
        ok = _norm(line) in self.corpus
        if not ok:
            self.removed.append("query line not found in sources")
        return ok


def _s(v, n: int = 60) -> str:
    return str(v or "").strip()[:n]


def _verify_visual(v: dict | None, ck: Checker) -> dict | None:
    """Return a cleaned visual, or None if it no longer makes a proper diagram."""
    if not isinstance(v, dict):
        return None
    kind = v.get("type")
    if kind == "flow":
        nodes = [{"id": _s(n.get("id"), 20), "label": _s(n.get("label"))}
                 for n in v.get("nodes", [])[:9] if isinstance(n, dict)]
        nodes = [n for n in nodes if n["id"] and n["label"] and ck.ok_label(n["label"])]
        ids = {n["id"] for n in nodes}
        edges = [{"from": _s(e.get("from"), 20), "to": _s(e.get("to"), 20), "label": _s(e.get("label"), 30)}
                 for e in v.get("edges", []) if isinstance(e, dict)]
        edges = [e for e in edges if e["from"] in ids and e["to"] in ids and e["from"] != e["to"]
                 and (not e["label"] or ck.ok_label(e["label"]))]
        linked = {e["from"] for e in edges} | {e["to"] for e in edges}
        nodes = [n for n in nodes if n["id"] in linked]
        return {"type": "flow", "nodes": nodes, "edges": edges} if len(nodes) >= 3 else None
    if kind in ("chain", "stack", "cards"):
        key = {"chain": "stages", "stack": "layers", "cards": "items"}[kind]
        items = [{"label": _s(i.get("label")), "detail": _s(i.get("detail"), 160)}
                 for i in v.get(key, [])[:8] if isinstance(i, dict)]
        items = [i for i in items if i["label"] and ck.ok_label(i["label"]) and ck.ok_label(i["detail"])]
        return {"type": kind, key: items} if len(items) >= 2 else None
    if kind == "tree":
        def walk(node, depth):
            if not isinstance(node, dict) or depth > 3:
                return None
            label = _s(node.get("label"))
            if not label or not ck.ok_label(label):
                return None
            kids = [k for k in (walk(c, depth + 1) for c in node.get("children", [])[:6]) if k]
            return {"label": label, "children": kids}
        root = _s(v.get("root"))
        kids = [k for k in (walk(c, 2) for c in v.get("children", [])[:6]) if k]
        return {"type": "tree", "root": root, "children": kids} if root and ck.ok_label(root) and len(kids) >= 2 else None
    if kind == "compare":
        cols = [_s(c, 40) for c in v.get("columns", [])[:4]]
        rows = []
        for r in v.get("rows", [])[:8]:
            if not isinstance(r, dict):
                continue
            cells = [_s(c, 120) for c in r.get("cells", [])][:len(cols)]
            label = _s(r.get("label"), 40)
            if label and len(cells) == len(cols) and all(ck.ok_label(c) for c in cells + [label]):
                rows.append({"label": label, "cells": cells})
        return {"type": "compare", "columns": cols, "rows": rows} if len(cols) >= 2 and len(rows) >= 2 else None
    if kind == "query":
        lines = [{"code": str(l.get("code", "")).rstrip()[:200], "explain": _s(l.get("explain"), 160)}
                 for l in v.get("lines", [])[:12] if isinstance(l, dict)]
        lines = [l for l in lines if l["code"] and ck.ok_code(l["code"]) and ck.ok_label(l["explain"])]
        return {"type": "query", "lines": lines} if len(lines) >= 2 else None
    return None


_STOPWORDS = set("""about above after again against also because been before being below between both
could does doing down during each from further have having here into itself just more most other
over same should some such than that their them then there these they this those through under
until very what when where which while with would your user users""".split())


def _words_of(text: str) -> set[str]:
    """Content words (4+ letters/digits, no common words), lightly stemmed."""
    out = set()
    for w in re.findall(r"[a-z0-9]{4,}", str(text).lower()):
        if w in _STOPWORDS:
            continue
        for suffix in ("ment", "ing", "ly", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.add(w)
    return out


def _support(option: str, source: str) -> float | None:
    """Share of an option's content words that its source passage contains."""
    words = _words_of(option)
    return len(words & _words_of(source)) / len(words) if words else None


def _check_answer(opts: list[str], ans: int, source: str) -> tuple[int | None, str | None]:
    """
    Is the option marked correct actually what the source says?

    WHY (v0.7, found testing the real qwen3.5:4b): the model sometimes marks
    a distractor as the answer ("Wipe the disk" instead of "Use PtH to
    authenticate"). The fact check can't see that — no invented numbers or
    IDs — so the answer is compared with the question's own source passage:
      - marked answer well supported (≥ 50% of its words) → keep;
      - another option clearly better supported (≥ 60%, 0.2 ahead of the
        rest) → that option becomes the answer (noted in the checks);
      - otherwise the question is dropped.
    RETURNS (answer index or None to drop, note or None).
    """
    sup = [_support(o, source) for o in opts]
    if sup[ans] is None or sup[ans] >= 0.5:
        return ans, None
    others = sorted(((s, i) for i, s in enumerate(sup) if i != ans and s is not None), reverse=True)
    if others and others[0][0] >= 0.6 and (len(others) == 1 or others[0][0] - others[1][0] >= 0.2):
        return others[0][1], f"quiz answer corrected to \"{opts[others[0][1]][:40]}\""
    return None, f"quiz question dropped: answer \"{opts[ans][:40]}\" not supported by its source"


def _verify(plan: dict, ck: Checker, valid_cites: set[int], cite_texts: dict[int, str] | None = None) -> dict:
    steps = []
    for st in (plan.get("steps") or [])[:MAX_STEPS]:
        if not isinstance(st, dict):
            continue
        title = _s(st.get("title"), 80)
        if not title or not ck.ok_label(title):
            continue
        text = ck.clean_text(st.get("text"))
        visual = _verify_visual(st.get("visual"), ck)
        if not text and not visual:
            continue
        cites = sorted({int(c) for c in (st.get("cites") or []) if str(c).isdigit() and int(c) in valid_cites})
        steps.append({"title": title, "text": text, "cites": cites, "visual": visual})
    quiz = []
    for q in (plan.get("quiz") or [])[:MAX_QUIZ]:
        if not isinstance(q, dict):
            continue
        opts = [_s(o, 120) for o in (q.get("options") or [])][:4]
        ans = q.get("answer")
        question = _s(q.get("q"), 200)
        # Only the question and the CORRECT answer must come from the sources:
        # the wrong options are wrong on purpose (e.g. a different event ID).
        if (len(opts) >= 2 and len(set(opts)) == len(opts) and isinstance(ans, int)
                and 0 <= ans < len(opts) and question
                and ck.ok_label(question) and ck.ok_label(opts[ans])):
            cite = q.get("cite")
            source = (cite_texts or {}).get(cite) if isinstance(cite, int) else None
            ans, note = _check_answer(opts, ans, source or ck.corpus)
            if note:
                ck.removed.append(note)
            if ans is None:
                continue
            quiz.append({"q": question, "options": opts, "answer": ans,
                         "cite": cite if isinstance(cite, int) and cite in valid_cites else None})
    return {"steps": steps, "quiz": quiz}


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def build_lesson(topic_id: int, model: str) -> bool:
    """
    Design, calculate, verify and save one topic's lesson. RETURNS True if a
    lesson with at least one step was saved. If the AI's plan can't be used,
    the lesson is built from the calculated blocks alone (if any) — never
    from unverified text.
    """
    mat = _material(topic_id)
    if not mat or not mat["points"]:
        return False
    texts = [p["text"] for p in mat["points"]]
    table_text = [" ".join(" ".join(r) for r in tb["rows"]) for tb in mat["tables"]]
    prof = profile(texts + table_text, mat["tables"])
    ck = Checker(texts + table_text)

    plan = _plan(mat, prof, model) or {}
    by_id = {p["passage_id"]: p["text"] for p in mat["points"]}
    cite_texts = {int(k): by_id.get(v, "") for k, v in mat["citations"].items()}
    lesson = _verify(plan, ck, {int(k) for k in mat["citations"]}, cite_texts)
    lesson["steps"] += _calculated_steps(mat, prof)
    if not lesson["steps"]:
        return False
    lesson["profile"] = prof
    lesson["citations"] = mat["citations"]
    checks = {"removed": ck.removed, "removed_count": len(ck.removed),
              "ai_plan_used": bool(plan)}
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO lessons(topic_id, spec_json, checks_json, model_used) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(topic_id) DO UPDATE SET spec_json = excluded.spec_json, "
            "checks_json = excluded.checks_json, model_used = excluded.model_used, created_at = datetime('now')",
            (topic_id, json.dumps(lesson, ensure_ascii=False), json.dumps(checks), model),
        )
    # Phase 5: refresh this lesson's flashcards (progress is kept by card_key).
    try:
        from . import learn  # late import: learn reads lessons, not the other way round
        learn.sync_cards()
    except Exception:
        pass  # cards are re-synced when the Learn screen opens anyway
    return True


def get_lesson(topic_id: int) -> dict | None:
    """The saved lesson with its check results, or None."""
    with db.connect() as conn:
        r = conn.execute("SELECT spec_json, checks_json, model_used, created_at FROM lessons WHERE topic_id = ?",
                         (topic_id,)).fetchone()
        if not r:
            return None
        lesson = json.loads(r["spec_json"])
        # Map each citation to its current repeat group (the "point" id the
        # Topics screen shows), exactly like distill.topic_detail does for
        # articles, so a source chip opens the right point in the side panel.
        mapped = {}
        for marker, pid in (lesson.get("citations") or {}).items():
            row = conn.execute("SELECT cluster_id FROM passages WHERE id = ?", (pid,)).fetchone()
            if row:
                mapped[marker] = row["cluster_id"] or pid
        lesson["citations"] = mapped
    return {"lesson": lesson, "checks": json.loads(r["checks_json"] or "{}"),
            "model_used": r["model_used"], "created_at": r["created_at"]}
