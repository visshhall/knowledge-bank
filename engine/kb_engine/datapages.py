"""
datapages.py — spreadsheets become their own topic, instantly, with a lesson
calculated from the data (no AI, so nothing can be made up).

WHAT:  ensure_data_topic(source_id) → one topic per spreadsheet file
         (topics.kind = 'data', schema v8), created the moment the file is
         imported, holding all of its passages. Its "article" and lesson are
         built by code from the exact cells:
           - What's inside: every sheet, its size, what was found in it.
           - Charts: number series found in the sheet (e.g. Hosts by CIDR),
             drawn as interactive charts; log scale when values span many
             orders of magnitude.
           - Patterns: halving/doubling/steps found by arithmetic.
           - Subnet data (CIDR "/n" labels detected): a check of every value
             against the formula (addresses = 2^(32 − n), last mask octet =
             256 − 2^(32 − n) for /25–/32), the bits explainer and the
             interactive Subnet Lab, plus quiz questions whose answers come
             from your own sheet.
           - The exact tables, cell for cell.
       rebuild_data_topics() → recreate all of them (after "Rebuild topics",
         which replaces every topic) and remove ones whose file was removed.
WHY:   v0.7 placed spreadsheet rows into whichever subject topic their
       meaning was closest to — a subnet sheet has nothing in common with
       "Credential theft" — and only when the AI engine was running, so the
       owner's Subnet-Guide.xlsx showed up nowhere (owner report, 14 Nov).
       Numbers need calculation, not language models.
WHEN:  importer.py after a spreadsheet is read; distill.py after topics are
       rebuilt; importer.remove after a file is removed.
CONNECTED TO: db.py (topics.kind, topic_passages, lessons, doc_tables,
       sources), lessons.py (_patterns; lesson format), learn.sync_cards
       (quiz → flashcards), Diagrams.jsx (chart, subnetlab, verify visuals).
"""

from __future__ import annotations

import json
import re

from . import db

CIDR_LABEL = re.compile(r"^/(\d{1,2})$")


def _num(cell: str) -> float | None:
    s = str(cell).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Finding series in a sheet
# ---------------------------------------------------------------------------

def _row_series(rows: list[list[str]]) -> list[dict]:
    """
    Row-oriented series: a row whose first filled cell is a label followed by
    3+ values ("CIDR | /1 | /2 …", "Hosts | 2147483648 | …"). A numeric row
    is paired with the nearest label row of the same length just above it
    (within 3 rows), so blocks like the subnet sheet's 4 blocks of 8 line up.
    Series with the same (x label, y label) across blocks are joined.
    RETURNS [{"x_label", "y_label", "x": [...], "y": [...]}].
    """
    parsed = []
    for i, row in enumerate(rows):
        cells = [str(c).strip() for c in row]
        filled = [(j, c) for j, c in enumerate(cells) if c]
        if len(filled) < 4:
            continue
        label = filled[0][1]
        values = [c for _j, c in filled[1:]]
        if _num(label) is not None:
            continue
        numeric = sum(_num(v) is not None for v in values)
        parsed.append({"i": i, "label": label.rstrip(":"), "values": values,
                       "numeric": numeric == len(values)})
    out: dict[tuple, dict] = {}
    for p in parsed:
        if not p["numeric"]:
            continue
        xs = next((q for q in reversed(parsed) if q["i"] < p["i"] and p["i"] - q["i"] <= 3
                   and not q["numeric"] and len(q["values"]) == len(p["values"])), None)
        key = (xs["label"] if xs else "#", p["label"])
        s = out.setdefault(key, {"x_label": key[0], "y_label": key[1], "x": [], "y": []})
        s["x"] += xs["values"] if xs else [str(len(s["x"]) + k + 1) for k in range(len(p["values"]))]
        s["y"] += [_num(v) for v in p["values"]]
    return [s for s in out.values() if len(s["y"]) >= 4]


