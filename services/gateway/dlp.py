"""Task 91 — DLP export gates.

Before any summary leaves the system, scan it for (1) classification banners/control
markings, (2) seeded DLP canary tokens that must never appear in output, and
(3) withheld-fact terms — text from facts the caller is NOT cleared for (the Task-75
redaction layer is the primary control; this is defense-in-depth at the egress). On a
finding the gate redacts the offending span (enforce) so a seeded leak is blocked.
"""
from __future__ import annotations
import re

# Common US classification control markings / banners (illustrative, case-insensitive).
_BANNER = re.compile(
    r"(TOP\s*SECRET//[A-Z/ ]+|TS//[A-Z/]+|SECRET//[A-Z/]+|//NOFORN|//SI/TK|\(TS//[A-Z]+\)|\(S//NF\))",
    re.IGNORECASE)
REDACTION = "[DLP-REDACTED]"


def scan(text: str, canaries: list[str] | None = None,
         classified_terms: list[str] | None = None) -> list[dict]:
    """Return DLP findings (does not modify the text)."""
    findings: list[dict] = []
    for m in _BANNER.findall(text or ""):
        findings.append({"type": "classification-banner", "match": m})
    low = (text or "").lower()
    for c in (canaries or []):
        if c and c.lower() in low:
            findings.append({"type": "canary", "match": c})
    for t in (classified_terms or []):
        if t and len(t) >= 8 and t.lower() in low:
            findings.append({"type": "classified-term", "match": t[:48]})
    return findings


def enforce(text: str, canaries: list[str] | None = None,
            classified_terms: list[str] | None = None) -> tuple[str, list[dict]]:
    """Redact any banner / canary / withheld-term so the leak cannot egress."""
    findings = scan(text, canaries, classified_terms)
    if not findings:
        return text, findings
    clean = _BANNER.sub(REDACTION, text)
    for c in (canaries or []):
        if c:
            clean = re.sub(re.escape(c), REDACTION, clean, flags=re.IGNORECASE)
    for t in (classified_terms or []):
        if t and len(t) >= 8:
            clean = re.sub(re.escape(t), REDACTION, clean, flags=re.IGNORECASE)
    return clean, findings
