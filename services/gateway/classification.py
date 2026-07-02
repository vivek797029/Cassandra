"""Task 75 — cell-level clearance redaction.

Classifications are data-driven (`data/classification.json`, overridable via
`ARGUS_CLASSIFICATION`): a record-level map (whole fact hidden above clearance), a
cell-level map (a single field masked while the record stays visible), and a
domain default. The composer / API render only what the caller's `Principal` is
cleared for — a SECRET fact is hidden from an OPEN principal, and a SECRET cell on
an otherwise-OPEN fact is masked. Unlisted items default to OPEN.
"""
from __future__ import annotations
import os, json
from functools import lru_cache

from services.gateway.clearance import Principal, normalize_clearance

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REDACTED = "[REDACTED]"


def _path() -> str:
    return os.environ.get("ARGUS_CLASSIFICATION",
                          os.path.join(_ROOT, "data", "classification.json"))


@lru_cache(maxsize=1)
def _rules() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}
    return {"record": raw.get("record", {}) or {},
            "cell": raw.get("cell", {}) or {},
            "domain": raw.get("domain", {}) or {}}


def reset_classification_cache() -> None:
    """Test helper — re-read the classification file on next call."""
    _rules.cache_clear()


def classify_fact(fact: dict) -> str:
    """Record-level clearance for a fact: explicit id rule, else domain default, else OPEN."""
    r = _rules()
    fid = fact.get("id")
    if fid in r["record"]:
        return normalize_clearance(r["record"][fid])
    return normalize_clearance(r["domain"].get(fact.get("domain")))


def redact_facts(facts: list[dict], principal: Principal) -> dict:
    """Filter a fact list for a principal. Returns visible facts (with over-clearance
    cells masked) plus counts of hidden records and masked cells."""
    r = _rules()
    visible: list[dict] = []
    hidden = masked = 0
    withheld_texts: list[str] = []
    for fact in facts:
        if not principal.can_access(classify_fact(fact)):
            hidden += 1
            if fact.get("text"):
                withheld_texts.append(fact["text"])
            continue
        cell_rules = r["cell"].get(fact.get("id"), {})
        if cell_rules:
            fact = dict(fact)
            for cell, lvl in cell_rules.items():
                if cell in fact and not principal.can_access(lvl):
                    fact[cell] = f"{REDACTED} ({normalize_clearance(lvl)})"
                    masked += 1
        visible.append(fact)
    return {"facts": visible, "hidden": hidden, "cells_masked": masked,
            "clearance": principal.clearance, "withheld_texts": withheld_texts}


def redaction_notice(result: dict) -> str | None:
    """One-line, clearance-honest notice, or None when nothing was withheld."""
    if not result["hidden"] and not result["cells_masked"]:
        return None
    parts = []
    if result["hidden"]:
        parts.append(f"{result['hidden']} item(s) above your clearance "
                     f"({result['clearance']}) withheld")
    if result["cells_masked"]:
        parts.append(f"{result['cells_masked']} field(s) redacted")
    return "🔒 " + "; ".join(parts) + "."
