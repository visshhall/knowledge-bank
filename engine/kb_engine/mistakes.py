"""
mistakes.py — v0.17 learn from mistakes: log them, find the patterns, turn patterns into lessons, check they worked.

WHAT:  1. LOG. Every time an answer goes wrong the app records it (mistake_log): thumbs-down, Regenerate,
          a Correct (his rewritten version is kept next to the model's original), or claims the fact-checker
          removed from a library answer. Nothing is asked of him.
       2. FIND PATTERNS. Two ways, both automatic:
          a) By counting (no AI): from his corrections it measures what he keeps changing — answers too long
             or too short, bullet lists he turns into prose (or the reverse), opening pleasantries he deletes
             ("Certainly!"), closing offers he deletes ("Let me know if…"). A habit seen in at least
             MIN_PATTERN of his corrections becomes a lesson.
          b) With the AI: every few new mistakes the model reads them together and writes general lessons
             ("Give the command first, then explain it") — only lessons that several mistakes support (or
             one correction of his), never about a single fact.
       3. APPLY. Active lessons are added to the instructions of every reply in their scope (block()). A
          lesson is a short imperative sentence; at most MAX_ACTIVE are active, MAX_BLOCK_CHARS are sent.
       4. CHECK. After enough new answers (MIN_AFTER) each lesson is judged: if the share of bad answers in
          its scope dropped to 70% of what it was before, it is "working"; if it did not drop, it is
          "not helping" and is switched off by the app (he can switch it back on). So the app does not keep
          instructions that make no difference — or make things worse.
WHY:   The owner asked the app to identify its problems, learn from them, correct itself and not repeat
       mistakes. A local model cannot rewrite itself, but it can be given better standing instructions, and
       the app can measure whether those instructions helped. Lessons apply automatically (his choice) and
       every one is visible in Learning with its evidence, with an off switch and delete.
WHEN:  log_*() are called when he reacts to an answer (training.py) and when a reply is saved (chat.py);
       maybe_run() starts pattern-finding in the background when enough new mistakes have piled up;
       block() runs for every reply; evaluate() whenever Learning is opened and after each new mistake.
CONNECTED TO: db.py (mistake_log, lesson_rules — schema v19), training.py (logs down/regen/correct),
       chat.py (logs removed facts; adds block() to the instructions; passes answers to on_undo),
       ollama_client.py (the pattern-finding AI call), server.py (/lessons/*), Learning.jsx (the screen).
"""
from __future__ import annotations

import json
import re
import statistics
import threading
import time

from . import db, ollama_client

KINDS = ("down", "regen", "correct", "removed")
SCOPES = ("free", "library", "both", "all")
MIN_PATTERN = 3            # corrections needed before counting-based patterns are trusted
PATTERN_SHARE = 0.6        # share of corrections showing the habit
MAX_ACTIVE = 12            # lessons switched on at once
MAX_LESSON_CHARS = 170
MAX_BLOCK_CHARS = 900      # what is added to a reply's instructions
DISTILL_AT = 5             # new unassigned mistakes that start an AI pattern search
COOLDOWN_SECONDS = 600     # between AI pattern searches
MIN_AFTER = 10             # answers after a lesson before it is judged
MODEL_SAMPLE = 14          # mistakes shown to the model at once
SIMILAR = 0.55             # word overlap above which a new lesson counts as an existing one

_lock = threading.Lock()
_running = False
_last_run = 0.0

OPENERS = ("certainly", "sure", "absolutely", "great question", "of course", "i'd be happy", "i would be happy", "happy to help")
CLOSERS = ("let me know if", "i hope this helps", "feel free to", "don't hesitate", "if you need anything", "hope that helps")


def enabled() -> bool:
    return bool(db.get_setting("lessons_on", True))


def set_enabled(on: bool) -> dict:
    db.set_setting("lessons_on", bool(on))
    return {"ok": True, "on": bool(on)}


# ---------------------------------------------------------------------------
# 1. The log
# ---------------------------------------------------------------------------