def _column_series(rows: list[list[str]]) -> list[dict]:
    """
    Column-oriented series (an ordinary table): a header row, then rows; the
    first text column gives x, each fully numeric column gives a series.
    """
    rows = [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if len(rows) < 4:
        return []
    head = rows[0]
    body = rows[1:]
    width = len(head)
    out = []
    xcol = next((j for j in range(width) if any(_num(r[j] if j < len(r) else "") is None and (r[j] if j < len(r) else "")
                                                 for r in body)), None)
    for j in range(width):
        col = [r[j] if j < len(r) else "" for r in body]
        if j == xcol or not head[j] or not all(_num(c) is not None for c in col if c) or sum(bool(c) for c in col) < 3:
            continue
        pts = [(r[xcol] if xcol is not None and xcol < len(r) else str(k + 1), _num(c))
               for k, (r, c) in enumerate(zip(body, col)) if c]
        out.append({"x_label": head[xcol] if xcol is not None else "#", "y_label": head[j],
                    "x": [p[0] for p in pts], "y": [p[1] for p in pts]})
    return out


def _describe(y: list[float]) -> list[str]:
    """Plain-language patterns in a number series (exact arithmetic only)."""
    notes = []
    ratios = {round(b / a, 6) for a, b in zip(y, y[1:]) if a}
    if len(ratios) == 1:
        r = ratios.pop()
        if r == 0.5:
            notes.append("Each step halves the value.")
        elif r == 2:
            notes.append("Each step doubles the value.")
        elif r != 1:
            notes.append(f"Each step multiplies the value by {r:g}.")
    diffs = {round(b - a, 6) for a, b in zip(y, y[1:])}
    if len(diffs) == 1 and not notes:
        notes.append(f"Each step changes the value by {diffs.pop():+g}.")
    if all(v >= 1 and float(v).is_integer() and (int(v) & (int(v) - 1)) == 0 for v in y):
        notes.append("Every value is a power of 2.")
    if y and min(y) > 0 and max(y) / min(y) >= 1000:
        notes.append(f"Values range from {min(y):,.0f} to {max(y):,.0f} — a log scale shows all of them clearly.")
    return notes


# ---------------------------------------------------------------------------
# Subnet knowledge (exact formulas)
# ---------------------------------------------------------------------------

def _cidr_checks(series: list[dict]) -> list[dict]:
    """
    For every series indexed by CIDR labels, compare each value with the
    formula. RETURNS [{"rows": table rows, "ok": n, "wrong": [...], "rule", "series"}].
    """
    found = []
    for s in series:
        cidrs = [CIDR_LABEL.match(x) for x in s["x"]]
        if sum(bool(m) for m in cidrs) < 4:
            continue
        label = s["y_label"].lower()
        rows = [["CIDR", f"Your sheet ({s['y_label']})", "Calculated", "Match"]]
        ok, wrong = 0, []
        for m, val in zip(cidrs, s["y"]):
            if not m:
                continue
            n = int(m.group(1))
            if "mask" in label:
                if n < 25:  # this row only holds the changing (last) octet for /25–/32
                    continue
                calc, rule = 256 - 2 ** (32 - n), "last mask octet = 256 − 2^(32 − n)"
            else:
                calc, rule = 2 ** (32 - n), "addresses = 2^(32 − n)"
            good = val is not None and abs(val - calc) < 0.5
            ok += good
            if not good:
                wrong.append(f"/{n}")
            rows.append([f"/{n}", f"{val:,.0f}" if val is not None else "—", f"{calc:,}", "✓" if good else "✗"])
        if len(rows) > 1:
            found.append({"rows": rows, "ok": ok, "wrong": wrong, "rule": rule, "series": s["y_label"]})
    return found


def _host_map(series: list[dict]) -> dict:
    """CIDR → value from the owner's sheet (the Subnet Lab shows "your sheet says …")."""
    for s in series:
        if "host" in s["y_label"].lower():
            out = {}
            for x, v in zip(s["x"], s["y"]):
                m = CIDR_LABEL.match(x)
                if m and v is not None:
                    out[int(m.group(1))] = v
            if out:
                return out
    return {}


# ---------------------------------------------------------------------------
# Building the page
# ---------------------------------------------------------------------------

def build(source_id: int) -> dict | None:
    """Compute the lesson + article for one spreadsheet. RETURNS {lesson, article, title}."""
    from .lessons import _patterns  # shared pattern finder for raw tables

    with db.connect() as conn:
        src = conn.execute("SELECT id, file_name FROM sources WHERE id = ?", (source_id,)).fetchone()
        tables = conn.execute("SELECT name, rows_json FROM doc_tables WHERE source_id = ? ORDER BY page_number, id",
                              (source_id,)).fetchall()
    if not src or not tables:
        return None
    sheets = [{"name": t["name"], "rows": json.loads(t["rows_json"])} for t in tables]
    all_series, steps, quiz, md_patterns = [], [], [], []
    overview_items = []
    for sh in sheets:
        rows = [r for r in sh["rows"] if any(str(c).strip() for c in r)]
        series = _row_series(rows) or _column_series(rows)
        all_series += series
        width = max((len(r) for r in rows), default=0)
        found = ", ".join(f"{s['y_label']} by {s['x_label']}" for s in series[:3]) or "a table of values"
        overview_items.append({"label": sh["name"], "detail": f"{len(rows)} rows × {width} columns · {found}"})

    fname = src["file_name"]
    steps.append({"title": f"What's in {fname}", "computed": True, "cites": [],
                  "text": f"{len(sheets)} sheet{'s' if len(sheets) != 1 else ''}. Everything on this page is "
                          f"calculated from your cells — no AI is involved, so nothing is guessed.",
                  "visual": {"type": "cards", "items": overview_items}})

    checks = _cidr_checks(all_series)
    sheet_text = " ".join(" ".join(str(c) for c in r) for sh in sheets for r in sh["rows"]).lower()
    for s in all_series[:4]:
        notes = _describe([v for v in s["y"] if v is not None])
        md_patterns += [f"**{s['y_label']} by {s['x_label']}:** {n}" for n in notes]
        is_cidr = sum(bool(CIDR_LABEL.match(x)) for x in s["x"]) >= 4
        extra = ""
        if is_cidr and "host" in s["y_label"].lower():
            extra = (" Read it from left to right: every extra network bit (one step to a bigger CIDR "
                     "number) halves the number of addresses in the network.")
            if "double" in sheet_text:
                extra += (" Your sheet's note says hosts double with each CIDR increment — that's true "
                          "reading right to left (/32 → /1); moving to a bigger /n they halve.")
        if is_cidr and "mask" in s["y_label"].lower():
            extra = (" These are the last-octet mask values for /25–/32: each extra network bit adds the "
                     "next bit value (128, 64, 32 …) to the octet. The same values appear in the 2nd and "
                     "3rd octets for /9–/16 and /17–/24.")
        steps.append({
            "title": f"{s['y_label']} by {s['x_label']}", "computed": True, "cites": [],
            "text": (" ".join(notes) + extra).strip() or "The values from your sheet, drawn as a chart.",
            "visual": {"type": "chart", "x": s["x"], "series": [{"name": s["y_label"], "values": s["y"]}],
                       "x_label": s["x_label"], "y_label": s["y_label"],
                       "log": bool(s["y"]) and min(v for v in s["y"] if v) > 0
                              and max(s["y"]) / min(v for v in s["y"] if v) >= 1000},
        })

    subnet = bool(checks) or "subnet" in sheet_text
    for cidr in checks:
        verdict = (f"All {cidr['ok']} values match the formula ({cidr['rule']})." if not cidr["wrong"]
                   else f"{cidr['ok']} values match the formula ({cidr['rule']}); check {', '.join(cidr['wrong'])}.")
        tail = (" Hosts you can actually use are 2 fewer: the first address is the network ID and the last "
                "is the broadcast (/31 and /32 are special cases).") if "addresses" in cidr["rule"] else ""
        steps.append({"title": f"Checking your sheet: {cidr['series']}", "computed": True, "cites": [],
                      "text": verdict + tail,
                      "visual": {"type": "verify", "rows": cidr["rows"], "ok": cidr["ok"], "wrong": cidr["wrong"]}})
        md_patterns.append(f"**Check ({cidr['series']}):** {verdict}")
    if subnet:
        hosts = _host_map(all_series)
        steps.append({"title": "Why “/n” means n network bits", "computed": True, "cites": [],
                      "text": "An IPv4 address is 32 bits in 4 groups of 8. A /n prefix keeps the first n bits "
                              "for the network; the remaining 32 − n bits number the hosts, so a network has "
                              "2^(32 − n) addresses. Press Play to watch the mask build bit by bit.",
                      "visual": {"type": "bits"}})
        steps.append({"title": "Subnet Lab: work out any network", "computed": True, "cites": [],
                      "text": "Type any IP address and pick a prefix. The network, broadcast, usable range and "
                              "mask are calculated live, and the AND of address and mask is shown bit by bit.",
                      "visual": {"type": "subnetlab", "hosts": {str(k): v for k, v in hosts.items()}}})
        # Quiz from the owner's own numbers (correct by construction).
        for n in (26, 20, 29):
            if n in hosts:
                right = int(hosts[n])
                opts = sorted({right, right * 2, right // 2, max(1, right - 2)})
                quiz.append({"q": f"According to your sheet, how many addresses does a /{n} network have?",
                             "options": [f"{o:,}" for o in opts], "answer": opts.index(right), "cite": None})
        for n in (27, 30):
            right = 256 - 2 ** (32 - n)
            opts = sorted({right, 256 - 2 ** (33 - n), min(255, 256 - 2 ** (31 - n)), 255 if right != 255 else 128})
            quiz.append({"q": f"What is the last octet of the subnet mask for /{n}?",
                         "options": [str(o) for o in opts], "answer": opts.index(right), "cite": None})
        quiz.append({"q": "How many usable host addresses does a /24 network have?",
                     "options": ["256", "254", "255", "128"], "answer": 1, "cite": None})

    for sh in sheets:
        rows = [r for r in sh["rows"] if any(str(c).strip() for c in r)]
        steps.append({"title": f"From your spreadsheet: {sh['name']}", "computed": True, "cites": [],
                      "text": f"The exact cells of “{sh['name']}”.",
                      "visual": {"type": "table", "name": sh["name"], "rows": rows[:80], "patterns": _patterns(rows)}})

    lesson = {"steps": steps, "quiz": quiz[:5], "profile": {"data": True, "subnet": subnet}, "citations": {}}
    article = [f"## Overview", f"{fname} has {len(sheets)} sheet{'s' if len(sheets) != 1 else ''}: "
               + ", ".join(f"**{s['name']}**" for s in sheets) + ". This page is calculated from the cells, "
               "not written by AI.", "", "## Key points"]
    article += [f"- {p}" for p in md_patterns] or ["- No number series were found; the exact tables are in the lesson."]
    if subnet:
        article += ["", "## How it works",
                    "1. An IPv4 address has 32 bits; /n keeps n of them for the network.",
                    "2. The other 32 − n bits number the hosts: 2^(32 − n) addresses.",
                    "3. Two of them are reserved (network ID and broadcast), so usable hosts = 2^(32 − n) − 2.",
                    "", "Open the **Lesson** tab for the interactive Subnet Lab and charts."]
    return {"lesson": lesson, "article": "\n".join(article), "title": re.sub(r"\.(xlsx|xlsm|csv)$", "", fname, flags=re.I)}


def ensure_data_topic(source_id: int) -> int | None:
    """Create or refresh the data topic for one spreadsheet. RETURNS the topic id."""
    page = build(source_id)
    if not page:
        return None
    with db.connect() as conn:
        pids = [r[0] for r in conn.execute("SELECT id FROM passages WHERE source_id = ?", (source_id,))]
        if not pids:
            return None
        row = conn.execute("SELECT topic_id FROM topic_passages WHERE passage_id = ?", (pids[0],)).fetchone()
        tid = row[0] if row else None
        kind = conn.execute("SELECT kind FROM topics WHERE id = ?", (tid,)).fetchone() if tid is not None else None
        # Linked to a subject topic, or to a topic that no longer exists (a link
        # left dangling by an interrupted rebuild): unlink and make a fresh one.
        if tid is not None and (kind is None or kind[0] != "data"):
            conn.execute("DELETE FROM topic_passages WHERE topic_id = ? AND passage_id IN (%s)"
                         % ",".join("?" * len(pids)), [tid, *pids])
            tid = None
        if tid is None:
            slug = f"data-{source_id}"
            conn.execute("DELETE FROM topics WHERE slug = ?", (slug,))
            tid = conn.execute(
                "INSERT INTO topics(slug, title, summary, status, kind, body_markdown, model_used, written_at, citations) "
                "VALUES (?, ?, ?, 'written', 'data', ?, 'calculated', datetime('now'), '{}')",
                (slug, page["title"], "Spreadsheet — tables, charts and patterns calculated from your cells.",
                 page["article"])).lastrowid
            conn.execute("DELETE FROM topic_passages WHERE passage_id IN (%s)" % ",".join("?" * len(pids)), pids)
            conn.executemany("INSERT INTO topic_passages(topic_id, passage_id, fit) VALUES (?, ?, 1.0)",
                             [(tid, p) for p in pids])
        else:
            conn.execute("UPDATE topics SET title = ?, body_markdown = ?, status = 'written', "
                         "written_at = datetime('now') WHERE id = ?", (page["title"], page["article"], tid))
        conn.execute(
            "INSERT INTO lessons(topic_id, spec_json, checks_json, model_used) VALUES (?, ?, ?, 'calculated') "
            "ON CONFLICT(topic_id) DO UPDATE SET spec_json = excluded.spec_json, checks_json = excluded.checks_json, "
            "model_used = 'calculated', created_at = datetime('now')",
            (tid, json.dumps(page["lesson"], ensure_ascii=False),
             json.dumps({"removed": [], "removed_count": 0, "calculated": True})))
    try:
        from . import learn
        learn.sync_cards()
    except Exception:
        pass
    return tid


def rebuild_data_topics() -> int:
    """Recreate every spreadsheet's data topic; drop data topics with no file left."""
    with db.connect() as conn:
        sids = [r[0] for r in conn.execute("SELECT id FROM sources WHERE file_type = 'table' AND status = 'extracted'")]
        for r in conn.execute("SELECT t.id FROM topics t WHERE t.kind = 'data' AND NOT EXISTS "
                              "(SELECT 1 FROM topic_passages tp WHERE tp.topic_id = t.id)").fetchall():
            conn.execute("DELETE FROM topics WHERE id = ?", (r[0],))
    return sum(1 for sid in sids if ensure_data_topic(sid))
