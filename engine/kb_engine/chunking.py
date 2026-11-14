"""
chunking.py — cleans page text and cuts it into passages (the bank's basic unit).

WHAT:  clean(text)          → tidy text that KEEPS its structure: bullet
                               lists, query lines and short headings stay on
                               their own lines; only ordinary wrapped prose
                               is joined into paragraphs.
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

CHUNKER_VERSION = 2  # bump when clean()/split_passages() rules change

TARGET_WORDS = 180   # aim for passages about this long
MAX_WORDS = 260      # never longer than this (long blocks get split)
MIN_WORDS = 12       # shorter leftovers are merged into the previous passage

_SPACES = re.compile(r"[ \t ]+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

# A line that starts a list item: •, ●, ▪, ◦, -, *, –, or "1." / "1)" / "a)".
_BULLET = re.compile(r"^\s*(?:[•●▪◦‣∙\-\*–]|\d{1,2}[.)]|[a-z][.)])\s+")
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


def _is_heading(line: str) -> bool:
    """
    Short line that looks like a title: under ~70 characters, no sentence
    punctuation at the end, and mostly capitalised words (e.g. "Detection
    Logic", "USE CASE 9: DLL SIDELOADING").
    """
    s = line.strip()
    if not (3 <= len(s) <= 70) or s.endswith((".", ",", ";")):
        return False
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-']*", s)]
    if not words:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.7


def _is_structural(line: str) -> bool:
    """True for lines that must keep their own line: bullets, code, headings."""
    return bool(_BULLET.match(line) or _CODE_START.match(line)) or _is_heading(line)


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
                and not line[0].isupper():
            current[-1] = f"{current[-1]} {line}"   # continuation of a bullet item
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

    units: list[str] = []
    for block in text.split("\n\n"):
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
        if current and _words(current) + _words(unit) > MAX_WORDS:
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
