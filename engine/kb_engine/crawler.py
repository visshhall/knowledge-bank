"""
crawler.py — v0.13: read a web page, a section of a site or a whole site into the bank.

WHAT:  The owner types a web address. The crawler fetches it and, depending on the
       scope he picks, follows links to more pages of the SAME site:
         page     only that one page;
         section  that page and the pages under the same folder of the site
                  (https://shop.example/guides/ → /guides/a, /guides/b/c …);
         site     every page of that site it can reach (also uses sitemap.xml).
       Each page (and each PDF / Word / Excel / PowerPoint / text file the pages
       link to) is saved as a copy in the data folder (…/web/<site>/…), registered
       as a source with its address (sources.url) and then goes through exactly the
       same import as a file from disk: cleaning, passages, search, topics, chat.
WHY:   The owner wants his private AI to learn from "anything and everything", not only
       his PDFs — product pages, documentation sites, articles. Saving a local copy means
       the bank keeps working offline and the answers cite what the page said when it
       was read.
HOW IT BEHAVES (the rules, all fixed in code so a wrong click cannot cause harm):
       - Only http:// and https:// addresses. Addresses that point at this computer or
         the local network (127.x, 10.x, 192.168.x, 169.254.x …) are refused, also after
         a redirect — so a crawl can never reach the app's own engine or his router.
       - Only the same site (www. and non-www. count as the same). Links to other sites
         are not followed.
       - robots.txt is respected for every page the crawler FINDS (a page the owner typed
         himself is fetched, as a browser would). A Crawl-delay is honoured up to 10 s.
       - Polite: one request at a time, at least 1 second between requests, 20 s timeout,
         pages up to 5 MB and documents up to 40 MB, at most MAX_PAGES_LIMIT pages.
       - Pages with almost no readable text (under 200 characters — usually pages that need
         JavaScript to show anything) are skipped and counted. Pages marked noindex are skipped.
       - Tracking parameters (utm_*, fbclid, gclid …) and #fragments are ignored; at most
         5 variants of the same path (filters, sorting) are fetched, so a shop's endless
         filter combinations cannot swallow the page limit.
       - Login, cart, checkout and admin paths are skipped.
       - The crawler cannot run JavaScript, so pages built entirely in the browser come
         back empty. Server-rendered sites, documentation, blogs and most shops work.
WHEN:  server.py → POST /crawl/start, GET /crawl/status, POST /crawl/stop. One crawl at a
       time, in a background thread; the window (Library.jsx) polls the status.
       The only moment the app contacts the internet for content: when he presses Read.
CONNECTED TO: importer.py (add_paths with url/name/keep options; the normal import then
       runs), officefiles.py (HTML → text, used to check a page has text), config.py
       (DATA_DIR), db.py (sources.url, schema v16), Library.jsx (the window).
RIGHTS NOTE: the bank keeps a local copy of what it reads. The window reminds the owner
       to read only sites he may copy for his own use.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import threading
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib import robotparser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from . import __version__, config

MAX_PAGES_DEFAULT = 30
MAX_PAGES_LIMIT = 500
MAX_DEPTH_LIMIT = 5
HTML_MAX_BYTES = 5 * 1024 * 1024
DOC_MAX_BYTES = 40 * 1024 * 1024
MIN_TEXT_CHARS = 200
MIN_DELAY = 1.0             # seconds between two requests to the same site
MAX_DELAY = 10.0            # longest Crawl-delay we honour
VARIANTS_PER_PATH = 5       # distinct query-string variants of one path
SITEMAP_LIMIT = 200         # addresses taken from sitemaps
TIMEOUT = 20.0
MAX_REDIRECTS = 5
SCOPES = ("page", "section", "site")
USER_AGENT = f"KnowledgeBank/{__version__} (personal offline research tool)"

# Set True only by the tests, which serve a small site from this computer.
ALLOW_PRIVATE = False

TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|msclkid$|yclid$|ref$|_ga$)", re.I)
SKIP_PATH = re.compile(r"/(cart|checkout|login|log-in|logout|signin|sign-in|signup|register|account|my-account|"
                       r"wp-admin|wp-login|admin|cdn-cgi|basket|wishlist)(/|$)", re.I)
SKIP_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tif", ".tiff", ".avif",
            ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm", ".m4a", ".zip", ".rar", ".7z", ".gz", ".tar",
            ".exe", ".msi", ".dmg", ".apk", ".iso", ".css", ".js", ".json", ".xml", ".rss", ".woff", ".woff2",
            ".ttf", ".eot", ".map"}
DOC_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".csv", ".txt", ".md"}
DOC_TYPES = {  # content-type → file extension, for a document whose address has no telling ending
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv", "text/plain": ".txt", "text/markdown": ".md",
}

_lock = threading.Lock()
_state: dict = {"state": "idle"}
_stop = threading.Event()


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def status() -> dict:
    """Live state of the crawl: idle | running | done | stopped | error, with counts and the latest pages."""
    with _lock:
        out = dict(_state)
        out["recent"] = list(out.get("recent", []))
        out["skipped"] = dict(out.get("skipped", {}))
    return out


def stop() -> dict:
    """Stop after the page being read; what was already saved stays in the bank."""
    _stop.set()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

def normalize_url(raw: str) -> str | None:
    """
    What the owner typed → a clean http(s) address, or None. "example.com/a" gets https://.
    Only http and https are accepted; anything else (file://, javascript:, ftp://) is refused.
    """
    raw = (raw or "").strip()
    if not raw or " " in raw:
        return None
    if "://" not in raw:
        if re.match(r"^[a-z][a-z0-9+.-]*:(?!\d)", raw, re.I):   # javascript:, mailto:, data: … (but not host:8080)
            return None
        raw = "https://" + raw
    try:
        u = urlparse(raw)
        if u.scheme not in ("http", "https") or not u.hostname:
            return None
    except ValueError:
        return None
    return canonical(raw) or None


def canonical(url: str) -> str:
    """One spelling per page: lower-case host, no #fragment, no tracking parameters, sorted query."""
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        port = f":{u.port}" if u.port and u.port not in (80, 443) else ""
    except ValueError:
        return ""  # a malformed address (bad port …): callers treat "" as "not an address"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)))
    return urlunparse((u.scheme, host + port, u.path or "/", "", query, ""))


def _site(host: str) -> str:
    """www.example.com and example.com are the same site."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def blocked_address(host: str) -> str | None:
    """
    Why this host must not be fetched, or None if it is fine. Refuses anything that resolves to this
    computer or a private network, so a crawl (or a redirect) can't reach the app's own engine,
    a router page or another device. Also refuses a host that can't be resolved.
    """
    if ALLOW_PRIVATE:
        return None
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return "that address could not be found"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return "that address is on this computer or a private network"
    return None


# ---------------------------------------------------------------------------
# Reading a page's links
# ---------------------------------------------------------------------------

class _Links(HTMLParser):
    """Collects the page title, its first heading, its links and its robots meta tag."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.title = ""
        self.h1 = ""
        self.robots = ""
        self.base: str | None = None
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            if "nofollow" not in (a.get("rel") or "").lower():
                self.links.append(a["href"])
        elif tag == "base" and a.get("href"):
            self.base = a["href"]
        elif tag == "meta" and (a.get("name") or "").lower() == "robots":
            self.robots = (a.get("content") or "").lower()
        elif tag in ("title", "h1") and not (self.title if tag == "title" else self.h1):
            self._in = tag

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1 += data


def read_links(html: str) -> _Links:
    p = _Links()
    try:
        p.feed(html)
    except Exception:
        pass  # a broken page still gives whatever was read before the break
    return p


def _page_title(parsed: _Links, url: str) -> str:
    title = " ".join((parsed.title or parsed.h1).split())
    if title:
        return title[:120]
    tail = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return (tail.replace("-", " ").replace("_", " ").strip() or urlparse(url).hostname or "Web page")[:120]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class _Skip(Exception):
    """A page that is not stored; the message is the reason shown to the owner."""


def _fetch(client: httpx.Client, url: str, max_bytes: int) -> tuple[bytes, str, str]:
    """
    GET one address (following redirects by hand so each hop is checked). RETURNS
    (body, content-type, final address). Raises _Skip with a plain-words reason.
    """
    for _hop in range(MAX_REDIRECTS + 1):
        u = urlparse(url)
        reason = blocked_address(u.hostname or "")
        if reason:
            raise _Skip(reason)
        try:
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = canonical(urljoin(url, r.headers["location"]))
                    if urlparse(url).scheme not in ("http", "https"):
                        raise _Skip("it redirects to something that is not a web page")
                    continue
                if r.status_code >= 400:
                    raise _Skip(f"the site answered {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                declared = int(r.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise _Skip("it is larger than the size limit")
                body = bytearray()
                for chunk in r.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise _Skip("it is larger than the size limit")
                return bytes(body), ctype, url
        except httpx.HTTPError as exc:
            raise _Skip(f"could not be reached ({exc.__class__.__name__})") from exc
    raise _Skip("too many redirects")


# ---------------------------------------------------------------------------
# The crawl
# ---------------------------------------------------------------------------

def start(url: str, scope: str = "section", max_pages: int = MAX_PAGES_DEFAULT, depth: int | None = None) -> dict:
    """
    Begin reading a web address in the background. RETURNS {"ok": True} or {"ok": False, "message"}.
    scope: "page" | "section" | "site"; max_pages up to 500; depth (links followed from the first
    page) up to 5 — default 2 for a section, 3 for a site, 0 for a single page.
    """
    clean = normalize_url(url)
    if not clean:
        return {"ok": False, "message": "That doesn't look like a web address. Try something like https://example.com/guides/"}
    if scope not in SCOPES:
        scope = "section"
    max_pages = max(1, min(int(max_pages or MAX_PAGES_DEFAULT), MAX_PAGES_LIMIT))
    if depth is None:
        depth = {"page": 0, "section": 2, "site": 3}[scope]
    depth = 0 if scope == "page" else max(0, min(int(depth), MAX_DEPTH_LIMIT))
    with _lock:
        if _state.get("state") == "running":
            return {"ok": False, "message": "A web read is already running. Stop it or wait for it to finish."}
        _state.clear()
        _state.update(state="running", start_url=clean, scope=scope, max_pages=max_pages, fetched=0, stored=0,
                      skipped={}, recent=[], current=clean, message="Starting…", started_at=time.time())
    _stop.clear()
    threading.Thread(target=_crawl, args=(clean, scope, max_pages, depth), name="kb-crawl", daemon=True).start()
    return {"ok": True}


def _in_scope(url: str, start_url: str, scope: str) -> bool:
    a, b = urlparse(url), urlparse(start_url)
    if _site(a.hostname) != _site(b.hostname):
        return False
    if scope == "section":
        folder = b.path if b.path.endswith("/") else b.path.rsplit("/", 1)[0] + "/"
        return a.path.startswith(folder) or a.path.rstrip("/") == folder.rstrip("/")
    return True


def _skip_reason(url: str) -> str | None:
    """Addresses that are never fetched (media, archives, login/cart pages)."""
    path = urlparse(url).path.lower()
    ext = Path(path).suffix
    if ext in SKIP_EXT:
        return "not a page"
    if SKIP_PATH.search(path):
        return "login, cart or admin page"
    return None


def _slug(url: str) -> str:
    u = urlparse(url)
    tail = re.sub(r"[^a-z0-9]+", "-", (u.path.strip("/") or "home").lower()).strip("-")[:60] or "page"
    return f"{tail}-{hashlib.sha256(url.encode()).hexdigest()[:8]}"


def _crawl(start_url: str, scope: str, max_pages: int, depth: int) -> None:
    from . import importer, officefiles  # late: importer is a big module and must not import this one

    host_dir = config.DATA_DIR / "web" / re.sub(r"[^a-z0-9.-]", "_", _site(urlparse(start_url).hostname or "site"))
    host_dir.mkdir(parents=True, exist_ok=True)
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1
        _set(skipped=dict(skipped))

    def note(url: str, title: str, result: str) -> None:
        with _lock:
            recent = _state.setdefault("recent", [])
            recent.append({"url": url, "title": title, "result": result})
            del recent[:-8]

    robots: dict[str, robotparser.RobotFileParser | None] = {}
    delay = [MIN_DELAY]
    sitemaps: list[str] = []

    def robots_for(client, url: str):
        u = urlparse(url)
        key = f"{u.scheme}://{u.netloc}"
        if key not in robots:
            rp = robotparser.RobotFileParser()
            try:
                body, _t, _f = _fetch(client, f"{key}/robots.txt", 512 * 1024)
                text = body.decode("utf-8", errors="replace")
                rp.parse(text.splitlines())
                cd = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*")
                if cd:
                    delay[0] = max(MIN_DELAY, min(float(cd), MAX_DELAY))
                sitemaps.extend(re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text))
                robots[key] = rp
            except _Skip:
                robots[key] = None  # no robots.txt (or unreadable): nothing is forbidden
        return robots[key]

    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"},
                          timeout=httpx.Timeout(TIMEOUT), follow_redirects=False) as client:
            queue: deque[tuple[str, int]] = deque([(start_url, 0)])
            seen = {start_url}
            variants: dict[str, int] = {}
            attempts = 0
            stored = 0
            first = True
            if scope == "site":  # a sitemap lists pages that no link on the first page leads to
                robots_for(client, start_url)
                for sm in (sitemaps[:2] or [f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}/sitemap.xml"]):
                    try:
                        body, _t, _f = _fetch(client, sm, 5 * 1024 * 1024)
                    except _Skip:
                        continue
                    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body.decode("utf-8", errors="replace"))
                    for loc in locs[:SITEMAP_LIMIT]:
                        c = canonical(loc.replace("&amp;", "&"))
                        if c not in seen and _in_scope(c, start_url, scope) and not _skip_reason(c):
                            seen.add(c)
                            queue.append((c, 1))
            while queue and stored < max_pages and attempts < max_pages * 3 and not _stop.is_set():
                url, d = queue.popleft()
                attempts += 1
                _set(current=url, message=f"Reading {url}")
                if not first:
                    time.sleep(delay[0])
                is_start = first
                first = False
                if not is_start:
                    rp = robots_for(client, url)
                    if rp is not None and not rp.can_fetch(USER_AGENT, url):
                        skip("blocked by the site's robots.txt")
                        continue
                try:
                    body, ctype, final = _fetch(client, url, DOC_MAX_BYTES)
                except _Skip as why:
                    skip(f"not read: {why}")
                    note(url, "", f"skipped — {why}")
                    continue
                _set(fetched=_state.get("fetched", 0) + 1)
                ext = Path(urlparse(final).path).suffix.lower()
                is_html = ctype in ("text/html", "application/xhtml+xml") or (not ctype and ext in ("", ".html", ".htm"))
                # The copy's name carries a fingerprint of its content: a page that changed since the
                # last read becomes a NEW copy, so the older copy (and the source using it) is untouched.
                body_id = hashlib.sha256(body).hexdigest()[:8]
                try:
                    if is_html:
                        if len(body) > HTML_MAX_BYTES:
                            raise _Skip("it is larger than the size limit")
                        html = body.decode(errors="replace")
                        links = read_links(html)
                        if not is_start and "noindex" in links.robots:
                            raise _Skip("the page asks not to be indexed")
                        text = officefiles._html_text(body)
                        if len(text) < MIN_TEXT_CHARS:
                            raise _Skip("almost no readable text (it may need JavaScript)")
                        title = _page_title(links, final)
                        name = f"{_slug(final)}-{body_id}.html"
                        shown = f"{title} — {_site(urlparse(final).hostname)}"
                    else:
                        ext = ext if ext in DOC_EXT else DOC_TYPES.get(ctype, "")
                        if not ext:
                            raise _Skip("not a page or document the bank can read")
                        links = None
                        title = Path(urlparse(final).path).name or "document"
                        name = f"{_slug(final)}-{body_id}{ext}"
                        shown = f"{title} — {_site(urlparse(final).hostname)}"
                except _Skip as why:
                    skip(str(why))
                    note(url, "", f"skipped — {why}")
                    continue
                path = host_dir / name
                path.write_bytes(body)
                result = importer.add_paths([str(path)], picked=is_start, urls={str(path): final},
                                            names={str(path): shown[:140]}, keep=True)
                if result["added"]:
                    stored += 1
                    _set(stored=stored)
                    note(final, title, "added")
                elif result["duplicates"]:
                    skip("same content as a page already in the bank")
                    note(final, title, "same content already in the bank")
                elif result["already_in_bank"]:
                    skip("already in the bank")
                    note(final, title, "already in the bank")
                elif result["removed_before"]:
                    skip("you removed it earlier")
                    note(final, title, "removed earlier — skipped")
                if links is None or d >= depth or "nofollow" in links.robots:
                    continue
                base = canonical(urljoin(final, links.base)) if links.base else final
                for href in links.links:
                    if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                        continue
                    nxt = canonical(urljoin(base, href))
                    if urlparse(nxt).scheme not in ("http", "https") or nxt in seen:
                        continue
                    if not _in_scope(nxt, start_url, scope) or _skip_reason(nxt):
                        continue
                    pk = urlparse(nxt)._replace(query="", fragment="").geturl()
                    variants[pk] = variants.get(pk, 0) + 1
                    if variants[pk] > VARIANTS_PER_PATH:
                        continue
                    seen.add(nxt)
                    queue.append((nxt, d + 1))
        stopped = _stop.is_set()
        total = _state.get("stored", 0)
        left = len(queue)
        msg = (f"Stopped. {total} page{'s' if total != 1 else ''} added." if stopped else
               f"Finished. {total} page{'s' if total != 1 else ''} added"
               + (f"; {left} more found but not read (page limit reached)." if left and stored >= max_pages else "."))
        _set(state="stopped" if stopped else "done", current=None, message=msg, finished_at=time.time())
    except Exception as exc:  # never leave the window waiting on a crashed crawl
        _set(state="error", current=None, message=f"The web read stopped: {exc}", finished_at=time.time())
