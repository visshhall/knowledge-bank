"""
tools.py — Phase 6 analyst tools: IOCs, MITRE ATT&CK techniques, query library.

WHAT:  extract_iocs(text) → indicators found in any pasted text, grouped by
         type: IPv4, domains, URLs, emails, MD5/SHA-1/SHA-256 hashes, CVEs,
         MITRE technique IDs. Defanged input ("1[.]2[.]3[.]4", "hxxp://",
         "evil[.]com") is recognised; each value comes back both refanged
         (usable) and defanged (safe to paste into a report/chat).
       bank_iocs() → the same, across every passage in the bank, with where
         each indicator appears.
       mitre() → every ATT&CK technique ID mentioned in the bank with its
         official name and tactics (bundled offline: data/mitre_techniques.json,
         from MITRE's own ATT&CK data), how often it's mentioned, and where.
       queries() → the bank's query library: every KQL / Splunk SPL query
         found in your documents, de-duplicated, with its language, the table
         or index it reads, and the file/page/topic it came from.
WHY:   The owner works as a SOC analyst: pulling indicators out of an alert,
       seeing which ATT&CK techniques his material covers, and reusing tested
       queries are daily tasks. All of this runs offline on the bank.
WHEN:  POST /tools/iocs, GET /tools/bank-iocs, GET /tools/mitre,
       GET /tools/queries (server.py), from the Tools screen (Tools.jsx).
CONNECTED TO: db.py (passages, sources, topic_passages, topics),
       chunking.py (_CODE_START: what counts as a query line),
       data/mitre_techniques.json, Tools.jsx.
"""

from __future__ import annotations

import ipaddress
import json
import re
from functools import lru_cache
from pathlib import Path

from . import chunking, db

# --- Indicator patterns -----------------------------------------------------
_DOT = r"(?:\.|\[\.\]|\(\.\)|\[dot\]|\(dot\))"
_RE = {
    "url": re.compile(r"\b(?:h[tx]{2}ps?|ftp)(?::|\[:\])//(?:\[\.\]|\[dot\]|[^\s\"'<>\[\]\)])+", re.I),
    "email": re.compile(rf"\b[\w.+-]+(?:@|\[@\]|\[at\])[\w-]+(?:{_DOT}[\w-]+)+\b", re.I),
    "ipv4": re.compile(rf"\b(?:\d{{1,3}}{_DOT}){{3}}\d{{1,3}}\b"),
    "sha256": re.compile(r"\b[a-f0-9]{64}\b", re.I),
    "sha1": re.compile(r"\b[a-f0-9]{40}\b", re.I),
    "md5": re.compile(r"\b[a-f0-9]{32}\b", re.I),
    "cve": re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I),
    "mitre": re.compile(r"\bT\d{4}(?:\.\d{3})?\b"),
    "domain": re.compile(rf"\b(?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?{_DOT})+[a-z]{{2,24}}\b", re.I),
}
# Things that look like domains but are file names / code ("update.exe",
# "System.Management") — left out of the domain list.
_NOT_TLD = {"exe", "dll", "sys", "ps1", "bat", "cmd", "vbs", "js", "jar", "py", "sh", "txt", "log", "csv",
            "pdf", "doc", "docx", "xls", "xlsx", "zip", "rar", "7z", "png", "jpg", "jpeg", "gif", "evtx",
            "json", "xml", "yml", "yaml", "ini", "cfg", "msi", "lnk", "hta", "iso", "img", "tmp", "dat",
            "db", "local", "lan", "internal", "corp", "md", "html", "htm", "aspx", "php", "config"}
TYPES = ["ipv4", "domain", "url", "email", "sha256", "sha1", "md5", "cve", "mitre"]
LABELS = {"ipv4": "IP addresses", "domain": "Domains", "url": "URLs", "email": "Email addresses",
          "sha256": "SHA-256 hashes", "sha1": "SHA-1 hashes", "md5": "MD5 hashes", "cve": "CVEs",
          "mitre": "MITRE techniques"}


def refang(v: str) -> str:
    v = re.sub(r"\[\.\]|\(\.\)|\[dot\]|\(dot\)", ".", v, flags=re.I)
    v = re.sub(r"\[@\]|\[at\]", "@", v, flags=re.I)
    v = re.sub(r"^hxxp", "http", v, flags=re.I)
    return v.replace("[:]", ":")


