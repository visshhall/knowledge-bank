"""
test_crawler.py — checks for crawler.py (v0.13 read a web page / section / site) and importer.add_text.
Plain asserts: run with   python -I tests/test_crawler.py   from the engine folder.
WHAT: a small test website is served from this computer (crawler.ALLOW_PRIVATE is switched on only here).
      Checked: single page, section scope, site scope with sitemap, depth limit, page limit, same-site only
      (other sites and www. handling), robots.txt, noindex, tracking parameters, query-variant cap,
      login/cart paths, pages without text, documents (txt) linked from a page, unchanged page read twice,
      stop button, address checks (only http/https, private addresses refused), pasted text, and that removing
      a web source deletes the app's own copy of it.
WHY:  the crawler is the one part that talks to the internet; its rules (polite, same site, never local)
      must hold. No internet and no AI are used.
WHEN: before every release that touches crawler.py or the import of web pages.
"""
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["KB_DATA_DIR"] = tempfile.mkdtemp(prefix="kb-crawl-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import config, crawler, db, importer  # noqa: E402

db.init_db()
importer._ensure_worker = lambda: None   # registering sources is enough here; extraction is tested elsewhere
crawler.ALLOW_PRIVATE = True
crawler.MIN_DELAY = 0.0

LONG = "This sentence is real readable text about planters and lamps for the page. " * 6
hits: list[str] = []


def page(title, body, links=(), extra_head=""):
    anchors = "".join(f'<a href="{h}">link</a>' for h in links)
    return (f"<html><head><title>{title}</title>{extra_head}</head><body><nav>menu menu menu</nav>"
            f"<main><h1>{title}</h1><p>{body}</p>{anchors}</main><footer>footer</footer></body></html>").encode()


SITE = {
    "/": page("Home", LONG, ["/guides/", "/about", "/shop?utm_source=x&sort=a", "/login", "/cart/1", "http://other.invalid/x",
                              "/private/secret", "/empty", "/noindex", "/files/notes.txt", "/pic.png"]),
    "/guides/": page("Guides", LONG, ["/guides/a", "/guides/b?utm_campaign=z", "/about"]),
    "/guides/a": page("Guide A", LONG + " alpha", ["/guides/deep/1"]),
    "/guides/b": page("Guide B", LONG + " beta"),
    "/guides/deep/1": page("Deep one", LONG + " deep", ["/guides/deep/2"]),
    "/guides/deep/2": page("Deep two", LONG + " deeper"),
    "/about": page("About", LONG + " about us"),
    "/shop": page("Shop", LONG + " shop", [f"/shop?filter={i}" for i in range(12)]),
    "/private/secret": page("Secret", LONG + " secret"),
    "/empty": b"<html><head><title>Empty</title></head><body><div id=app></div><script>x()</script></body></html>",
    "/noindex": page("Hidden", LONG + " hidden", extra_head='<meta name="robots" content="noindex">'),
    "/login": page("Login", LONG + " login"),
    "/cart/1": page("Cart", LONG + " cart"),
    "/files/notes.txt": ("Plain text notes about material choices for large planters. " * 8).encode(),
    "/orphan": page("Orphan", LONG + " orphan only in sitemap"),
    "/robots.txt": b"User-agent: *\nDisallow: /private/\nSitemap: SITEMAP\n",
}
SITE_MOVED = {"/old": "/about"}
state = {"changed": False}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path
        hits.append(path)
        base = path.split("?")[0]
        if base == "/sitemap.xml":
            body = (f"<urlset><url><loc>http://127.0.0.1:{PORT}/orphan</loc></url>"
                    f"<url><loc>http://127.0.0.1:{PORT}/about</loc></url></urlset>").encode()
            return self._send(200, body, "application/xml")
        if base in SITE_MOVED:
            self.send_response(301)
            self.send_header("Location", SITE_MOVED[base])
            self.end_headers()
            return
        if base == "/robots.txt":
            return self._send(200, SITE[base].replace(b"SITEMAP", f"http://127.0.0.1:{PORT}/sitemap.xml".encode()), "text/plain")
        if base == "/pic.png":
            return self._send(200, b"\x89PNG....", "image/png")
        if base == "/about" and state["changed"]:
            return self._send(200, page("About", LONG + " about us — now changed"), "text/html")
        if base in SITE:
            ctype = "text/plain" if base.endswith(".txt") else "text/html"
            return self._send(200, SITE[base], ctype)
        self._send(404, b"nope", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


def crawl(url, **kw):
    r = crawler.start(url, **kw)
    assert r["ok"], r
    for _ in range(400):
        if crawler.status()["state"] != "running":
            break
        time.sleep(0.05)
    st = crawler.status()
    assert st["state"] in ("done", "stopped"), st
    return st


def urls_in_bank():
    with db.connect() as c:
        return sorted(r["url"] for r in c.execute("SELECT url FROM sources WHERE url IS NOT NULL"))


def wipe():
    with db.connect() as c:
        c.execute("DELETE FROM sources")
        c.execute("DELETE FROM removed_files")
        c.execute("DELETE FROM duplicate_files")
    hits.clear()


# --- address handling -----------------------------------------------------------------------------
assert crawler.normalize_url("example.com/a#top") == "https://example.com/a"
assert crawler.normalize_url("HTTP://Example.com:80/x?utm_source=a&b=2&a=1") == "http://example.com/x?a=1&b=2"
for bad in ("", "ftp://x.com", "file:///etc/passwd", "javascript:alert(1)", "two words.com", "http://"):
    assert crawler.normalize_url(bad) is None, bad
assert crawler._site("www.Example.com") == "example.com"
assert crawler.start("file:///etc/passwd")["ok"] is False
crawler.ALLOW_PRIVATE = False
assert crawler.blocked_address("127.0.0.1") and crawler.blocked_address("localhost")
assert crawler.blocked_address("192.168.1.1") and crawler.blocked_address("10.0.0.5") and crawler.blocked_address("169.254.169.254")
assert crawler.blocked_address("no-such-host.invalid")
crawler.ALLOW_PRIVATE = True

# --- one page only ----------------------------------------------------------------------------------
st = crawl(BASE + "/guides/a", scope="page")
assert st["stored"] == 1 and urls_in_bank() == [BASE + "/guides/a"], urls_in_bank()
with db.connect() as c:
    row = c.execute("SELECT * FROM sources").fetchone()
assert row["keep_anyway"] == 1 and row["file_name"].startswith("Guide A") and row["file_type"] == "doc"
assert Path(row["original_path"]).exists() and "web" in Path(row["original_path"]).parts
assert not any(h.startswith("/guides/deep") for h in hits)

# --- the same page read twice adds nothing; a changed page is a new copy ---------------------------------
st = crawl(BASE + "/guides/a", scope="page")
assert st["stored"] == 0 and len(urls_in_bank()) == 1
wipe()

# --- section scope: only under /guides/, robots + tracking + depth ------------------------------------
st = crawl(BASE + "/guides/", scope="section", depth=1)
got = urls_in_bank()
assert got == [BASE + "/guides/", BASE + "/guides/a", BASE + "/guides/b"], got   # depth 1: deep/1 is two links away
assert "/about" not in "".join(got), "outside the folder"
st = crawl(BASE + "/guides/", scope="section", depth=3)                           # deeper now; the rest are already in
assert BASE + "/guides/deep/2" in urls_in_bank()
assert not any("utm_" in u for u in urls_in_bank())
wipe()

# --- site scope: whole site, rules applied ---------------------------------------------------------------
st = crawl(BASE + "/", scope="site", max_pages=100)
got = urls_in_bank()
assert BASE + "/about" in got and BASE + "/orphan" in got, "sitemap page found"
assert BASE + "/private/secret" not in got and "/private/secret" not in "".join(hits[1:]) , "robots.txt respected"
assert BASE + "/login" not in got and BASE + "/cart/1" not in got
assert BASE + "/empty" not in got and BASE + "/noindex" not in got
assert BASE + "/files/notes.txt" in got, "a linked text document is read"
assert not any("other.invalid" in u for u in got) and "/pic.png" not in hits
assert st["skipped"].get("blocked by the site's robots.txt") == 1, st["skipped"]
assert any("almost no readable text" in k for k in st["skipped"]), st["skipped"]
assert any("noindex" in k or "indexed" in k for k in st["skipped"]), st["skipped"]
shop = [u for u in got if "/shop" in u]
assert 1 <= len(shop) <= crawler.VARIANTS_PER_PATH, shop                           # filter variants capped
wipe()

# --- page limit ----------------------------------------------------------------------------------------
st = crawl(BASE + "/", scope="site", max_pages=3)
assert st["stored"] == 3 and len(urls_in_bank()) == 3 and "page limit" in st["message"], st
wipe()

# --- a page that changed since the last read becomes a new copy and replaces the old by name -------------
crawl(BASE + "/about", scope="page")
assert len(urls_in_bank()) == 1
state["changed"] = True
st = crawl(BASE + "/about", scope="page")
assert st["stored"] == 1, st
with db.connect() as c:
    paths = {r["original_path"] for r in c.execute("SELECT original_path FROM sources")}
assert len(paths) == 2 and all(Path(p).exists() for p in paths)
state["changed"] = False
wipe()

# --- redirect is followed and the final address is stored -------------------------------------------------
st = crawl(BASE + "/old", scope="page")
assert urls_in_bank() == [BASE + "/about"], urls_in_bank()
wipe()

# --- Stop keeps what was read --------------------------------------------------------------------------------
crawler.MIN_DELAY = 0.3
r = crawler.start(BASE + "/", scope="site", max_pages=100)
time.sleep(0.9)
crawler.stop()
for _ in range(100):
    if crawler.status()["state"] != "running":
        break
    time.sleep(0.05)
st = crawler.status()
assert st["state"] == "stopped" and 1 <= st["stored"] < 10, st
assert crawler.start(BASE + "/", scope="page")["ok"]            # a new read can start afterwards
for _ in range(100):
    if crawler.status()["state"] != "running":
        break
    time.sleep(0.05)
crawler.MIN_DELAY = 0.0
wipe()

# --- only one read at a time ----------------------------------------------------------------------------------
crawler.MIN_DELAY = 0.4
assert crawler.start(BASE + "/", scope="site", max_pages=100)["ok"]
assert crawler.start(BASE + "/", scope="page")["ok"] is False
crawler.stop()
for _ in range(100):
    if crawler.status()["state"] != "running":
        break
    time.sleep(0.05)
crawler.MIN_DELAY = 0.0
wipe()

# --- an unreachable site is explained, not crashed ------------------------------------------------------------------
st = crawl("http://127.0.0.1:1/", scope="page")
assert st["stored"] == 0 and any("could not be reached" in k for k in st["skipped"]), st

# --- private addresses are refused even when typed -------------------------------------------------------------------
crawler.ALLOW_PRIVATE = False
st = crawl("http://127.0.0.1:%d/" % PORT, scope="page")
assert st["stored"] == 0 and any("private network" in k or "this computer" in k for k in st["skipped"]), st
crawler.ALLOW_PRIVATE = True

# --- pasted text -----------------------------------------------------------------------------------------------------
assert importer.add_text("", "too short")["ok"] is False
r = importer.add_text("Planter care notes", "Water the planter lightly twice a week and keep it out of direct afternoon sun.")
assert r["ok"] and r["added"] == 1, r
again = importer.add_text("Planter care notes", "Water the planter lightly twice a week and keep it out of direct afternoon sun.")
assert again["added"] == 0 and "already in the bank" in again["message"], again
with db.connect() as c:
    note = c.execute("SELECT * FROM sources WHERE file_name = 'Planter care notes'").fetchone()
assert note["keep_anyway"] == 1 and note["url"] is None and "notes" in Path(note["original_path"]).parts
assert Path(note["original_path"]).read_text(encoding="utf-8").startswith("# Planter care notes")

# --- removing a web source or a note deletes the app's own copy, but never a file from his disk -------------------------
crawl(BASE + "/guides/a", scope="page")
with db.connect() as c:
    web = c.execute("SELECT id, original_path FROM sources WHERE url IS NOT NULL").fetchone()
mine = Path(os.environ["KB_DATA_DIR"]) / "mine.txt"
mine.write_text("A file the owner keeps on his own disk, with enough words to be a real file here.", encoding="utf-8")
assert importer.add_paths([str(mine)], picked=True)["added"] == 1
with db.connect() as c:
    own_id = c.execute("SELECT id FROM sources WHERE original_path = ?", (str(mine),)).fetchone()["id"]
assert importer.remove_sources([web["id"], note["id"], own_id])["removed"] == 3
assert not Path(web["original_path"]).exists() and not Path(note["original_path"]).exists()
assert mine.exists(), "a file from his own disk is never deleted"
assert any(x["url"] for x in importer.library()) is False

print("test_crawler: all checks passed")
server.shutdown()
