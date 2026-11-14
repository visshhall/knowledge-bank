"""
chunking.py — cuts page text into passages (the bank's basic unit).

WHAT:  split_passages(text) → list of passages of roughly 120–260 words,
       broken at paragraph boundaries where possible.
       fingerprint(text) → a hash that is identical for passages whose
       wording is the same apart from spacing/case/punctuation.

WHY:   - Search results, merging and source citations all work on passages.
         A passage must be big enough to carry one idea, small enough that
         a citation points to something specific.
       - Passages never cross a page boundary, so every passage can cite
         one exact page.
       - The fingerprint catches the most common duplicate: the same
         paragraph copied into several PDFs. (Same meaning in different
         words is caught later, in Phase 2, with embeddings.)

WHEN:  Called by importer.py for every page after its text is extracted.

CONNECTED TO: importer.py (caller); db.py `passages` table (stores
       text, token_count and content_hash produced here).
"""

import hashlib
import re

TARGET_WORDS = 180   # aim for passages about this long
MAX_WORDS = 260      # never longer than this (long paragraphs get split)
MIN_WORDS = 12       # shorter leftovers are merged into the previous passage

_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def clean(text: str) -> str:
    """
    Tidy raw PDF text: join words hyphenated across line ends
    ("detec-\\ntion" → "detection"), collapse repeated spaces, and keep
    paragraph breaks (blank lines) while removing single hard line wraps.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    paragraphs = _BLANK_LINES.split(text)
    paragraphs = [_WHITESPACE.sub(" ", p.replace("\n", " ")).strip() for p in paragraphs]
    return "\n\n".join(p for p in paragraphs if p)


def split_passages(text: str) -> list[str]:
    """
    Split one page's text into passages.

    HOW:  Walk the paragraphs, adding each to the current passage until it
          reaches TARGET_WORDS; a paragraph longer than MAX_WORDS is cut into
          MAX_WORDS-sized pieces. A tiny final leftover is merged backwards
          so we don't create one-line passages.
    """
    text = clean(text)
    if not text:
        return []

    pieces: list[list[str]] = []
    for para in text.split("\n\n"):
        words = para.split()
        while len(words) > MAX_WORDS:          # oversized paragraph → slices
            pieces.append(words[:MAX_WORDS])
            words = words[MAX_WORDS:]
        if words:
            pieces.append(words)

    passages: list[list[str]] = []
    current: list[str] = []
    for words in pieces:
        if current and len(current) + len(words) > MAX_WORDS:
            passages.append(current)
            current = []
        current = current + words
        if len(current) >= TARGET_WORDS:
            passages.append(current)
            current = []
    if current:
        if passages and len(current) < MIN_WORDS:
            passages[-1] = passages[-1] + current
        else:
            passages.append(current)
    return [" ".join(p) for p in passages]


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
    Used later to pack passages into a model's context window.
    """
    return int(len(text.split()) * 1.33) + 1
