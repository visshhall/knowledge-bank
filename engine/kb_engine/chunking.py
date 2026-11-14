"""
chunking.py — cleans page text and cuts it into passages (the bank's basic unit).

WHAT:  clean(text)          → tidy text that KEEPS its structure: bullet
                               lists, query lines and short headings stay on
                               their own lines; only ordinary wrapped prose
                               is joined into paragraphs.
       split_with_sections(text, state) → [(passage, section)] where
                               section is the document part (use case /
                               scenario / chapter heading, else the
                               document's title) the passage belongs to.
                               `state` carries the current part from page to
                               page of one document.
       split_passages(text) → passages of roughly 120–260 words, broken at
                               paragraph/line boundaries, never mid-line
                               where avoidable, never across a page.
       fingerprint(text)    → a hash that is identical for passages whose
                               wording is the same apart from spacing/case/
                               punctuation.
       CHUNKER_VERSION      → bumped whenever the rules change, so existing
                               banks are re-organised automatically
                               (importer.rechunk_all).

WHY:   - Search results, merging and citations all work on passages: big
         enough for one idea, small enough to point at something specific.
       - v2 (KB v0.5) change: the first version joined every line into one
         long paragraph. PDFs extract bullets ("• T1574.002 – …") and KQL
         queries ("Sysmon | where EventID == 7 | where …") as plain lines, so
         they became unreadable walls of text (owner feedback, 14 Nov 2026).
         Now bullets, numbered items, query pipelines and headings keep their
         own lines, and inline bullets / query pipes are split back onto
         separate lines.
       - v3 (KB v0.6.1) change, owner feedback on real PDFs ("no context,
         random Step 3 / Step 5"): Word documents use nested bullets
         "•" → "o" → "§" (Symbol/Wingdings fonts), which extract as the
         plain letters "o" and "§", sometimes alone on their own line. They
         weren't recognised, so sub-points were glued onto the item above.
         Now they become real bullets with their level kept (• / ◦ / ▪),
         typographic ligatures (ﬁ, ﬃ) are expanded, and every passage
         records the document part it belongs to (split_with_sections), so
         "Step 3: Root Cause" is shown under "Use Case 7: …" instead of on
         its own.
       - v5 (KB v0.6.3): tables WITHOUT ruled borders (common in Word SOC
         playbooks: "Step | Action") arrive as "Step", "Action", "1",
         "Terminate…", "2", "Delete…" on separate lines and were joined into
         one run-on sentence. _rebuild_numbered_rows turns them back into
         table rows ("Step · Action", "1 · Terminate…"). Passages now also
         start at a heading when possible, so a section such as "Analyst
         Steps" isn't cut in half across two cards.
       - The fingerprint catches the same paragraph copied into several PDFs
         (same meaning in different words is caught in Phase 2).

WHEN:  Called by importer.py for every page after its text is extracted, and
       by importer.rechunk_all() when CHUNKER_VERSION changes.

CONNECTED TO: importer.py (caller); db.py `passages` table (stores text,
       token_count and content_hash produced here); app/src/Formatted.jsx
       relies on the line structure kept here to display passages nicely.
"""

import hashlib
import re
import unicodedata

CHUNKER_VERSION = 5  # bump when clean()/split_passages() rules change

TARGET_WORDS = 180   # aim for passages about this long
MAX_WORDS = 260      # never longer than this (long blocks get split)
MIN_WORDS = 12       # shorter leftovers are merged into the previous passage

