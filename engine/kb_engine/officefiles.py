"""
officefiles.py — reads Word, PowerPoint, web pages, text and Markdown (v0.9).

WHAT:  read(path) → list of "pages", each {"text", "tables", "pictures"}:
         .docx       Word: paragraphs in order (headings kept as headings),
                     tables kept as tables (rows joined with " · ", the grid
                     saved for lessons), pictures in the document. One "page"
                     per ~3,000 characters, split at paragraph boundaries, so
                     citations point somewhere useful.
         .pptx       PowerPoint: one page per slide (title first, then the
                     text boxes, tables and speaker notes), pictures on it.
         .html/.htm  Saved web pages: the readable text (scripts, styles,
                     menus and footers dropped), headings and list items kept.
         .txt/.md    Plain text and Markdown, paged like Word.
       pictures = raw image bytes (≥ 160 px), OCR'd by importer.py like the
       pictures inside PDFs.

WHY:   Owner chose "more file types" (15 Nov 2026): a lot of security
       material arrives as Word reports, slide decks and saved web pages,
       which the Library used to ignore.

HOW:   .docx and .pptx are ZIP files of XML; they are read with the Python
       standard library (zipfile + ElementTree) — no extra packages to
       bundle, nothing to install on Windows. HTML uses html.parser.

WHEN:  importer._extract_doc() for any file of type 'doc'.

CONNECTED TO: importer.py (only caller).
"""

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