def _cut(text, n) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def log_raw(kind: str, chat_id, message_id, mode, question, answer, detail="") -> None:
    """Record one mistake (the same message and kind only once). Never raises: logging must not break a chat."""
    try:
        if kind not in KINDS:
            return
        with db.connect() as conn:
            if message_id and conn.execute("SELECT 1 FROM mistake_log WHERE message_id = ? AND kind = ?",
                                           (message_id, kind)).fetchone():
                return
            conn.execute("INSERT INTO mistake_log(kind, chat_id, message_id, mode, question, answer, detail) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (kind, chat_id, message_id, mode, _cut(question, 400), _cut(answer, 900), _cut(detail, 900)))
        maybe_run()
    except Exception:
        pass


def log_message(kind: str, message_id: int, detail: str = "") -> None:
    """Record a mistake about a message that still exists (looks up its question, answer and mode)."""
    try:
        with db.connect() as conn:
            m = conn.execute("SELECT id, chat_id, content, mode FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
            q = conn.execute("SELECT content FROM chat_messages WHERE chat_id = ? AND id < ? AND role = 'user' "
                             "ORDER BY id DESC LIMIT 1", (m["chat_id"], m["id"])).fetchone() if m else None
        if m:
            log_raw(kind, m["chat_id"], m["id"], m["mode"], q["content"] if q else "", m["content"], detail)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 2a. Patterns by counting (no AI)
# ---------------------------------------------------------------------------

def _has_bullets(text: str) -> bool:
    return len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+", text or "", re.M)) >= 2


def _starts(text: str, words) -> bool:
    return (text or "").strip().lower().lstrip("*#> _-").startswith(words)


def _ends(text: str, phrases) -> bool:
    tail = (text or "").strip().lower()[-160:]
    return any(p in tail for p in phrases)


def count_patterns(rows: list[dict]) -> list[dict]:
    """
    Habits in how he rewrites answers. `rows` = corrections with `answer` (the model's) and `detail` (his).
    RETURNS [{"key", "text", "scope", "evidence"}]; empty below MIN_PATTERN corrections.
    """
    rows = [r for r in rows if r.get("answer") and r.get("detail")]
    n = len(rows)
    if n < MIN_PATTERN:
        return []
    need = max(MIN_PATTERN, round(n * PATTERN_SHARE))
    found: list[dict] = []

    def add(key, text, evidence):
        found.append({"key": key, "text": text, "scope": "free", "evidence": evidence})

    ratios = [len(r["detail"]) / max(1, len(r["answer"])) for r in rows]
    med = statistics.median(ratios)
    if med <= 0.7 and sum(x < 0.85 for x in ratios) >= need:
        add("len-short", "Keep answers short and to the point; cut filler and repetition.", sum(x < 0.85 for x in ratios))
    elif med >= 1.4 and sum(x > 1.2 for x in ratios) >= need:
        add("len-long", "Give fuller answers with concrete detail and examples.", sum(x > 1.2 for x in ratios))
    drop = sum(_has_bullets(r["answer"]) and not _has_bullets(r["detail"]) for r in rows)
    if drop >= need:
        add("bullets-off", "Write in plain prose; avoid bullet lists and headings unless he asks for a list.", drop)
    gain = sum(not _has_bullets(r["answer"]) and _has_bullets(r["detail"]) for r in rows)
    if gain >= need:
        add("bullets-on", "Use short bullet lists for steps and options.", gain)
    op = sum(_starts(r["answer"], OPENERS) and not _starts(r["detail"], OPENERS) for r in rows)
    if op >= need:
        add("no-opener", "Start directly with the answer; no opening pleasantries like “Certainly!”.", op)
    cl = sum(_ends(r["answer"], CLOSERS) and not _ends(r["detail"], CLOSERS) for r in rows)
    if cl >= need:
        add("no-closer", "End when the answer is complete; no closing offers like “let me know if…”.", cl)
    return found


# ---------------------------------------------------------------------------
# Lessons: storing, applying, checking
# ---------------------------------------------------------------------------

def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(w) > 2}


def _similar(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= SIMILAR


def _baseline(conn, scope: str) -> float | None:
    """Share of recent answers in this scope that went wrong (None when there are too few answers to say)."""
    modes = _modes(scope)
    q = ",".join("?" * len(modes))
    answers = conn.execute(f"SELECT COUNT(*) FROM chat_messages WHERE role = 'assistant' AND mode IN ({q}) "
                           "AND created_at >= datetime('now', '-30 days')", modes).fetchone()[0]
    bad = conn.execute(f"SELECT COUNT(*) FROM mistake_log WHERE mode IN ({q}) AND created_at >= datetime('now', '-30 days')",
                       modes).fetchone()[0]
    return round(bad / answers, 4) if answers >= 5 else None


def _modes(scope: str) -> list[str]:
    return {"free": ["free"], "library": ["library", "both"], "both": ["both"], "all": ["free", "library", "both"]}[scope]


def add_rule(text: str, scope: str, source: str, key: str | None, evidence: int, mistake_ids: list[int]) -> int | None:
    """
    Store a lesson (or strengthen a very similar one). RETURNS the rule id, or None when it was not stored.
    Past MAX_ACTIVE lessons the one with the least evidence is switched off to make room.
    """
    text = " ".join((text or "").split()).strip(" \"'-")
    if scope not in SCOPES or not (8 <= len(text) <= MAX_LESSON_CHARS):
        return None
    with db.connect() as conn:
        rows = conn.execute("SELECT id, text, key, evidence FROM lesson_rules").fetchall()
        for r in rows:
            if (key and r["key"] == key) or _similar(r["text"], text):
                conn.execute("UPDATE lesson_rules SET evidence = MAX(evidence, ?) + ? WHERE id = ?",
                             (evidence, len(mistake_ids), r["id"]))
                _assign(conn, mistake_ids, r["id"])
                return r["id"]
        rid = conn.execute("INSERT INTO lesson_rules(text, scope, source, key, evidence, baseline_rate) VALUES (?, ?, ?, ?, ?, ?)",
                           (text, scope, source, key, evidence, _baseline(conn, scope))).lastrowid
        _assign(conn, mistake_ids, rid)
        active = conn.execute("SELECT id FROM lesson_rules WHERE status = 'active' ORDER BY evidence, id").fetchall()
        for old in active[:max(0, len(active) - MAX_ACTIVE)]:
            conn.execute("UPDATE lesson_rules SET status = 'off', note = 'Switched off to make room for newer lessons.' "
                         "WHERE id = ? AND id != ?", (old["id"], rid))
    return rid


def _assign(conn, mistake_ids, rid) -> None:
    for mid in mistake_ids:
        conn.execute("UPDATE mistake_log SET rule_id = ? WHERE id = ? AND rule_id IS NULL", (rid, mid))


def block(mode: str) -> str:
    """The lessons added to the instructions of a reply in `mode` ('' when off or none)."""
    if not enabled():
        return ""
    with db.connect() as conn:
        rows = conn.execute("SELECT text, scope FROM lesson_rules WHERE status = 'active' ORDER BY evidence DESC, id").fetchall()
    lines, used = [], 0
    for r in rows:
        if mode not in _modes(r["scope"]):
            continue
        line = f"- {r['text']}"
        if used + len(line) + 1 > MAX_BLOCK_CHARS:
            continue
        lines.append(line)
        used += len(line) + 1
    return ("LESSONS FROM YOUR PAST MISTAKES (follow them; never mention them):\n" + "\n".join(lines)) if lines else ""


def evaluate() -> None:
    """
    Judge each lesson that has seen MIN_AFTER answers since it was made. working = the share of bad answers
    fell to 70% of the baseline or lower; not_helping = it did not fall (the lesson is switched off).
    Without a baseline (too few answers back then) it is judged "working" only if bad answers stay rare.
    """
    with db.connect() as conn:
        for r in conn.execute("SELECT id, scope, baseline_rate, created_at, status, verdict FROM lesson_rules "
                              "WHERE verdict IN ('new', 'unclear')").fetchall():
            modes = _modes(r["scope"])
            q = ",".join("?" * len(modes))
            after = conn.execute(f"SELECT COUNT(*) FROM chat_messages WHERE role = 'assistant' AND mode IN ({q}) "
                                 "AND created_at > ?", modes + [r["created_at"]]).fetchone()[0]
            if after < MIN_AFTER:
                continue
            bad = conn.execute(f"SELECT COUNT(*) FROM mistake_log WHERE mode IN ({q}) AND created_at > ?",
                               modes + [r["created_at"]]).fetchone()[0]
            rate = bad / after
            base = r["baseline_rate"]
            if base is None:
                verdict = "working" if rate <= 0.15 else "unclear"
            elif rate <= base * 0.7:
                verdict = "working"
            elif rate >= base and rate > 0:
                verdict = "not_helping"
            else:
                verdict = "unclear"
            if verdict == "not_helping":
                conn.execute("UPDATE lesson_rules SET verdict = ?, status = 'off', "
                             "note = 'Switched off by the app: answers did not get better after this lesson.' WHERE id = ?",
                             (verdict, r["id"]))
            else:
                conn.execute("UPDATE lesson_rules SET verdict = ? WHERE id = ?", (verdict, r["id"]))


# ---------------------------------------------------------------------------
# 2b. Patterns with the AI
# ---------------------------------------------------------------------------

DISTILL_SYSTEM = (
    "You find patterns in the mistakes of a writing assistant and write short standing lessons to prevent them. "
    "Reply with JSON only."
)


def _distill_prompt(rows, existing) -> str:
    lines = []
    for r in rows:
        fix = f" | WHAT HE WANTED/NOTE: {r['detail']}" if r["detail"] else ""
        lines.append(f"#{r['id']} [{r['kind']}, {r['mode']}] QUESTION: {r['question']} | ANSWER: {_cut(r['answer'], 400)}{fix}")
    return ("LESSONS ALREADY KNOWN (do not repeat them, even in other words):\n"
            + ("\n".join(f"- {t}" for t in existing) if existing else "(none yet)")
            + "\n\nMISTAKES (kinds: down = he marked it bad, regen = he asked again, correct = he rewrote it, "
              "removed = the fact-checker removed unsupported claims):\n" + "\n".join(lines)
            + "\n\nWrite at most 3 NEW lessons. Each must be a general, imperative instruction (max 160 characters) about "
              "HOW to answer — style, structure, checking, what to avoid — never about one topic or one fact. A lesson needs "
              "support from at least 2 mistakes, or from 1 mistake of kind 'correct'. scope is one of free, library, both, all "
              "(where the mistakes happened). If there is no clear pattern return {\"lessons\": []}.\n"
              'Format: {"lessons": [{"text": "...", "scope": "free", "mistakes": [12, 15]}]}')


def parse_lessons(text: str, valid_ids: dict[int, str]) -> list[dict]:
    """
    The model's reply → [{"text", "scope", "ids"}]. Tolerates a code fence or chatter around the JSON. Drops
    lessons without enough support or with text that is too short/long.
    `valid_ids` maps each mistake id shown to the model to its kind.
    """
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(0)).get("lessons", [])
    except (ValueError, AttributeError):
        return []
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        ids = [int(i) for i in it.get("mistakes", []) if isinstance(i, int) and i in valid_ids]
        corrected = any(valid_ids[i] == "correct" for i in ids)
        if len(set(ids)) < 2 and not corrected:
            continue
        text_ = " ".join(str(it.get("text", "")).split())
        scope = it.get("scope") if it.get("scope") in SCOPES else "all"
        if 8 <= len(text_) <= MAX_LESSON_CHARS:
            out.append({"text": text_, "scope": scope, "ids": sorted(set(ids))})
    return out[:3]


def run_patterns(use_model: bool = True) -> dict:
    """
    Find patterns now: counting first (always), then the AI over mistakes that have no lesson yet.
    RETURNS {"ok", "new_lessons": n, "message"}.
    """
    global _running, _last_run
    with _lock:
        if _running:
            return {"ok": False, "message": "Already looking for patterns."}
        _running = True
    made = 0
    try:
        with db.connect() as conn:
            corr = [dict(r) for r in conn.execute("SELECT id, answer, detail FROM mistake_log WHERE kind = 'correct' "
                                                  "AND created_at >= datetime('now', '-90 days')")]
        for p in count_patterns(corr):
            ids = [r["id"] for r in corr]
            before = _rule_count()
            add_rule(p["text"], p["scope"], "pattern", p["key"], p["evidence"], ids)
            made += _rule_count() - before
        if use_model:
            made += _distill_with_model()
        _last_run = time.time()
        evaluate()
        return {"ok": True, "new_lessons": made,
                "message": f"Found {made} new lesson{'s' if made != 1 else ''}." if made else "No new patterns yet."}
    except Exception as exc:
        return {"ok": False, "message": f"Pattern search stopped: {exc}"}
    finally:
        with _lock:
            _running = False


def _rule_count() -> int:
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM lesson_rules").fetchone()[0]


def _distill_with_model() -> int:
    from . import chat  # late: chat imports this module
    if chat.status().get("state") == "running" or not ollama_client.is_running():
        return 0  # never compete with a reply being written; try again later
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM mistake_log WHERE rule_id IS NULL ORDER BY id DESC LIMIT ?",
                                              (MODEL_SAMPLE,))]
        existing = [r["text"] for r in conn.execute("SELECT text FROM lesson_rules ORDER BY id DESC LIMIT 30")]
    if len(rows) < 2 and not any(r["kind"] == "correct" for r in rows):
        return 0
    rows.reverse()
    r = ollama_client.generate(chat.chat_model(), _distill_prompt(rows, existing), system=DISTILL_SYSTEM,
                               temperature=0.1, num_ctx=4096, num_predict=500)
    made = 0
    valid = {x["id"]: x["kind"] for x in rows}
    for les in parse_lessons(r.text, valid):
        before = _rule_count()
        add_rule(les["text"], les["scope"], "model", None, len(les["ids"]), les["ids"])
        made += _rule_count() - before
    return made