def defang(v: str, kind: str) -> str:
    if kind in ("sha256", "sha1", "md5", "cve", "mitre"):
        return v
    v = re.sub(r"^http", "hxxp", v, flags=re.I)
    return v.replace(".", "[.]").replace("@", "[@]") if kind != "url" else re.sub(
        r"(?<=//)([^/]+)", lambda m: m.group(1).replace(".", "[.]"), v)


def _private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
    except ValueError:
        return False


def extract_iocs(text: str) -> dict:
    """
    RETURNS {"groups": [{type, label, items: [{value, defanged, count,
    note}]}], "total"}. Hashes are matched longest first so a SHA-256 isn't
    also reported as an MD5; domains inside URLs/emails aren't repeated.
    """
    text = text or ""
    found: dict[str, dict[str, int]] = {t: {} for t in TYPES}
    taken: list[tuple[int, int]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < y and x < b for x, y in taken)

    for kind in ["url", "email", "sha256", "sha1", "md5", "cve", "mitre", "ipv4", "domain"]:
        for m in _RE[kind].finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            v = refang(m.group(0)).rstrip(".,;:")
            if kind == "ipv4" and any(int(p) > 255 for p in v.split(".")):
                continue
            if kind == "domain":
                # "System.Management", "Get-Process.Name": code, not domains —
                # real domains in text are written in lower case.
                if re.search(r"\.[A-Z]", m.group(0)):
                    continue
                tld = v.rsplit(".", 1)[-1].lower()
                if tld in _NOT_TLD or v.replace(".", "").isdigit() or "." not in v:
                    continue
                v = v.lower()
            if kind in ("md5", "sha1", "sha256"):
                v = v.lower()
            if kind == "cve":
                v = v.upper()
            taken.append((m.start(), m.end()))
            found[kind][v] = found[kind].get(v, 0) + 1
    groups, total = [], 0
    for kind in TYPES:
        if not found[kind]:
            continue
        items = []
        for v, n in sorted(found[kind].items(), key=lambda kv: (-kv[1], kv[0])):
            note = ""
            if kind == "ipv4" and _private(v):
                note = "private / internal"
            if kind == "mitre":
                t = _mitre_names().get(v)
                note = (f"{t['name']} (retired ID in current ATT&CK)" if t.get("retired") else t["name"]) \
                    if t else "not in the bundled ATT&CK list"
            items.append({"value": v, "defanged": defang(v, kind), "count": n, "note": note})
        total += len(items)
        groups.append({"type": kind, "label": LABELS[kind], "items": items})
    return {"groups": groups, "total": total}


def bank_iocs(limit_refs: int = 3) -> dict:
    """Indicators across the whole bank, each with where it appears."""
    where: dict[tuple[str, str], list] = {}
    with db.connect() as conn:
        rows = conn.execute("SELECT p.id, p.text, p.page_number, p.source_id, s.file_name FROM passages p "
                            "JOIN sources s ON s.id = p.source_id").fetchall()
    for r in rows:
        for g in extract_iocs(r["text"])["groups"]:
            if g["type"] == "mitre":
                continue  # the MITRE tab covers these
            for it in g["items"]:
                refs = where.setdefault((g["type"], it["value"]), [])
                if len(refs) < limit_refs:
                    refs.append({"passage_id": r["id"], "file_name": r["file_name"],
                                 "page": r["page_number"], "source_id": r["source_id"]})
                else:
                    refs.append(None)
    groups = []
    for kind in TYPES:
        items = [{"value": v, "defanged": defang(v, kind), "count": len(refs),
                  "note": "private / internal" if kind == "ipv4" and _private(v) else "",
                  "where": [x for x in refs if x]}
                 for (k, v), refs in where.items() if k == kind]
        if items:
            items.sort(key=lambda x: (-x["count"], x["value"]))
            groups.append({"type": kind, "label": LABELS[kind], "items": items})
    return {"groups": groups, "total": sum(len(g["items"]) for g in groups)}


@lru_cache(maxsize=1)
def _mitre_names() -> dict:
    p = Path(__file__).parent / "data" / "mitre_techniques.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["techniques"]
    except Exception:
        return {}


