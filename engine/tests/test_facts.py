"""
test_facts.py — checks for facts.py (repeated-statement folding). Plain asserts, no test framework:
run with   python tests/test_facts.py   from the engine folder.
WHAT: proves what must merge (same sentence in two files, a sentence inside a longer one, a
      point that is only repeats) and what must NOT (other technique ID, negation, one swapped
      word, a different query). WHEN: before every release that touches facts.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import facts  # noqa: E402


def pt(i, text, src, page=1, ordinal=0):
    return {"id": i, "text": text, "order": [src, page, ordinal],
            "sources": [{"source_id": src, "file_name": f"f{src}.pdf", "page": page}]}


def run(*points):
    return facts.plan(list(points), {}, [])


# 1. The same sentence in two files: shown once, both files listed as sources.
a = "Adversaries may abuse DNS to communicate with systems under their control inside a victim network."
pts, ab, st = run(pt(1, a, 1), pt(2, "Intro line that is short\n" + a, 2, 4))
assert [p["id"] for p in pts] == [1] and ab == {2: 1}, (pts, ab)
assert {s["source_id"] for s in pts[0]["sources"]} == {1, 2}

# 2. A shorter sentence inside a longer one: the longer one stays, the shorter's file is added.
short = "Attackers can hide data inside DNS packets sent to the resolver."
long_ = "Attackers can hide data inside DNS packets sent to the resolver and read it back from replies."
pts, ab, st = run(pt(1, short, 1), pt(2, long_, 2))
assert [p["id"] for p in pts] == [2] and ab == {1: 2}, (pts, ab)

# 3. Different technique IDs / event IDs are never merged by wording.
pts, _, st = run(pt(1, "Technique T1059.001 runs commands through the PowerShell interpreter on the host.", 1),
                 pt(2, "Technique T1059.003 runs commands through the PowerShell interpreter on the host.", 2))
assert len(pts) == 2 and st["merged"] == 0
pts, _, st = run(pt(1, "Event 4624 is logged when an account logs on to the computer successfully.", 1),
                 pt(2, "Event 4625 is logged when an account logs on to the computer successfully.", 2))
assert len(pts) == 2 and st["merged"] == 0

# 4. One changed word (or a negation) is a different statement.
pts, _, st = run(pt(1, "Adversaries may steal data by exfiltrating it over a symmetrically encrypted network protocol.", 1),
                 pt(2, "Adversaries may steal data by exfiltrating it over an asymmetrically encrypted network protocol.", 2))
assert len(pts) == 2 and st["merged"] == 0
pts, _, st = run(pt(1, "The service account is allowed to log on interactively to the domain controller.", 1),
                 pt(2, "The service account is not allowed to log on interactively to the domain controller today.", 2))
assert len(pts) == 2, "a negation must not be folded away"

# 5. A query block is compared by exact text only.
q1 = "```kql\nSecurityEvent | where EventID == 4625 | summarize count() by Account\n```"
q2 = "```kql\nSecurityEvent | where EventID == 4625 | summarize count() by Computer\n```"
pts, _, st = run(pt(1, "Failed logons:\n" + q1, 1), pt(2, "Failed logons by host:\n" + q2, 2))
assert len(pts) == 2 and st["merged"] == 0
pts, ab, st = run(pt(1, "Failed logons:\n" + q1, 1), pt(2, q1, 2))
assert ab == {2: 1}

# 6. A repeat inside the SAME file (the same line twice on different pages) is folded too.
pts, ab, st = run(pt(1, a, 1, page=2), pt(2, a, 1, page=9))
assert ab == {2: 1} and {(s["source_id"], s["page"]) for s in pts[0]["sources"]} == {(1, 2), (1, 9)}

# 7. A borderline pair is queued for the AI and counts as different until it answers.
pend = []
b1 = "Spearphishing attachment is delivered by email with a malicious file that the user must open to start execution."
b2 = "Spearphishing with a malicious file attached to an email depends on the user opening it for execution to start."
pts, _, _ = facts.plan([pt(1, b1, 1), pt(2, b2, 2)], {}, pend)
assert len(pts) == 2 and len(pend) == 1
key = pend[0][0]
pts, ab, _ = facts.plan([pt(1, b1, 1), pt(2, b2, 2)], {key: "SAME"}, [])
assert len(ab) == 1, "a SAME answer folds the pair"
pts, ab, _ = facts.plan([pt(1, b1, 1), pt(2, b2, 2)], {key: "DIFFERENT"}, [])
assert len(pts) == 2

# 8. Headings are never statements and never merge two points.
pts, _, st = run(pt(1, "USE CASE 13: COMMAND AND CONTROL\nStep 1: Investigation\n" + a, 1),
                 pt(2, "USE CASE 13: COMMAND AND CONTROL\nStep 1: Investigation\nAnother separate statement about proxies and beacons here.", 2))
assert len(pts) == 2

print("facts.py: all checks passed")