_SPACES = re.compile(r"[ \t ]+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

# A line that starts a list item: •, ●, ▪, ◦, -, *, –, or "1." / "1)" / "a)".
_BULLET = re.compile(r"^\s*(?:[•●▪◦‣∙\-\*–]|\d{1,2}[.)]|[a-z][.)])\s+")
# Word's bullet glyphs. Symbol/Wingdings fonts put them in the private-use
# area or extract them as letters: level 1 "•"/"", level 2 "o", level 3
# "§"/"". They are rewritten to • / ◦ / ▪ so the level survives.
_GLYPH_LEVEL = {"\uf0b7": "•", "\uf0a7": "▪", "\uf076": "•", "\uf0d8": "•", "\uf0fc": "•",
                "\uf0a8": "•", "\uf0e8": "•", "➢": "•", "■": "▪", "Ø": "•", "ü": "•",
                "o": "◦", "§": "▪", "•": "•", "●": "•", "◦": "◦", "▪": "▪"}
# A line that is only a bullet glyph (the text followed on the next line).
_LONE_GLYPH = re.compile(r"^\s*([\uf0b7\uf0a7\uf076\uf0d8\uf0fc\uf0a8\uf0e8➢■Øüo§•●◦▪])\s*$")
# A glyph at the start of a line followed by text. "o"/"§"/"Ø"/"ü" only
# count when a capital letter or quote/path follows ("o On the …", "§ The …")
# so ordinary words and legal "§ 164" references are left alone.
_LEAD_GLYPH = re.compile(r"^\s*(?:([\uf0b7\uf0a7\uf076\uf0d8\uf0fc\uf0a8\uf0e8➢■])\s*|([oØü§])\s+(?=[A-Z\"'“‘(\\]))")
# Level-2/3 glyphs flattened INSIDE a line after a colon/full stop:
# "Endpoint Analysis: o On the user's workstation: § QuickShareApp.exe …"
_INLINE_WORD_BULLET = re.compile(r"(?<=[:.;!?)])\s+([o§])\s+(?=[A-Z\"'“‘(\\])")

# Bullet characters appearing in the MIDDLE of a line (PDFs often flatten lists).
_INLINE_BULLET = re.compile(r"\s+([•●▪◦‣])\s+")
# Query-language pipe steps (KQL / Splunk SPL), e.g. "| where", "| project".
_PIPE_STEP = re.compile(
    r"\s+\|\s*(?=(?:where|project|summarize|extend|join|order|sort|take|top|count|distinct|"
    r"mv-expand|parse|union|render|let|lookup|search|stats|table|eval|rex|dedup|sort)\b)",
    re.IGNORECASE,
)
_CODE_START = re.compile(
    # A pipe step, a "let"/"union"/"search" statement, a Splunk "index=", or a
    # table name standing alone or followed by a pipe ("Sysmon | where …").
    # A table name followed by ordinary words ("Sysmon Event IDs:") is prose.
    r"^\s*(?:\||let\s|union\s|search\s|index=|"
    r"(?:SecurityEvent|SigninLogs|Device\w+Events|AuditLogs|Sysmon|Event)\s*(?:\||$))",
    re.IGNORECASE,
)


_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
                "or", "the", "to", "vs", "via", "with"}


def _is_heading(line: str) -> bool:
    """
    Short line that looks like a title: under ~70 characters, no sentence
    punctuation at the end, and mostly capitalised words (e.g. "Detection
    Logic", "USE CASE 9: DLL SIDELOADING").
    """
    s = line.strip()
    if not (3 <= len(s) <= 70) or s.endswith((".", ",", ";")) or " · " in s:
        return False
    if _BULLET.match(s):  # a list item ("▪ VPN?", "1. Step") is never a heading
        return False
    # A single token with digits ("WINRDP01", "4624") is data, not a title.
    if " " not in s and re.search(r"\d", s):
        return False
    # Small joining words don't count against a title (v0.6.2): "Containment
    # and Response" is a heading even though "and" is lower-case.
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']*", s) if w.lower() not in _SMALL_WORDS]
    if not words:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.7


def _is_structural(line: str) -> bool:
    """
    True for lines that must keep their own line: bullets, code, headings,
    and spreadsheet rows (cells joined by " · " in importer._extract_table).
    The row rule only affects spreadsheets (new in v0.6), so CHUNKER_VERSION
    stays 2 and existing banks aren't re-organised (which would clear topics).
    """
    return (bool(_BULLET.match(line) or _CODE_START.match(line)) or " · " in line
            or _is_heading(line))


def _normalise_bullets(text: str) -> str:
    """
    Turn Word's bullet glyphs into • / ◦ / ▪ (levels 1/2/3), join a bullet
    that sits alone on its line with the text on the next line, and split
    sub-bullets flattened into the middle of a line back onto their own line.
    """
    text = _INLINE_WORD_BULLET.sub(lambda m: "\n" + _GLYPH_LEVEL[m.group(1)] + " ", text)
    out: list[str] = []
    pending = ""
    for line in text.split("\n"):
        lone = _LONE_GLYPH.match(line)
        if lone:
            pending = _GLYPH_LEVEL.get(lone.group(1), "•")
            continue
        m = _LEAD_GLYPH.match(line)
        if m:
            line = _GLYPH_LEVEL.get(m.group(1) or m.group(2), "•") + " " + line[m.end():].lstrip()
        elif pending and line.strip():
            line = f"{pending} {line.strip()}"
        if line.strip():
            pending = ""
        out.append(line)
    return "\n".join(out)


_LONE_NUM = re.compile(r"^\s*(\d{1,2})[.)]?\s*$")            # "3" alone on a line
_NUM_LEAD = re.compile(r"^\s*(\d{1,2})\s+(?=[A-Z])(.+)$")       # "3 Quarantine both…"


def _is_header_cell(line: str) -> bool:
    """A table header cell: 1–3 short capitalised words, no digits/punctuation ("Step", "Action")."""
    s = line.strip()
    return (0 < len(s) <= 25 and len(s.split()) <= 3 and s[0].isupper()
            and not re.search(r"[\d.:;,?!·]", s) and not _BULLET.match(s))