def maybe_run() -> None:
    """After a new mistake: start a pattern search in the background when enough have piled up."""
    if not enabled():
        return
    with db.connect() as conn:
        waiting = conn.execute("SELECT COUNT(*) FROM mistake_log WHERE rule_id IS NULL").fetchone()[0]
        corrections = conn.execute("SELECT COUNT(*) FROM mistake_log WHERE rule_id IS NULL AND kind = 'correct'").fetchone()[0]
    if waiting < DISTILL_AT and not corrections:
        evaluate()
        return
    if time.time() - _last_run < COOLDOWN_SECONDS or _running:
        return
    threading.Thread(target=run_patterns, name="kb-lessons", daemon=True).start()


# ---------------------------------------------------------------------------
# For the Learning screen
# ---------------------------------------------------------------------------

def status() -> dict:
    evaluate()
    with db.connect() as conn:
        rules = [dict(r) for r in conn.execute(
            "SELECT id, text, scope, source, status, evidence, verdict, note, created_at FROM lesson_rules "
            "ORDER BY (status = 'active') DESC, evidence DESC, id DESC")]
        counts = {r["kind"]: r["n"] for r in conn.execute("SELECT kind, COUNT(*) AS n FROM mistake_log GROUP BY kind")}
        recent = [dict(r) for r in conn.execute("SELECT id, kind, mode, question, detail, rule_id, created_at FROM mistake_log "
                                                "ORDER BY id DESC LIMIT 12")]
    return {"on": enabled(), "rules": rules, "counts": {k: counts.get(k, 0) for k in KINDS},
            "total": sum(counts.values()), "recent": recent, "running": _running,
            "active": sum(1 for r in rules if r["status"] == "active")}


def set_rule(rule_id: int, on: bool) -> dict:
    """
    Switch a lesson on or off. Switching ON starts it fresh: its clock and baseline are reset, so it is judged
    again over answers written from now on (otherwise a lesson the app switched off would be switched off again
    at once, from the old answers).
    """
    with db.connect() as conn:
        r = conn.execute("SELECT scope FROM lesson_rules WHERE id = ?", (rule_id,)).fetchone()
        if not r:
            return {"ok": False}
        if on:
            conn.execute("UPDATE lesson_rules SET status = 'active', note = NULL, verdict = 'new', "
                         "created_at = datetime('now', '+1 second'), baseline_rate = ? WHERE id = ?",
                         (_baseline(conn, r["scope"]), rule_id))
        else:
            conn.execute("UPDATE lesson_rules SET status = 'off', note = NULL WHERE id = ?", (rule_id,))
    return {"ok": True}


def delete_rule(rule_id: int) -> dict:
    with db.connect() as conn:
        conn.execute("UPDATE mistake_log SET rule_id = NULL WHERE rule_id = ?", (rule_id,))
        n = conn.execute("DELETE FROM lesson_rules WHERE id = ?", (rule_id,)).rowcount
    return {"ok": bool(n)}