DOC_EXTENSIONS = {".docx", ".pptx", ".html", ".htm", ".txt", ".md", ".markdown"}
PAGE_CHARS = 3000          # Word/text documents are cut into "pages" of about this size
MIN_PICTURE_PX = 160

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def read(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext in (".html", ".htm"):
        return _paged(_html_text(path.read_bytes()), [])
    return _paged(_decode(path.read_bytes()), [])


# --- helpers ---------------------------------------------------------------------

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            if "\x00" not in text:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _paged(text: str, tables: list, pictures: list | None = None) -> list[dict]:
    """Cut long text into ~PAGE_CHARS pages at blank lines / paragraph ends."""
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    pages, cur = [], ""
    for b in blocks:
        b = b.strip("\n")
        if not b.strip():
            continue
        if cur and len(cur) + len(b) > PAGE_CHARS:
            pages.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        pages.append(cur)
    out = [{"text": p, "tables": [], "pictures": []} for p in pages] or [{"text": "", "tables": [], "pictures": []}]
    out[0]["tables"] = tables
    if pictures:
        out[0]["pictures"] = pictures
    return out


def _big_picture(data: bytes) -> bool:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return min(im.size) >= MIN_PICTURE_PX
    except Exception:
        return False


# --- Word ---------------------------------------------------------------------

def _para_text(p) -> str:
    parts = []
    for node in p.iter():
        if node.tag == _W + "t" and node.text:
            parts.append(node.text)
        elif node.tag == _W + "tab":
            parts.append("\t")
        elif node.tag in (_W + "br", _W + "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
        pictures = [z.read(n) for n in z.namelist()
                    if n.startswith("word/media/") and not n.lower().endswith((".emf", ".wmf", ".svg"))]
    body = root.find(_W + "body")
    lines: list[str] = []
    tables: list[tuple[str, list[list[str]]]] = []
    for el in list(body) if body is not None else []:
        if el.tag == _W + "p":
            t = _para_text(el)
            if not t:
                lines.append("")
                continue
            style = el.find(f"{_W}pPr/{_W}pStyle")
            sval = (style.get(_W + "val") if style is not None else "") or ""
            if sval.lower().startswith(("heading", "title")):
                lines += ["", t, ""]  # headings stand alone so chunking sees them
            elif el.find(f"{_W}pPr/{_W}numPr") is not None:
                lines.append(f"• {t}")
            else:
                lines += [t, ""]
        elif el.tag == _W + "tbl":
            rows = []
            for tr in el.iter(_W + "tr"):
                cells = [re.sub(r"\s+", " ", " ".join(_para_text(p) for p in tc.iter(_W + "p"))).strip()
                         for tc in tr.iter(_W + "tc")]
                if any(cells):
                    rows.append(cells)
            if len(rows) >= 2:
                tables.append((f"Table {len(tables) + 1}", rows))
                lines += ["", *[" · ".join(c or "—" for c in r) for r in rows], ""]
    pages = _paged("\n".join(lines), [])
    # Tables go with the page whose text contains their first row.
    for name, rows in tables:
        first = " · ".join(c or "—" for c in rows[0])
        page = next((p for p in pages if first in p["text"]), pages[0])
        page["tables"].append((name, rows))
    pics = [d for d in pictures if _big_picture(d)]
    if pics:
        pages[0]["pictures"] = pics
    return pages


# --- PowerPoint -------------------------------------------------------------------

def _slide_no(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _pptx(path: Path) -> list[dict]:
    pages = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_slide_no)
        for sname in slides:
            root = ET.fromstring(z.read(sname))
            title, texts, tables = "", [], []
            for sp in root.iter(_P + "sp"):
                ph = sp.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
                paras = []
                for p in sp.iter(_A + "p"):
                    t = "".join(r.text or "" for r in p.iter(_A + "t")).strip()
                    if t:
                        ppr = p.find(f"{_A}pPr")
                        bullet = ppr is not None and (
                            ppr.find(_A + "buChar") is not None or ppr.find(_A + "buAutoNum") is not None
                            or int(ppr.get("lvl") or 0) > 0)
                        paras.append(("• " if bullet else "") + t)
                if not paras:
                    continue
                if ph is not None and ph.get("type") in ("title", "ctrTitle") and not title:
                    title = " ".join(paras)
                else:
                    texts.append("\n".join(paras))
            for tbl in root.iter(_A + "tbl"):
                rows = []
                for tr in tbl.iter(_A + "tr"):
                    cells = [" ".join((t.text or "") for t in tc.iter(_A + "t")).strip() for tc in tr.iter(_A + "tc")]
                    if any(cells):
                        rows.append(cells)
                if len(rows) >= 2:
                    tables.append((f"Table on slide {_slide_no(sname)}", rows))
                    texts.append("\n".join(" · ".join(c or "—" for c in r) for r in rows))
            # speaker notes
            notes = f"ppt/notesSlides/notesSlide{_slide_no(sname)}.xml"
            if notes in names:
                nroot = ET.fromstring(z.read(notes))
                ntext = "\n".join("".join(r.text or "" for r in p.iter(_A + "t")).strip()
                                  for p in nroot.iter(_A + "p"))
                ntext = "\n".join(l for l in ntext.splitlines() if l.strip() and not l.strip().isdigit())
                if ntext.strip():
                    texts.append("Speaker notes: " + ntext)
            # pictures on this slide (via its relationships file)
            pics = []
            rels = f"ppt/slides/_rels/{Path(sname).name}.rels"
            if rels in names:
                for rel in ET.fromstring(z.read(rels)):
                    target = rel.get("Target", "")
                    if "media/" in target:
                        media = "ppt/" + target.split("../", 1)[-1] if target.startswith("../") else target
                        if media in names and not media.lower().endswith((".emf", ".wmf", ".svg")):
                            data = z.read(media)
                            if _big_picture(data):
                                pics.append(data)
            text = "\n\n".join(([title] if title else []) + texts)
            pages.append({"text": text, "tables": tables, "pictures": pics})
    return pages or [{"text": "", "tables": [], "pictures": []}]


# --- HTML -------------------------------------------------------------------------

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "button", "iframe",
            "title", "head"}
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
             "pre", "blockquote", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.in_li, self.in_pre = [], 0, False, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif not self.skip:
            if tag in self.BLOCK:
                self.out.append("\n\n" if tag.startswith("h") or tag == "p" else "\n")
            if tag == "li":
                self.out.append("• ")
            if tag in ("td", "th"):
                self.out.append(" · ")
            if tag == "pre":
                self.in_pre = True

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in self.BLOCK:
            self.out.append("\n\n" if tag.startswith("h") else "\n")
            if tag == "pre":
                self.in_pre = False

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data if self.in_pre else re.sub(r"\s+", " ", data))


def _html_text(data: bytes) -> str:
    p = _Text()
    p.feed(_decode(data))
    text = "".join(p.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n · ", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
