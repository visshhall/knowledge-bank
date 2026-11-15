"""
test_understand.py — checks for understand.py (roles, subjects, outline, article material).
Plain asserts: run with   python tests/test_understand.py   from the engine folder.
WHAT: the AI's answer is parsed safely; queries are recognised without the AI; the outline is in
      teaching order with steps in document order; subjects are grouped by a shared key word;
      the article material gives every section a share and numbers points in prompt order.
WHEN: before every release that touches understand.py or the writer's material.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kb_engine import understand as u  # noqa: E402


def pt(i, text, fit=0.5, order=(1, 1, 0)):
    return {"id": i, "text": text, "fit": fit, "order": list(order), "sources": [], "section": None}


# 1. Parsing the AI's answer: ids, roles and subjects; junk and out-of-range lines are ignored.
got = u.parse_answer("P1|definition|DNS tunneling\nP2|Detection|Sysmon event 22\nhello\nP9|note|x\nP3|query|x\nP3|steps|Phase two", 3)
assert got == {1: ("definition", "DNS tunneling"), 2: ("detection", "Sysmon event 22"), 3: ("step", "Phase two")}, got

# 2. Queries are found by rules, not by the AI.
assert u.rule_role("```kql\nSecurityEvent | where EventID == 4625\n```") == "query"
assert u.rule_role("Monitor DNS logs for long TXT records.") == "detection"
assert u.rule_role("Block outbound DNS to untrusted resolvers.") == "response"

# 3. Outline: teaching order, steps in document order, one subject → no sub-heading.
pts = [pt(1, "Block outbound traffic to unknown hosts at the firewall.", 0.9),
       pt(2, "Second, the implant beacons to the server every minute.", 0.8, (1, 1, 2)),
       pt(3, "First, the attacker registers a domain for command and control.", 0.7, (1, 1, 1)),
       pt(4, "DNS tunneling is a technique that hides data inside DNS queries.", 0.6)]
roles = {u._key(pts[0]["text"]): ("response", ""), u._key(pts[1]["text"]): ("step", ""),
         u._key(pts[2]["text"]): ("step", ""), u._key(pts[3]["text"]): ("definition", "")}
u.annotate(pts, roles)
s = u.structure(pts)
assert [x["key"] for x in s["sections"]] == ["definition", "step", "response"], s["sections"]
step = next(x for x in s["sections"] if x["key"] == "step")
assert step["groups"][0]["point_ids"] == [3, 2], "steps keep their document order"
assert step["groups"][0]["about"] is None

# 4. Subjects: labels sharing a key word are grouped; few labels are left alone.
labels = ["Proxy-based C2 communication", "DNS-based C2 communication", "Web service C2 communication",
          "USB data exfiltration", "Traffic mirroring exfiltration", "Code repository exfiltration",
          "Lateral tool transfer", "Message broker protocol abuse"]
m = u.group_labels(labels)
assert m["DNS-based C2 communication"] == m["Proxy-based C2 communication"] == "C2"
assert m["USB data exfiltration"] == m["Code repository exfiltration"] == "Exfiltration"
assert u.group_labels(labels[:4]) == {}

# 5. Gaps are reported only when something else is known; contradictions are passed through.
extra5 = pt(5, "Another how it works sentence about the beacon traffic.")
u.annotate([extra5], {})
s = u.structure(pts[:3] + [extra5],
                [{"a": "X is allowed.", "b": "X is not allowed.", "a_point": 1, "b_point": 2}])
kinds = [i["kind"] for i in s["insights"]]
assert "conflict" in kinds and "gap" in kinds

# 6. Article material: every section gets a share, numbering follows the prompt order.
many = [pt(10 + i, f"Adversaries may abuse mechanism number {i} to reach the target host quietly.", 0.9 - i / 100) for i in range(8)]
many.append(pt(30, "Monitor proxy logs for beaconing to rare domains.", 0.1))
many.append(pt(31, "Disable the unused protocol on edge routers.", 0.1))
u.annotate(many, {})
direct, extra, text = u.writer_material(many, [], 6)
ids = {p["id"] for p in direct}
assert 30 in ids and 31 in ids, "detection and response points must not be pushed out by the larger section"
assert len(direct) == 6 and len(extra) == 4
assert text.index("### How it works") < text.index("### How to detect it") < text.index("### What to do about it")
assert text.count("[1]") == 1 and f"[{len(direct)}]" in text

print("understand.py: all checks passed")
