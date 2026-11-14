"""
ocr.py — reads text out of pictures (scanned pages, screenshots, diagrams).

WHAT:  read_text(image_bytes) → text, backed by RapidOCR, an offline OCR
       engine that runs small neural networks via onnxruntime. It is safe
       to call from several threads at once: each call borrows one engine
       from a small pool (v0.8.1). Its models ship inside the Python package, so nothing is
       downloaded and nothing leaves the laptop.

WHY:   Some PDFs are scans (pictures of pages with no text layer) and the
       owner also adds screenshots and diagrams. Without OCR their content
       would be invisible to search and to the knowledge bank.
       RapidOCR was chosen over Tesseract because it installs as a normal
       Python package (bundled in the app — no separate Windows install),
       and it handles screenshots and mixed layouts well.

WHEN:  Called by importer.py for: PDF pages with almost no text, images
       embedded in PDFs, and standalone image files.

CONNECTED TO: importer.py (only caller).

PERFORMANCE: about 3 s per scanned page on a laptop processor; OCR is
       almost all of the import time (text pages take ~20 ms each).
       v0.8.1 (owner: "import is too slow"):
         - On Windows the bundled onnxruntime is the DirectML build, which
           runs the OCR networks on ANY graphics card (NVIDIA, AMD, Intel).
           The models are small (~15 MB, a few hundred MB while running),
           so they fit beside the AI model on the 4 GB card. If DirectML is
           missing or fails on the first page, OCR switches to the processor
           for the rest of the session — importing never stops because of it.
         - prewarm() loads the engine in the background as soon as an import
           starts, so the first scanned page doesn't wait for the load.
       The 180° text-line classifier stays on: switching it off was ~10%
       faster in tests but changed the text read, and accuracy comes first.
"""

import io
import re
import threading

from PIL import Image

import queue

device = "not loaded"       # "graphics card" or "processor" — shown in import status
last_error: str | None = None  # last OCR failure, shown in import status
_gpu_failed = False         # set once DirectML failed; then processor for the session
_load_lock = threading.Lock()  # guards building the pool (once)
_pool: "queue.Queue | None" = None  # idle engines; read_text borrows one
_size = 0                   # how many engines the pool holds
# v0.8.1 design note: the old single engine + one global run lock meant one
# picture at a time using all cores. Measured on 2 cores: two engines with
# one thread each read 34% more pages per second than one engine with all
# threads (ONNX models of this size don't spread well over many threads).
# On the owner's 8+-core laptop the gain is larger.

# Lines the OCR engine is less than this confident about are dropped —
# they are usually noise (specks, borders, icon fragments).
MIN_CONFIDENCE = 0.5

# Images are shrunk so their longest side is at most this many pixels before
# OCR. Bigger adds time without improving accuracy for normal text.
MAX_SIDE_PX = 2400


def _gpu_available() -> bool:
    """True when this onnxruntime build can use DirectML (Windows bundle)."""
    try:
        import onnxruntime
        import platform
        return platform.system() == "Windows" and "DmlExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False


def _cpu_plan() -> tuple[int, int]:
    """(engines, threads per engine) for this processor.
    About 2 cores per engine, at most 3 engines (~200 MB of memory each, so
    the AI model and the window keep plenty of the 16 GB)."""
    try:
        import psutil
        cores = psutil.cpu_count(logical=False) or 2
    except Exception:
        cores = 2
    engines = max(1, min(3, cores // 2)) if cores >= 2 else 1
    return engines, max(1, cores // engines)


def _build_pool() -> None:
    """Create the engines (called under _load_lock). Graphics card: ONE
    engine (the card runs one picture at a time anyway). Processor: a few
    single-purpose engines that work side by side."""
    global _pool, _size, device
    from rapidocr_onnxruntime import RapidOCR  # heavy import, done once
    engines = []
    if not _gpu_failed and _gpu_available():
        try:
            engines = [RapidOCR(det_use_dml=True, cls_use_dml=True, rec_use_dml=True)]
            device = "graphics card"
        except Exception:
            engines = []
    if not engines:
        n, threads = _cpu_plan()
        engines = [RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1) for _ in range(n)]
        device = "processor"
    q: queue.Queue = queue.Queue()
    for e in engines:
        q.put(e)
    _pool, _size = q, len(engines)


def _ensure_pool() -> "queue.Queue":
    with _load_lock:
        if _pool is None:
            _build_pool()
        return _pool


def workers() -> int:
    """How many pictures can be read at the same time (importer uses this
    to decide how many scanned pages to send at once)."""
    _ensure_pool()
    return _size


def _fall_back_to_cpu() -> None:
    """DirectML failed while reading: rebuild the pool on the processor."""
    global _pool, _gpu_failed
    with _load_lock:
        if not _gpu_failed:
            _gpu_failed = True
            _pool = None


def prewarm() -> None:
    """Load the OCR engines in a background thread (called when an import
    with work starts), so the first scanned page doesn't pay the load time."""
    def run():
        try:
            _ensure_pool()
        except Exception:
            pass
    threading.Thread(target=run, name="kb-ocr-warm", daemon=True).start()


def _run(png: bytes):
    """Borrow an idle engine, read one picture, give the engine back."""
    pool = _ensure_pool()
    engine = pool.get()
    try:
        return engine(png)
    finally:
        pool.put(engine)


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
        try:
            result, _timings = _run(png)
        except Exception:
            if device != "graphics card":
                raise
            # The graphics card path failed (driver, memory): retry this
            # same picture on the processor and stay there.
            _fall_back_to_cpu()
            result, _timings = _run(png)
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
