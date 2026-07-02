"""Task 92 — causal case library (POLICY-TRACE cartridges) + analog metric eval.

50 historical cartridges (cause→channel→outcome, with policy success/failure and a
survivorship-guard set of NON-EVENTS — crises that did NOT escalate). Retrieval is by
mechanism-channel overlap (Jaccard). `eval_analogs()` scores retrieval quality
(precision@3, MRR) against labeled queries and checks the mechanism-overlap floor and
non-event coverage.

    python -m services.kg.cases        # print the eval report
"""
from __future__ import annotations
import os, json
from functools import lru_cache

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DIR = os.path.join(_ROOT, "data", "cases")
REQUIRED = {"id", "name", "year", "domain", "channels", "mechanism",
            "outcome", "policy_success", "policy_failure", "is_nonevent"}


@lru_cache(maxsize=1)
def load_cases() -> list[dict]:
    with open(os.path.join(_DIR, "cases.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_eval_queries() -> list[dict]:
    with open(os.path.join(_DIR, "eval_queries.json"), encoding="utf-8") as f:
        return json.load(f)


def _jaccard(a, b) -> float:
    A, B = set(a), set(b)
    return len(A & B) / len(A | B) if (A | B) else 0.0


def retrieve(tags: list[str], k: int = 5, cases: list[dict] | None = None) -> list[tuple[str, float]]:
    """Top-k cases by mechanism-channel overlap (mechanism-overlap floor: score>0)."""
    cases = cases or load_cases()
    scored = sorted(((c["id"], _jaccard(tags, c["channels"])) for c in cases),
                    key=lambda x: (-x[1], x[0]))
    return [s for s in scored if s[1] > 0][:k]


def eval_analogs() -> dict:
    cases = load_cases()
    qs = load_eval_queries()
    n = len(cases)
    nonevents = sum(1 for c in cases if c.get("is_nonevent")) / n
    precisions, rrs, floor_ok = [], [], True
    for q in qs:
        top3 = [cid for cid, _ in retrieve(q["tags"], k=3, cases=cases)]
        rel = set(q["relevant"])
        precisions.append(sum(1 for cid in top3 if cid in rel) / max(len(top3), 1))
        ranked = retrieve(q["tags"], k=10, cases=cases)
        rr = next((1 / i for i, (cid, _) in enumerate(ranked, 1) if cid in rel), 0.0)
        rrs.append(rr)
        floor_ok &= bool(ranked) and ranked[0][1] > 0          # a real mechanism match exists
    return {"n_cases": n, "nonevent_fraction": round(nonevents, 3),
            "precision_at_3": round(sum(precisions) / len(precisions), 3),
            "mrr": round(sum(rrs) / len(rrs), 3),
            "mechanism_floor_ok": floor_ok}


def main() -> int:
    r = eval_analogs()
    print(json.dumps(r, indent=2))
    ok = (r["n_cases"] >= 50 and r["nonevent_fraction"] >= 0.15
          and r["precision_at_3"] >= 0.6 and r["mrr"] >= 0.6 and r["mechanism_floor_ok"])
    print("CASE-LIBRARY EVAL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
