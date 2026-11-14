"""
relevance.py — decides whether a file is about cybersecurity (v0.8.2).

WHAT:  assess(text) → {"verdict": "cyber" | "not" | "unsure", "strong": [...],
       "weak": [...], "words": n, "reason": "..."}.
       importer.py calls it on a SAMPLE of each new file BEFORE the slow
       work (full OCR, picture reading). A file whose verdict is "not" is
       set aside (status 'set_aside'): its text is not kept, it is never
       imported again, and Library offers "Keep anyway".

WHY:   Owner: "any PDF with content not related to cybersecurity should be
       removed automatically — I have multiple PDFs being scanned that are
       not related." Unrelated files cost OCR time, end up as odd topics,
       and dilute answers.

HOW:   A fixed vocabulary, no AI — so it is instant, works with the AI
       engine off, and always gives the same answer for the same file.
         - STRONG terms only occur in security writing (malware, phishing,
           SIEM, CVE-2024-…, T1059, Event ID 4625, KQL, ransomware…).
         - WEAK terms are common in security writing but also elsewhere
           (password, firewall, network, server, log, attack…).
       Verdict:
         cyber  — 3+ different strong terms, or 2 strong + 5 weak
         not    — enough text to judge (150+ words) and NO strong term, or
                  only one strong term in 500+ words (e.g. a recipe, a bank
                  statement, a Sanskrit text, an invoice, a novel)
         unsure — everything else, and any sample under 150 words.
                  Unsure files are KEPT: removing a real security file is
                  worse than keeping an unrelated one.
       Tested on the cyber PDFs in the test set (all "cyber") and on
       unrelated documents (font manuals, licences, recipes → "not").

WHEN:  importer._extract_pdf / _extract_image / _extract_table (new files),
       importer.check_existing_relevance() once for banks imported before
       v0.8.2.

CONNECTED TO: importer.py (only caller), Library.jsx (shows the reason).
"""

import re

# Terms that practically only appear in security material.
STRONG = {
    # threats, attacks, defence, products, query languages — terms that
    # practically never appear outside security writing
    "malware", "ransomware", "phishing", "spearphishing", "spear-phishing", "rootkit", "keylogger",
    "botnet", "exploit", "zero-day", "0-day", "brute-force", "brute force", "credential stuffing",
    "password spraying", "pass-the-hash", "pass the hash", "kerberoasting", "golden ticket",
    "mimikatz", "lateral movement", "privilege escalation", "exfiltration", "command and control",
    "cobalt strike", "metasploit", "shellcode", "obfuscation", "obfuscated", "infostealer",
    "cryptojacking", "ddos", "denial of service", "man-in-the-middle", "mitm", "sql injection",
    "sqli", "xss", "cross-site scripting", "csrf", "rce", "remote code execution",
    "buffer overflow", "deserialization", "smishing", "vishing", "social engineering",
    "insider threat", "threat actor", "living off the land", "lolbin", "lolbas", "webshell",
    "web shell", "reverse shell", "siem", "soar", "edr", "xdr", "ndr", "ioc", "iocs",
    "indicator of compromise", "indicators of compromise", "ttp", "ttps", "mitre", "att&ck",
    "attack framework", "threat intelligence", "threat hunting", "threat hunt",
    "incident response", "dfir", "yara", "suricata", "zeek", "vulnerability", "vulnerabilities",
    "cve", "cvss", "penetration test", "penetration testing", "pentest", "red team", "blue team",
    "purple team", "honeypot", "deception technology", "ueba", "dlp", "data loss prevention",
    "casb", "waf", "intrusion detection", "intrusion prevention", "zero trust", "mfa",
    "multi-factor", "multifactor", "2fa", "cis benchmark", "kill chain", "cyber kill chain",
    "analytics rule", "microsoft sentinel", "crowdstrike", "splunk", "qradar", "elastic security",
    "kql", "kusto", "signinlogs", "securityevent", "securityalert", "deviceprocessevents",
    "azure ad", "entra id", "kerberos", "ntlm", "virustotal", "wireshark", "nmap", "nessus",
    "qualys", "tenable", "cybersecurity", "cyber security", "infosec", "information security",
    "cyberattack", "cyber attack", "attacker", "attackers", "hacker", "hackers", "hacking",
    "ciphertext", "sha256", "md5", "dns tunneling", "port scan", "port scanning", "reconnaissance",
    "cidr", "subnet", "subnetting", "sysmon",
}

