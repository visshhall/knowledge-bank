"""
cleaning.py — removes junk from page text before it becomes passages (v0.9).

WHAT:  1. boilerplate(page_texts) → the set of short lines repeated on many
          pages of one document (running headers, footers, watermarks,
          "Confidential", "© Company 2024", the author's name on every
          slide…). Found from the PDF's text layer before reading starts.
       2. clean_page(text, page_number, page_count, boilerplate) →
          (cleaned text, junk reason or None). A junk page keeps its stored
          text (so "Read in context" still shows it) but gives NO passages:
            - blank pages
            - "follow / like / repost / save this post" promo pages
            - contents / index pages (lines ending in page numbers)
            - a cover page: page 1 with only a title (its words are still
              used to name the file — see titles.py)
          On normal pages, page-number lines ("Page 3 of 12", "- 3 -"),
          promo lines ("Follow me for more", "Like ♻ Repost",
          linkedin.com/in/…) and boilerplate lines are removed.
       3. is_garbled(text) → True when a PDF's text layer is gibberish
          (broken font encoding: "ĂŵĞƌŝĐĂ", "", ")(*&%") — importer.py then
          reads that page by OCR instead.

WHY:   Owner chose "clean junk pages and lines" and "garbled text detection"
       (15 Nov 2026). Many of his PDFs are LinkedIn carousels: every slide
       repeats the author's name and handle, the last slide says "Follow for
       more", and some exports have broken fonts. That junk became passages,
       then topic points, then article lines.

HOW:   Plain rules on the text (no AI) so it is instant and predictable.
       Every rule is conservative: a page or line is only dropped when it is
       clearly junk; anything with real sentences stays.

WHEN:  importer._extract_pdf (new files), importer._store_page,
       importer.clean_existing() (once per bank: removes passages that are
       entirely junk, without renumbering the others, so topics and article
       citations stay valid).

CONNECTED TO: importer.py (only caller), titles.py (cover text → file name).
"""

import re
import unicodedata

# --- promo / social lines -----------------------------------------------------
_PROMO = re.compile(
    r"(follow\s+(me|us|for)|like\s*[,&|/•·]?\s*(comment|share|repost)|repost\b|♻|"
    r"save\s+(this|for later)|share\s+with\s+your|hit\s+the\s+bell|subscribe|"
    r"link\s+in\s+(bio|comments?)|dm\s+me|turn\s+on\s+notifications|"
    r"was\s+this\s+(helpful|useful)|found\s+this\s+(helpful|useful)|"
    r"for\s+more\s+(such\s+)?(content|posts|tips)|thank\s*s?\s+(you\s+)?for\s+reading|"
    r"linkedin\.com/in/|t\.me/|instagram\.com/|youtube\.com/@|@\w{3,}\s*$)",
    re.I,
)
# "Page 3", "Page 3 of 12", "3 / 12", "3/12", "- 3 -" — clearly page labels,
# safe to drop anywhere. A BARE number ("3") is only dropped at the very top or
# bottom of a page, because inside a page it may be data (a port, a count).
_PAGE_NO = re.compile(r"^\s*(page\s*\d{1,4}(\s*(of|/)\s*\d{1,4})?|\d{1,4}\s*(of|/)\s*\d{1,4}|[-–—]\s*\d{1,4}\s*[-–—])\s*$", re.I)
_BARE_NO = re.compile(r"^\s*\d{1,4}\s*$")
_TOC_LINE = re.compile(r"(\.{3,}|…{2,}|\s{3,})\s*\d{1,4}\s*$|^\s*\d+(\.\d+)*\s+.{3,80}\s+\d{1,4}\s*$")
_TOC_HEAD = re.compile(r"^\s*(table\s+of\s+contents|contents|index|agenda)\s*$", re.I)
_SENTENCE = re.compile(r"[a-z]{3,}[^.!?]{15,}[.!?](\s|$)")