def _rebuild_numbered_rows(text: str) -> str:
    """
    Rebuild a numbered table that PDF extraction flattened.

    Pattern: a run of rows numbered 1, 2, 3 … where each number is alone on
    its line (cell text on the following line(s)) or starts the line
    ("2 Delete the sideloaded DLL"). At least 2 rows are required, numbers
    must be consecutive from 1, and a row's text ends at the next number, a
    heading, a bullet or a blank line. The two short lines right before
    row 1 ("Step", "Action") become the header row.
    RETURNS text with the rows as "1 · Terminate …" (with a header) or
    "1. Terminate …" (without one).
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        rows: list[tuple[int, str]] = []
        j = i
        while j < len(lines):
            expect = len(rows) + 1
            lone, lead = _LONE_NUM.match(lines[j]), _NUM_LEAD.match(lines[j])
            if lone and int(lone.group(1)) == expect:
                cell, k = [], j + 1
            elif lead and int(lead.group(1)) == expect and (rows or j == i):
                cell, k = [lead.group(2).strip()], j + 1
            else:
                break
            while k < len(lines):
                nxt = lines[k].strip()
                if (not nxt or _LONE_NUM.match(nxt) or _BULLET.match(nxt)
                        or (_NUM_LEAD.match(nxt) and int(_NUM_LEAD.match(nxt).group(1)) == expect + 1)
                        or (cell and _is_heading(nxt))
                        or (lead and not nxt[0].islower())):  # "2 Text" rows only wrap in lower case
                    break
                cell.append(nxt)
                k += 1
            if not cell:
                break
            rows.append((expect, " ".join(cell)))
            j = k
            while j < len(lines) and not lines[j].strip() and j + 1 < len(lines) \
                    and _LONE_NUM.match(lines[j + 1]):
                j += 1  # a blank line between rows
        # Lone-number rows are always a table; "1 Text" lines only count when
        # a header sits right above them (otherwise they may be prose).
        # The rows have two columns (number, text), so a header is exactly
        # the two short lines right above row 1 ("Step", "Action").
        header: list[str] = []
        if len(out) >= 2 and _is_header_cell(out[-1]) and _is_header_cell(out[-2]) \
                and len(out[-1].split()) <= 2 and len(out[-2].split()) <= 2:
            header = [out.pop(-2), out.pop()]
        lone_rows = _LONE_NUM.match(lines[i]) is not None
        if len(rows) >= 2 and (lone_rows or len(header) >= 2):
            if len(header) >= 2:
                out.append(" · ".join(h.strip() for h in header))
                out.extend(f"{n} · {t}" for n, t in rows)
            else:
                out.extend(header)
                out.extend(f"{n}. {t}" for n, t in rows)
            i = j
            continue
        out.extend(header)
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def clean(text: str) -> str:
    """
    Tidy raw PDF text while keeping its structure.

    HOW:  1. Normalise line endings; join words hyphenated across lines.
          2. Split inline bullets ("… • T1055 – …") and query pipes
             ("Sysmon | where … | project …") onto their own lines.
          3. Walk the lines: structural lines (bullets, code, headings) stay
             separate; ordinary lines are joined to the previous prose line
             (they were just wrapped by the PDF layout); a blank line ends a
             paragraph.
    RETURNS paragraphs separated by blank lines; structural lines separated
    by single newlines.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text.replace("\u00ad", ""))  # ﬁ→fi, soft hyphens out
    text = _normalise_bullets(text)
    text = _rebuild_numbered_rows(text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = _INLINE_BULLET.sub(r"\n\1 ", text)
    text = "\n".join(_PIPE_STEP.sub("\n| ", line) if "|" in line else line for line in text.split("\n"))

    blocks: list[list[str]] = [[]]
    for raw in text.split("\n"):
        line = _SPACES.sub(" ", raw).strip()
        if not line:
            if blocks[-1]:
                blocks.append([])
            continue
        current = blocks[-1]
        if (current and not _is_structural(line) and not _is_structural(current[-1])
                and not current[-1].endswith(":")):
            current[-1] = f"{current[-1]} {line}"   # wrapped prose → same line
        elif current and not _is_structural(line) and _BULLET.match(current[-1]) \
                and (not line[0].isupper()
                     or not current[-1].rstrip().endswith((".", ":", "?", "!", ";"))):
            # Continuation of a bullet item: the item's text wrapped onto the
            # next line. A capitalised line still continues it when the item
            # hasn't finished its sentence ("…within the Amazon EC2" + "API
            # that can return…") — v0.6.1 fix.
            current[-1] = f"{current[-1]} {line}"
        else:
            current.append(line)
    return "\n\n".join("\n".join(b) for b in blocks if b)


def _words(s: str) -> int:
    return len(s.split())


def split_passages(text: str) -> list[str]:
    """
    Split one page's text into passages, keeping line structure.

    HOW:  Units are blocks (paragraphs / groups of lines). Units are added to
          the current passage until it reaches TARGET_WORDS. A unit larger
          than MAX_WORDS is cut between lines; a single giant line is cut
          between words. A tiny final leftover is merged backwards.
    """
    text = clean(text)
    if not text:
        return []

    # A heading starts a new unit, so a passage can begin at it.
    blocks: list[str] = []
    for block in text.split("\n\n"):
        part: list[str] = []
        for line in block.split("\n"):
            if part and _is_heading(line) and not _is_heading(part[-1]):
                blocks.append("\n".join(part))
                part = []
            part.append(line)
        if part:
            blocks.append("\n".join(part))

    units: list[str] = []
    for block in blocks:
        if _words(block) <= MAX_WORDS:
            units.append(block)
            continue
        part: list[str] = []
        for line in block.split("\n"):
            if _words(line) > MAX_WORDS:                 # one huge line → word slices
                words = line.split()
                for i in range(0, len(words), MAX_WORDS):
                    units.append(" ".join(words[i:i + MAX_WORDS]))
                continue
            if part and _words("\n".join(part + [line])) > MAX_WORDS:
                units.append("\n".join(part))
                part = []
            part.append(line)
        if part:
            units.append("\n".join(part))

    passages: list[str] = []
    current = ""
    for unit in units:
        # Start a fresh passage at a heading once the current one has some
        # substance, so sections stay whole instead of being split mid-way.
        starts_heading = _is_heading(unit.split("\n", 1)[0])
        if current and (_words(current) + _words(unit) > MAX_WORDS
                        or (starts_heading and _words(current) >= 60)):
            passages.append(current)
            current = ""
        current = f"{current}\n\n{unit}" if current else unit
        if _words(current) >= TARGET_WORDS:
            passages.append(current)
            current = ""
    if current:
        if passages and _words(current) < MIN_WORDS:
            passages[-1] = f"{passages[-1]}\n\n{current}"
        else:
            passages.append(current)
    return passages


# A heading that starts a new PART of a document (not a step inside it).
_MAJOR = re.compile(
    r"^(?:use[\s-]?case|case[\s-]?study|scenario|incident|lab|exercise|chapter|module|section|part|"
    r"playbook|runbook|investigation|appendix|lesson|unit|project|task|assignment|report)\b",
    re.IGNORECASE,
)
_MINOR = re.compile(r"^(?:step|phase|stage)\b", re.IGNORECASE)


def _is_major(line: str) -> bool:
    s = line.strip()
    if not _is_heading(s) or _MINOR.match(s):
        return False
    return bool(_MAJOR.match(s)) or (s.isupper() and len(s.split()) >= 2)


def split_with_sections(text: str, state: dict) -> list[tuple[str, str | None]]:
    """
    Like split_passages, but also says which document part each passage
    belongs to. `state` is one dict per document, passed page after page:
      state["major"]  the latest part heading seen ("Use Case 7: …")
      state["title"]  the first heading of the document (fallback)
    RETURNS [(passage, section or None)].
    """
    out: list[tuple[str, str | None]] = []
    for passage in split_passages(text):
        lines = [l.strip() for l in passage.split("\n") if l.strip()]
        if not state.get("title"):
            first = next((l for l in lines if _is_heading(l) and not _MINOR.match(l)), None)
            if first:
                state["title"] = first
        if lines and _is_major(lines[0]):
            state["major"] = lines[0]
        out.append((passage, state.get("major") or state.get("title")))
        for l in lines[1:]:
            if _is_major(l):
                state["major"] = l
    return out


def with_section(text: str, section: str | None) -> str:
    """
    Prefix a passage with the document part it came from ("(From: Use Case
    7: Insider Data Theft)") so the AI knows the context of a passage that
    starts mid-way ("Step 3: …"). Skipped when the passage starts with that
    heading anyway. Used by writer.py and lessons.py (v0.6.1).
    """
    if section and not text.lstrip().startswith(section):
        return f"(From: {section})\n{text}"
    return text


def fingerprint(text: str) -> str:
    """
    SHA-256 of the passage with case, spacing and punctuation removed.
    Two passages with the same fingerprint say exactly the same thing.
    """
    normalised = _NON_WORD.sub(" ", text.lower()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def approx_tokens(text: str) -> int:
    """
    Rough token count (AI models read text in "tokens", about ¾ of a word).
    Used to pack passages into a model's context window.
    """
    return int(len(text.split()) * 1.33) + 1