# Common in security writing, but also in ordinary documents.
WEAK = {
    "security", "secure", "password", "passwords", "firewall", "network", "networks", "server",
    "servers", "log", "logs", "logging", "alert", "alerts", "attack", "attacks", "risk", "risks",
    "access", "authentication", "authorization", "account", "accounts", "user", "users", "admin",
    "administrator", "endpoint", "endpoints", "incident", "incidents", "monitoring", "detection",
    "detect", "protocol", "protocols", "ip", "tcp", "udp", "http", "https", "port", "ports",
    "domain", "email", "emails", "cloud", "azure", "aws", "windows", "linux", "process", "registry",
    "policy", "policies", "privilege", "privileges", "identity", "token", "tokens", "session",
    "traffic", "packet", "packets", "router", "switch", "gateway", "host", "hosts", "device",
    "devices", "data", "backup", "recovery", "audit", "control", "controls", "patch", "update",
    # security words that ALSO appear in law, IT, statistics or business text
    "trojan", "backdoor", "spyware", "worm", "exploitation", "exploited", "persistence", "c2",
    "beacon", "payload", "dropper", "loader", "stealer", "phish", "apt", "adversary",
    "adversaries", "soc", "forensics", "forensic", "sandbox", "detonation", "sigma", "snort",
    "patch management", "ids", "ips", "conditional access", "least privilege", "hardening", "nist",
    "iso 27001", "soc 2", "gdpr", "compliance", "attack surface", "containment", "eradication",
    "triage", "alert fatigue", "false positive", "true positive", "playbook", "runbook",
    "use case", "detection rule", "sentinel", "defender", "spl", "entra", "active directory",
    "ldap", "burp", "okta", "palo alto", "fortinet", "threat", "threats", "breach", "breaches",
    "compromise", "compromised", "malicious", "suspicious", "encryption", "decryption", "hash",
    "hashes", "certificate", "tls", "ssl", "vpn", "proxy", "recon", "enumeration", "subnet mask",
    "netmask", "rdp", "ssh", "smb", "powershell", "event id", "eventid", "audit log", "audit logs",
    "syslog",
}

# Patterns that are near-certain security content.
_PATTERNS = {
    "CVE id": re.compile(r"\bCVE-\d{4}-\d{3,7}\b", re.I),
    "ATT&CK id": re.compile(r"\bT1\d{3}(?:\.\d{3})?\b"),
    "event id": re.compile(r"\b(?:event\s*id|eventid)\s*[:=]?\s*\d{3,5}\b", re.I),
    "IP address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"),
    "hash value": re.compile(r"\b[a-f0-9]{32}\b|\b[a-f0-9]{64}\b", re.I),
    "query pipe": re.compile(r"^\s*\|\s*(?:where|project|summarize|extend|join|stats|table)\b", re.I | re.M),
}

MIN_WORDS = 150          # below this, a sample is too short to judge → unsure (kept)
_WORD = re.compile(r"[\w&'-]+", re.U)


def _phrases(text: str) -> set[str]:
    """All single words and 2-/3-word phrases in the text, lower-cased."""
    words = [w.lower().strip("'-") for w in _WORD.findall(text)]
    out = set(words)
    for n in (2, 3):
        out.update(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))
    return out


def assess(text: str) -> dict:
    """Judge a text sample. See the module docstring for the rules."""
    text = text or ""
    words = len(_WORD.findall(text))
    found = _phrases(text)
    strong = sorted(t for t in STRONG if t in found)
    strong += [name for name, rx in _PATTERNS.items() if rx.search(text)]
    weak = sorted(t for t in WEAK if t in found)
    s, w = len(strong), len(weak)
    if s >= 3 or (s >= 2 and w >= 5):
        verdict, reason = "cyber", f"security terms found: {', '.join(strong[:6])}"
    elif words >= MIN_WORDS and (s == 0 or (s == 1 and words >= 500)):
        verdict = "not"
        reason = ("no cybersecurity terms in a sample of %d words" % words if not s
                  else f"only one security term ({strong[0]}) in a sample of {words} words")
    else:
        verdict = "unsure"
        reason = ("too little text to judge" if words < MIN_WORDS
                  else f"some security terms ({', '.join((strong + weak)[:5])}) — kept to be safe")
    return {"verdict": verdict, "strong": strong[:12], "weak": weak[:12], "words": words, "reason": reason}
