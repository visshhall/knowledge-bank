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
    # Each item: [box_points, text, confidence]. Sort by the top-left corner:
    # rows first (rounded to ~10 px so words on one line stay together), then x.
    lines = [
        (round(item[0][0][1] / 10), item[0][0][0], item[1])
        for item in result
        if float(item[2]) >= MIN_CONFIDENCE and item[1].strip()
    ]
    lines.sort()
    return "\n".join(text for _row, _x, text in lines)
