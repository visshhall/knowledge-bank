"""
titles.py — readable names and categories for files (v0.9).

WHAT:  1. needs_title(file_name) → True for unhelpful names such as
          "1733744110377.pdf", "document (3).pdf", "Scan_0012.pdf",
          "IMG_2041.png", "download.pdf".
       2. guess_title(...) → a readable title from the file itself:
            a. the PDF's own title field (if it isn't generic),
            b. the document's first heading (chunking found it while cutting
               passages — passages.section of the first passage),
            c. the first line of page 1 that looks like a title
               (3–14 words, not a sentence),
          cleaned up ("Microsoft Word - " prefixes, trailing ".docx", extra
          spaces) and kept under 90 characters.
       3. categorise(text) → up to 2 categories from a fixed list (SIEM &
          Detection, Endpoint, Identity & Access, Cloud, Network, Email &
          Phishing, Malware, Incident Response, Threat Intel & Hunting,
          Vulnerabilities & AppSec, Governance & Compliance).

WHY:   Owner chose "real names for files" and "automatic categories"
       (15 Nov 2026). Many of his PDFs are LinkedIn downloads named only by
       numbers, which made Library and citations unreadable, and with dozens
       of files he needs to filter by subject.

HOW:   Rules and vocabularies only (no AI): instant, offline, repeatable.
       The title is DISPLAY ONLY — the file on disk keeps its name.

WHEN:  importer._name_and_tag() after each file is read; once for every file
       already in the bank (importer.name_existing()).

CONNECTED TO: importer.py (caller), Library.jsx (title, chips, filter),
       every citation query (COALESCE(s.title, s.file_name)).
"""

import re
from pathlib import Path

_GENERIC_NAME = re.compile(
    r"^(\d[\d _.-]*|document|doc|download|downloads|file|untitled|new|scan|scanned|img|image|"
    r"screenshot|screen ?shot|photo|pdf|print|output|export|copy|presentation|slides?)"
    r"([ _.-]*(\(\d+\)|\d+|copy|final|v\d+))*$",
    re.I,
)
_GENERIC_TITLE = re.compile(r"^(untitled|microsoft (word|powerpoint)|powerpoint presentation|"
                            r"slide \d+|document\d*|pdf|title|presentation\d*)$", re.I)


def needs_title(file_name: str) -> bool:
    """Is this file name unhelpful to a reader?"""
    stem = Path(file_name).stem.strip()
    if _GENERIC_NAME.match(stem):
        return True
    letters = sum(c.isalpha() for c in stem)
    return letters < 4 or sum(c.isdigit() for c in stem) > letters  # "IMG_20241102_1534"


def _clean(t: str) -> str:
    t = re.sub(r"^(microsoft (word|powerpoint|excel)\s*-\s*)", "", t.strip(), flags=re.I)
    t = re.sub(r"\.(docx?|pptx?|pdf|xlsx?)$", "", t, flags=re.I)
    t = re.sub(r"[#*_`|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—:·•")
    if len(t) > 90:
        t = t[:90].rsplit(" ", 1)[0] + "…"
    return _readable_case(t)


_KEEP_UPPER = {"rdp", "kql", "spl", "mfa", "soc", "siem", "edr", "xdr", "ioc", "iocs", "ttp", "ttps", "apt", "dns",
               "ip", "tcp", "udp", "vpn", "aws", "gcp", "m365", "ad", "id", "it", "api", "sql", "xss", "cve",
               "nist", "iso", "gdpr", "ntlm", "smb", "ssh", "tls", "ssl", "dlp", "waf", "c2", "dfir", "soar",
               "mitre", "att&ck", "ueba", "ids", "ips", "ldap", "url", "uac", "lsass"}


