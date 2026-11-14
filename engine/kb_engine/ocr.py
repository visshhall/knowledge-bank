"""
ocr.py — reads text out of pictures (scanned pages, screenshots, diagrams).

WHAT:  One function, read_text(image_bytes) → text, backed by RapidOCR, an
       offline OCR engine that runs small neural networks on the CPU via
       onnxruntime. Its models ship inside the Python package, so nothing is
       downloaded and nothing leaves the laptop.

WHY:   Some PDFs are scans (pictures of pages with no text layer) and the
       owner also adds screenshots and diagrams. Without OCR their content
       would be invisible to search and to the knowledge bank.
       RapidOCR was chosen over Tesseract because it installs as a normal
       Python package (bundled in the app — no separate Windows install),
       and it handles screenshots and mixed layouts well.

WHEN:  Called by importer.py for: PDF pages with almost no text, images
       embedded in PDFs, and standalone image files.

CONNECTED TO: importer.py (only caller). Uses CPU only, so it doesn't
       compete with the AI models for the graphics card's 4 GB.

PERFORMANCE: ~1–2 s per page-sized image. The engine is loaded once, on
       first use (~1–2 s), then reused.
"""

import io
import re
import threading

from PIL import Image

_engine = None              # the loaded RapidOCR instance (created lazily)
last_error: str | None = None  # last OCR failure, shown in import status
_load_lock = threading.Lock()   # guards creating the engine (once)
_run_lock = threading.Lock()    # one OCR call at a time keeps memory use flat
# Two separate locks on purpose: read_text() holds _run_lock while it calls
# _get_engine(), which needs _load_lock. Using one lock for both would make
# the first OCR call wait on itself forever (a deadlock found in testing).

# Lines the OCR engine is less than this confident about are dropped —
# they are usually noise (specks, borders, icon fragments).
MIN_CONFIDENCE = 0.5

# Images are shrunk so their longest side is at most this many pixels before
# OCR. Bigger adds time without improving accuracy for normal text.
MAX_SIDE_PX = 2400


def _get_engine():
    """Load RapidOCR the first time it's needed (thread-safe), then reuse it."""
    global _engine
    with _load_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR  # heavy import, done once
            _engine = RapidOCR()
        return _engine


def _normalise(image_bytes: bytes) -> bytes:
    """
    Convert any image format (PNG, JPEG, WEBP, GIF, BMP, TIFF…) into a PNG of
    sensible size, so the OCR engine always gets input it handles well.
    Transparent backgrounds are flattened onto white (dark text on a
    transparent PNG would otherwise read as black-on-black).
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        img.seek(0)  # first frame of animated GIFs / multi-page TIFFs
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
        if max(img.size) > MAX_SIDE_PX:
            img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()


def read_text(image_bytes: bytes) -> str:
    """
    Return the text found in an image, one detected line per output line,
    in top-to-bottom, left-to-right reading order. Returns "" if nothing
    readable was found, the image couldn't be decoded, or OCR failed (in
    which case `last_error` explains why).
    """
    global last_error
    try:
        png = _normalise(image_bytes)
    except Exception:
        return ""  # not a decodable image — treat as "no text"
    try:
        engine = _get_engine()
        with _run_lock:
            result, _timings = engine(png)
    except Exception as exc:
        # Safety net: if the OCR engine itself fails, keep importing the
        # rest of the file (its normal text still goes in) and report the
        # problem, rather than failing the whole file.
        last_error = f"OCR unavailable: {exc}"
        return ""
    if not result:
        return ""
    items = [(item[0], item[1]) for item in result
             if float(item[2]) >= MIN_CONFIDENCE and item[1].strip()]
    return fix_ocr_text(assemble_rows(items))


def assemble_rows(items: list) -> str:
    """
    Rebuild lines (and table rows) from OCR boxes.

    WHY (v0.6.2, owner's screenshot of a scanned log table): the OCR engine
        returns one box per word group. The old code put every box on its
        own line, so a table row "2025-07-28 18:21:10 | WINRDP01 | 4624 |
        SUCCESS" became four separate lines, and short ones looked like
        headings.
    HOW:  boxes whose vertical centres fall within half a line height of each
        other are one row; inside a row boxes are sorted left to right. A
        horizontal gap wider than ~1.5 characters means a new table cell and is
        written as " · " (the same cell separator spreadsheets use, which
        chunking keeps as structure and the app draws as a table); a small
        gap is a normal space.
    items: [(box 4×[x, y], text)]. RETURNS text, one row per line.
    """
    boxes = []
    for box, text in items:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({"x0": min(xs), "x1": max(xs), "yc": (min(ys) + max(ys)) / 2,
                      "h": max(1.0, max(ys) - min(ys)), "text": text.strip()})
    boxes.sort(key=lambda b: (b["yc"], b["x0"]))
    rows: list[list[dict]] = []
    for b in boxes:
        row = rows[-1] if rows else None
        if row is not None:
            yc = sum(r["yc"] for r in row) / len(row)
            h = sum(r["h"] for r in row) / len(row)
            if abs(b["yc"] - yc) <= 0.5 * max(h, b["h"]):
                row.append(b)
                continue
        rows.append([b])
    out = []
    for row in rows:
        row.sort(key=lambda b: b["x0"])
        line = row[0]["text"]
        for prev, cur in zip(row, row[1:]):
            char_w = (prev["x1"] - prev["x0"]) / max(1, len(prev["text"]))
            gap = cur["x0"] - prev["x1"]
            # The OCR engine already groups words of one phrase into one box,
            # so two boxes on a row are usually separate cells; only a
            # gap of about one character is treated as an ordinary space.
            # A lower-case word after a gap, following a word, continues the
            # sentence (justified or spaced-out prose) — not a new cell. Data
            # such as "10" → "admin@corp.local" still splits.
            continues = cur["text"][:1].islower() and prev["text"][-1:].isalpha() \
                and "@" not in cur["text"].split(" ")[0]
            new_cell = gap > max(1.5 * char_w, 0.5 * prev["h"]) and not continues
            line += (" · " if new_cell else " ") + cur["text"]
        out.append(line)
    return "\n".join(out)


# Common OCR breaks in security text: "192.168.1. 88" → "192.168.1.88",
# "2025-0728" → "2025-07-28", "10 . 0 . 0 . 5" → "10.0.0.5",
# "2025-07-2818:21:10" → "2025-07-28 18:21:10".
_IP_SPLIT = re.compile(r"\b(\d{1,3})\s*\.\s*(\d{1,3})\s*\.\s*(\d{1,3})\s*\.\s*(\d{1,3})\b")
_DATE_SQUASH = re.compile(r"\b((?:19|20)\d{2})-(\d{2})(\d{2})\b")
_DATE_TIME_GLUED = re.compile(r"\b((?:19|20)\d{2}-\d{2}-\d{2})(\d{2}:\d{2})")


def fix_ocr_text(text: str) -> str:
    """Repair predictable OCR spacing mistakes in IP addresses and dates."""
    text = _IP_SPLIT.sub(r"\1.\2.\3.\4", text)
    text = _DATE_SQUASH.sub(r"\1-\2-\3", text)
    return _DATE_TIME_GLUED.sub(r"\1 \2", text)  # "2025-07-2818:21" → "2025-07-28 18:21"
