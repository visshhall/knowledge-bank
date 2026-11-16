"""
websearch.py — v0.16 find web pages about a topic, for the app's own learning (learner.py).

WHAT:  search(query) asks DuckDuckGo's plain-HTML "lite" page for results and returns up to `limit`
       clean page addresses. No account, no key, nothing is sent except the search words. Results that are
       social media, video, shopping or login pages are dropped (they hold little readable text and the
       crawler would skip most anyway), and so are repeats from the same site (one page per site per search).
       online() is a cheap "can we reach the search page" check.
WHY:   The owner chose "fully automatic" web learning: the app finds pages itself instead of waiting for
       an address. A search page is the simplest way to turn "learn about Sentinel KQL" into addresses.
       Kept in its own small file so the search provider can be swapped without touching anything else.
LIMITS: This reads a public search page, not a paid search service; its layout can change or it can refuse
       a burst of requests. If that happens search() returns [] and learner.py waits and tries later — the
       rest of the app is unaffected. Only plain addresses leave this file; the crawler (crawler.py) then
       applies robots.txt, same-site and private-address rules to every page.
WHEN:  Called by learner.py about once per topic, at most a few times per hour.
CONNECTED TO: learner.py (the only caller), httpx (the same HTTP library crawler.py uses), __init__ (version in
       the User-Agent so sites can see what is reading them).
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

import httpx

from . import __version__

SEARCH_URL = "https://lite.duckduckgo.com/lite/"
USER_AGENT = f"Mozilla/5.0 (compatible; KnowledgeBank/{__version__}; personal offline knowledge app)"
TIMEOUT = 15.0

# Sites that are mostly not readable article text (or need a login). Matched against the end of the host name.
SKIP_SITES = (
    "youtube.com", "youtu.be", "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "pinterest.com", "linkedin.com", "reddit.com", "quora.com", "amazon.com", "amazon.in", "flipkart.com",
    "ebay.com", "etsy.com", "duckduckgo.com", "google.com", "bing.com", "t.me", "wa.me",
)

_UDDG = re.compile(r'uddg=([^&"\'<>\s]+)')


def _skipped(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return any(host == s or host.endswith("." + s) for s in SKIP_SITES)


def parse_results(html: str, limit: int = 5) -> list[str]:
    """Page addresses found in a DuckDuckGo lite results page (in order, one per site, skip-list applied)."""
    out: list[str] = []
    sites: set[str] = set()
    for raw in _UDDG.findall(html):
        url = unquote(raw)
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname or _skipped(u.hostname):
            continue
        site = u.hostname.lower().removeprefix("www.")
        if site in sites:
            continue
        sites.add(site)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def search(query: str, limit: int = 5) -> list[str]:
    """Up to `limit` page addresses for `query`; [] when offline, refused or nothing found."""
    query = " ".join((query or "").split())[:200]
    if not query:
        return []
    try:
        r = httpx.get(SEARCH_URL, params={"q": query}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
                      follow_redirects=True)
        if r.status_code != 200:
            return []
        return parse_results(r.text, limit)
    except httpx.HTTPError:
        return []


def online() -> bool:
    """True if the search page answers (used to skip a learning round quietly when the laptop is offline)."""
    try:
        return httpx.get(SEARCH_URL, params={"q": "test"}, headers={"User-Agent": USER_AGENT}, timeout=8.0).status_code < 500
    except httpx.HTTPError:
        return False