def _readable_case(t: str) -> str:
    """'USE CASE 3: RDP BRUTE FORCE' → 'Use Case 3: RDP Brute Force'."""
    letters = [c for c in t if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return t
    out = []
    for w in t.split():
        core = w.strip(":,.;()").lower()
        out.append(w.upper() if core in _KEEP_UPPER else w.capitalize())
    return " ".join(out)


def _good(t: str) -> bool:
    words = t.split()
    return (2 <= len(words) <= 16 and sum(c.isalpha() for c in t) >= 6
            and not _GENERIC_TITLE.match(t) and not re.search(r"https?://|www\.|@", t))


def guess_title(file_name: str, meta_title: str | None, first_heading: str | None,
                first_page: str | None) -> str | None:
    """Best readable title, or None if nothing better than the file name."""
    for cand in (meta_title, first_heading):
        if cand and _good(_clean(cand)) and _clean(cand).lower() != Path(file_name).stem.lower():
            return _clean(cand)
    for line in (first_page or "").splitlines()[:12]:
        c = _clean(line)
        if 3 <= len(c.split()) <= 14 and _good(c) and not re.search(r"[.!?]$", c):
            return c
    return None


# --- categories ---------------------------------------------------------------
CATEGORIES: dict[str, list[str]] = {
    "SIEM & Detection": ["siem", "sentinel", "splunk", "qradar", "kql", "spl", "kusto", "analytics rule",
                         "detection rule", "sigma", "correlation", "use case", "alert", "log source",
                         "securityevent", "signinlogs", "workbook", "watchlist", "soar", "playbook"],
    "Endpoint": ["edr", "xdr", "defender for endpoint", "crowdstrike", "sysmon", "process", "endpoint",
                 "registry", "powershell", "lolbin", "deviceprocessevents", "antivirus", "host"],
    "Identity & Access": ["entra", "azure ad", "active directory", "kerberos", "ntlm", "mfa", "multi-factor",
                          "conditional access", "sign-in", "signin", "okta", "ldap", "privilege", "credential",
                          "password", "identity", "golden ticket", "kerberoasting", "pass-the-hash"],
    "Cloud": ["azure", "aws", "gcp", "cloud", "tenant", "subscription", "m365", "office 365", "s3",
              "iam role", "defender for cloud", "kubernetes", "container"],
    "Network": ["firewall", "subnet", "cidr", "tcp", "udp", "dns", "vpn", "proxy", "packet", "port",
                "ids", "ips", "router", "vlan", "netflow", "zeek", "suricata", "snort", "ip address"],
    "Email & Phishing": ["phishing", "spearphishing", "email", "spf", "dkim", "dmarc", "attachment",
                         "exchange", "mailbox", "spoofing", "bec", "business email compromise"],
    "Malware": ["malware", "ransomware", "trojan", "rootkit", "worm", "payload", "sandbox", "yara",
                "reverse engineering", "static analysis", "dynamic analysis", "c2", "command and control"],
    "Incident Response": ["incident response", "containment", "eradication", "recovery", "triage",
                          "forensics", "forensic", "dfir", "lessons learned", "escalation", "incident"],
    "Threat Intel & Hunting": ["threat intelligence", "threat hunting", "hunting", "mitre", "att&ck",
                               "technique", "sub-technique", "tactic",
                               "ttp", "apt", "threat actor", "ioc", "indicator", "adversary", "kill chain"],
    "Vulnerabilities & AppSec": ["cve", "vulnerability", "patch", "cvss", "owasp", "sql injection", "xss",
                                 "pentest", "penetration test", "exploit", "zero-day", "scanner", "nessus"],
    "Governance & Compliance": ["iso 27001", "nist", "gdpr", "policy", "audit", "compliance", "risk",
                                "governance", "control", "framework", "soc 2", "pci"],
}


def categorise(text: str, top: int = 2) -> list[str]:
    """Up to `top` categories, each needing several different matching terms."""
    low = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    scored = []
    for cat, terms in CATEGORIES.items():
        hits = [t for t in terms if re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", low)]
        count = sum(len(re.findall(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", low)) for t in hits)
        if len(hits) >= 3 or (len(hits) >= 2 and count >= 6):
            scored.append((len(hits) * 3 + min(count, 40), cat))
    scored.sort(reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    return [c for s, c in scored[:top] if s >= best * 0.6]