def mitre() -> dict:
    """ATT&CK techniques mentioned in the bank, grouped by tactic, with names and places."""
    names = _mitre_names()
    hits: dict[str, dict] = {}
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT p.id, COALESCE(p.cluster_id, p.id) AS point_id, p.text, p.page_number, p.source_id,
                      s.file_name, t.id AS topic_id, t.title AS topic_title
               FROM passages p JOIN sources s ON s.id = p.source_id
               LEFT JOIN topic_passages tp ON tp.passage_id = p.id LEFT JOIN topics t ON t.id = tp.topic_id
               WHERE p.text LIKE '%T1%'""").fetchall()
    for r in rows:
        for tid in set(_RE["mitre"].findall(r["text"])):
            h = hits.setdefault(tid, {"id": tid, "count": 0, "where": [], "topics": {}})
            h["count"] += 1
            if len(h["where"]) < 5:
                h["where"].append({"file_name": r["file_name"], "page": r["page_number"], "source_id": r["source_id"],
                                   "topic_id": r["topic_id"], "point_id": r["point_id"]})
            if r["topic_id"]:
                h["topics"][r["topic_id"]] = r["topic_title"]
    techniques = []
    for tid, h in hits.items():
        base = tid.split(".")[0]
        info = names.get(tid) or names.get(base) or {}
        if tid in names:
            name = names[tid]["name"] + (" (retired ID in current ATT&CK)" if names[tid].get("retired") else "")
        elif base in names:
            name = f"{names[base]['name']} (sub-technique not in bundled list)"
        else:
            name = ""
        techniques.append({"id": tid, "name": name, "known": tid in names, "tactics": info.get("tactics", []),
                           "count": h["count"], "where": h["where"],
                           "topics": [{"id": k, "title": v} for k, v in h["topics"].items()],
                           "url": f"https://attack.mitre.org/techniques/{tid.replace('.', '/')}/"})
    techniques.sort(key=lambda t: (-t["count"], t["id"]))
    tactics: dict[str, int] = {}
    for t in techniques:
        for tac in t["tactics"] or ["unknown"]:
            tactics[tac] = tactics.get(tac, 0) + 1
    order = ["reconnaissance", "resource-development", "initial-access", "execution", "persistence",
             "privilege-escalation", "defense-evasion", "stealth", "credential-access", "discovery", "lateral-movement",
             "collection", "command-and-control", "exfiltration", "impact", "unknown"]
    # Known tactics in kill-chain order; any newer ATT&CK tactic names after them.
    ordered = [k for k in order if k in tactics] + sorted(k for k in tactics if k not in order)
    return {"techniques": techniques,
            "tactics": [{"tactic": k, "count": tactics[k]} for k in ordered],
            "catalogue": {"count": len(names), "source": "MITRE ATT&CK Enterprise, bundled offline"}}


def _lang(q: str) -> str:
    low = q.lower()
    if re.search(r"\bindex\s*=|\|\s*(stats|eval|rex|table|dedup|tstats)\b", low):
        return "SPL"
    return "KQL"


def queries() -> dict:
    """The bank's query library: KQL / SPL blocks found in passages, de-duplicated."""
    seen: dict[str, dict] = {}
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT p.id, COALESCE(p.cluster_id, p.id) AS point_id, p.text, p.page_number, p.source_id,
                      p.section, s.file_name, t.id AS topic_id, t.title AS topic_title
               FROM passages p JOIN sources s ON s.id = p.source_id
               LEFT JOIN topic_passages tp ON tp.passage_id = p.id LEFT JOIN topics t ON t.id = tp.topic_id
               WHERE p.text LIKE '%|%' OR p.text LIKE '%index=%'""").fetchall()
    for r in rows:
        block: list[str] = []
        for line in r["text"].split("\n") + [""]:
            if chunking._CODE_START.match(line) or (block and line.strip().startswith("|")):
                block.append(line.strip())
                continue
            if len(block) >= 1 and any(l.startswith("|") for l in block):
                q = "\n".join(block)
                norm = re.sub(r"\s+", " ", q.lower())
                if norm not in seen:
                    first = block[0].lstrip("| ").split()[0] if block[0].lstrip("| ") else ""
                    seen[norm] = {"query": q, "lang": _lang(q),
                                  "table": first if not block[0].startswith("|") else "",
                                  "lines": len(block), "file_name": r["file_name"], "page": r["page_number"],
                                  "source_id": r["source_id"], "section": r["section"],
                                  "topic_id": r["topic_id"], "topic_title": r["topic_title"],
                                  "point_id": r["point_id"], "also": 0}
                else:
                    seen[norm]["also"] += 1
            block = []
    # A fragment that is part of a longer query found elsewhere isn't listed twice.
    norms = list(seen)
    for n in norms:
        if any(n != m and n in m for m in norms):
            seen.pop(n, None)
    items = sorted(seen.values(), key=lambda x: (x["lang"], x["table"].lower(), x["query"]))
    return {"queries": items, "total": len(items)}
