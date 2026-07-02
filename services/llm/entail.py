"""Task 77 — entailment / faithfulness gate.

The blueprint's faithfulness rule (§9/§11): every sentence in an answer must map
to a field of a structured engine object — no unsupported claims, and above all no
ungrounded numbers. The composer is template-bound so it is faithful by
construction; this gate is the *checker* that proves it (defense-in-depth) and
that guards any future LLM-narrated path.

A sentence is UNFAITHFUL if it contains a number absent from the object corpus,
or it is a substantive claim (≥ `MIN_CLAIM_TOKENS` salient tokens) with zero
overlap with the corpus. `enforce()` removes offending sentences ("unfaithful
sentence blocked"); deterministic, no LLM, no network.
"""
from __future__ import annotations
import json, re

MIN_CLAIM_TOKENS = 6
BLOCK_MARKER = "[blocked: unverified — no supporting evidence object]"

_NUM = re.compile(r"\d+(?:\.\d+)?")
_WORD = re.compile(r"[a-zA-Z]{4,}")
_STOP = {
    "this", "that", "with", "from", "have", "will", "your", "into", "over", "under",
    "within", "than", "then", "when", "what", "which", "while", "about", "above",
    "their", "there", "these", "those", "been", "being", "they", "them", "here",
    "also", "more", "most", "less", "such", "only", "some", "very", "much", "many",
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "per",
    # scaffolding labels the composer prints alongside (not always) field values
    "mechanism", "counterargument", "counter", "evidence", "pathway", "causal",
    "analog", "historical", "confidence", "horizon", "watch", "assumptions",
    "situation", "headline", "risks", "scenario", "scenarios", "recommended",
    "portfolio", "warning", "indicators", "exposed", "similar", "episodes",
    "reproducible", "manifest", "audit", "fails", "via",
}


def _numbers(text: str) -> set[str]:
    return set(_NUM.findall(text))


def _expand_numbers(nums: set[str]) -> set[str]:
    """Add percent forms so a rendered '58%' matches a stored probability 0.58."""
    out = set(nums)
    for n in nums:
        try:
            f = float(n)
        except ValueError:
            continue
        if "." in n and 0.0 <= f <= 1.0:
            out.add(str(round(f * 100)))
            out.add(f"{f * 100:.0f}")
    return out


def _salient(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def build_corpus(objs: dict) -> dict:
    """Grounded corpus from the structured answer objects (excludes any echo of the
    raw question / parse)."""
    safe = {k: v for k, v in objs.items()
            if k not in ("redaction_notice",)}
    blob = json.dumps(safe, default=str).lower()
    return {"text": blob, "numbers": _expand_numbers(_numbers(blob)),
            "tokens": _salient(blob)}


def split_sentences(markdown: str) -> list[str]:
    """Strip markdown scaffolding and split into checkable sentences."""
    out: list[str] = []
    for line in markdown.splitlines():
        s = re.sub(r"`[^`]*`", " ", line)                 # drop code spans (manifest ids)
        s = re.sub(r"[*_>#\-]", " ", s)                   # markdown punctuation
        s = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", s)         # links → text
        s = s.strip()
        if not s:
            continue
        for part in re.split(r"(?<=[.!?])\s+", s):
            part = part.strip()
            if part:
                out.append(part)
    return out


def entails(sentence: str, corpus: dict) -> tuple[bool, str]:
    for n in _numbers(sentence):
        variants = _expand_numbers({n})
        if not (variants & corpus["numbers"]):
            return False, f"ungrounded number: {n}"
    tokens = _salient(sentence)
    if len(tokens) >= MIN_CLAIM_TOKENS and not (tokens & corpus["tokens"]):
        return False, "unsupported claim (no overlap with evidence objects)"
    return True, "ok"


def gate(markdown: str, objs: dict) -> dict:
    corpus = build_corpus(objs)
    sentences = split_sentences(markdown)
    violations = []
    for s in sentences:
        ok, reason = entails(s, corpus)
        if not ok:
            violations.append({"sentence": s, "reason": reason})
    _bump("checked", len(sentences))
    _bump("violations", len(violations))
    return {"faithful": not violations, "n_sentences": len(sentences),
            "violations": violations}


def enforce(markdown: str, objs: dict) -> tuple[str, dict]:
    """Return markdown with unfaithful sentences blocked, plus the report."""
    corpus = build_corpus(objs)
    report = gate(markdown, objs)
    if report["faithful"]:
        return markdown, report
    bad = {v["sentence"] for v in report["violations"]}
    out_lines = []
    for line in markdown.splitlines():
        if any(b and b in line for b in bad):
            out_lines.append(BLOCK_MARKER)
        else:
            out_lines.append(line)
    _bump("enforced", 1)
    return "\n".join(out_lines), report


# -- metrics ------------------------------------------------------------------
_METRICS = {"checked": 0, "violations": 0, "enforced": 0}


def _bump(k: str, n: int = 1) -> None:
    _METRICS[k] = _METRICS.get(k, 0) + n


def get_metrics() -> dict:
    return dict(_METRICS)