def _norm(line: str) -> str:
    """Line key for boilerplate: lower case, digits → #, spacing squeezed."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.lower())).strip()


def boilerplate(page_texts: list[str], min_pages: int = 3, share: float = 0.5) -> set[str]:
    """
    Short lines (≤ 12 words) at the top or bottom of a page that appear on at
    least `share` of the pages (and on at least `min_pages` pages). Counted
    once per page; digits are ignored ("Page 3" = "Page 7").
    """
    n = len(page_texts)
    if n < min_pages:
        return set()
    counts: dict[str, int] = {}
    for text in page_texts:
        # Only the top 3 and bottom 3 lines of a page are candidates: that is
        # where headers, footers and slide watermarks sit, and it keeps a
        # short sentence that genuinely repeats in the body from being lost.
        lines = [l for l in text.splitlines() if l.strip()]
        edges = lines[:3] + lines[-3:]
        seen = {_norm(l) for l in edges if len(l.split()) <= 12}
        for key in seen:
            if len(key) >= 3:
                counts[key] = counts.get(key, 0) + 1
    need = max(min_pages, int(n * share + 0.999))
    return {k for k, c in counts.items() if c >= need}


def _is_toc(lines: list[str]) -> bool:
    if len(lines) < 5:
        return False
    if any(_TOC_HEAD.match(l) for l in lines[:3]):
        return sum(bool(_TOC_LINE.search(l)) for l in lines) >= 0.4 * len(lines)
    return sum(bool(_TOC_LINE.search(l)) for l in lines) >= 0.7 * len(lines)


def clean_page(text: str, page_number: int, page_count: int,
               boiler: set[str] | None = None) -> tuple[str, str | None]:
    """
    RETURNS (cleaned text, junk reason). When the reason is not None the page
    gives no passages (the caller still stores the original page text).
    """
    raw_lines = [l for l in (text or "").splitlines()]
    lines = [l for l in raw_lines if l.strip()]
    words = sum(len(l.split()) for l in lines)
    if words < 3:
        return "", "blank page"
    if _is_toc(lines):
        return "", "contents or index page"
    promo_lines = [l for l in lines if _PROMO.search(l) and len(l.split()) <= 15]
    if promo_lines and words <= 60 and not _SENTENCE.search(
            " ".join(l for l in lines if l not in promo_lines).lower()):
        return "", "promotion page (follow / like / repost)"
    if page_number == 1 and page_count > 2 and words <= 20 and not _SENTENCE.search(text.lower()):
        return "", "cover page"
    kept = []
    nonblank = [i for i, l in enumerate(raw_lines) if l.strip()]
    edges = set(nonblank[:2] + nonblank[-2:])
    for i, l in enumerate(raw_lines):
        s = l.strip()
        if not s:
            kept.append(l)
            continue
        if _PAGE_NO.match(s) or (i in edges and _BARE_NO.match(s)):
            continue
        if _PROMO.search(s) and len(s.split()) <= 15:
            continue
        if boiler and len(s.split()) <= 12 and _norm(s) in boiler:
            continue
        kept.append(l)
    return "\n".join(kept).strip(), None


def is_junk_passage(passage: str) -> bool:
    """For banks imported earlier: a passage made only of junk lines."""
    lines = [l.strip() for l in passage.splitlines() if l.strip()]
    if not lines:
        return True
    return all(_PAGE_NO.match(l) or (_PROMO.search(l) and len(l.split()) <= 15) for l in lines)


# --- garbled text ---------------------------------------------------------------
_VOWELS = set("aeiouAEIOU")


def is_garbled(text: str) -> bool:
    """
    A text layer that is gibberish (broken font encoding). Checks, on pages
    with at least 120 characters:
      - more than 15% of characters are control/private-use/replacement or
        unusual symbols, or
      - fewer than 45% of the "words" look like words (letters with a vowel).
    Non-Latin scripts (Devanagari etc.) are treated as normal text.
    """
    t = (text or "").strip()
    if len(t) < 120:
        return False
    odd = 0
    letters = 0
    for ch in t:
        cat = unicodedata.category(ch)
        if cat in ("Co", "Cs", "Cn") or ch == "�" or (cat == "Cc" and ch not in "\n\r\t"):
            odd += 1
        elif cat.startswith("L"):
            letters += 1
    if odd / len(t) > 0.15:
        return True
    # Broken fonts often come out as Latin-Extended look-alikes ("ĂŵĞƌŝĐĂ"):
    # real English or Hindi text almost never has many of those.
    extended = sum(1 for ch in t if "\u0100" <= ch <= "\u024f" or "\u1e00" <= ch <= "\u1eff")
    if letters and extended / letters > 0.3:
        return True
    digits = sum(ch.isdigit() for ch in t)
    if letters / len(t) < 0.25 and digits / len(t) < 0.3:
        return True  # mostly symbols: ")(*&% #$@!"
    if not re.search(r"[A-Za-z]", t):
        return False  # a non-Latin script; can't judge with English rules
    tokens = re.findall(r"\S+", t)
    wordlike = sum(1 for w in tokens if re.fullmatch(r"[A-Za-z][A-Za-z'’-]*[.,:;!?)]*", w) and set(w) & _VOWELS
                   or re.fullmatch(r"[\d.,:/%()-]+", w))
    return len(tokens) >= 20 and wordlike / len(tokens) < 0.45
