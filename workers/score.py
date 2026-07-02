"""Task 50 — ledger scoring job.

Joins the forecast ledger (latest prediction per key) against resolved
registry outcomes and produces the calibration report the blueprint requires:
Brier + log score per stratum (domain × horizon), 10-bin reliability table,
and overall skill vs the base-rate climatology baseline.

Persisted as a run record (kind='pipeline', payload.job='scoring') and to
output/calibration.json — the GET /v1/calibration endpoint (Task 60) reads it.

CLI:  python -m workers.score
API helpers:
  record_predictions(store, preds, theta_hash)   # log model predictions for keys
  score(store, registry)                          # -> calibration report
"""
from __future__ import annotations
import hashlib, json, math, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.copilot.store import get_store
from services.question_registry.registry import QuestionRegistry

OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "output", "calibration.json")
EPS = 1e-4


def record_predictions(store, preds: list[dict], theta_hash: str) -> int:
    """preds: [{key, probability, band_lo?, band_hi?}] -> forecast_ledger rows."""
    n = 0
    for p in preds:
        mid = hashlib.sha256(f"{p['key']}|{p['probability']}|{theta_hash}"
                             .encode()).hexdigest()[:16]
        store.ledger_record(mid, p["key"], float(p["probability"]),
                            p.get("band_lo"), p.get("band_hi"), theta_hash)
        n += 1
    return n


def _stratum(q: dict) -> str:
    return f"{q.get('domain','?')}|{q.get('horizon') or '?'}"


def score(store, reg: QuestionRegistry) -> dict:
    resolved = {q["key"]: q for q in reg.list(resolved=True)}
    pairs = []
    for row in store.ledger_latest():
        q = resolved.get(row["key"])
        if q is None or q.get("outcome") is None:
            continue
        pairs.append({"key": row["key"], "p": float(row["probability"]),
                      "y": int(q["outcome"]), "stratum": _stratum(q)})
    n = len(pairs)
    if n == 0:
        return {"n_scored": 0, "note": "no (prediction, outcome) pairs yet"}

    brier = sum((x["p"] - x["y"]) ** 2 for x in pairs) / n
    logs = -sum(x["y"] * math.log(max(x["p"], EPS)) +
                (1 - x["y"]) * math.log(max(1 - x["p"], EPS)) for x in pairs) / n
    base_rate = sum(x["y"] for x in pairs) / n
    brier_clim = sum((base_rate - x["y"]) ** 2 for x in pairs) / n     # climatology
    skill = 1 - brier / brier_clim if brier_clim > 0 else 0.0          # Brier skill score

    strata: dict[str, dict] = {}
    for x in pairs:
        s = strata.setdefault(x["stratum"], {"n": 0, "brier_sum": 0.0,
                                             "p_sum": 0.0, "y_sum": 0})
        s["n"] += 1
        s["brier_sum"] += (x["p"] - x["y"]) ** 2
        s["p_sum"] += x["p"]
        s["y_sum"] += x["y"]
    by_stratum = {k: {"n": s["n"], "brier": round(s["brier_sum"] / s["n"], 4),
                      "avg_p": round(s["p_sum"] / s["n"], 4),
                      "base_rate": round(s["y_sum"] / s["n"], 4)}
                  for k, s in sorted(strata.items())}

    bins = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        inb = [x for x in pairs if lo <= x["p"] < hi or (b == 9 and x["p"] == 1.0)]
        if inb:
            bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(inb),
                         "avg_p": round(sum(x["p"] for x in inb) / len(inb), 4),
                         "freq": round(sum(x["y"] for x in inb) / len(inb), 4)})
    ece = sum(abs(b["avg_p"] - b["freq"]) * b["n"] for b in bins) / n if bins else None

    report = {"n_scored": n, "brier": round(brier, 4), "log_score": round(logs, 4),
              "base_rate": round(base_rate, 4),
              "brier_climatology": round(brier_clim, 4),
              "brier_skill_score": round(skill, 4),
              "ece": round(ece, 4) if ece is not None else None,
              "by_stratum": by_stratum, "reliability_bins": bins,
              "scored_at": time.time()}

    mid = hashlib.sha256(json.dumps([(x["key"], x["p"], x["y"]) for x in pairs],
                                    sort_keys=True).encode()).hexdigest()[:16]
    store.record_run(mid, "pipeline", {"job": "scoring", "report":
                     {k: v for k, v in report.items() if k != "reliability_bins"}},
                     theta_hash="-", seed=0)
    report["manifest_id"] = mid
    os.makedirs(os.path.dirname(os.path.abspath(OUT_JSON)), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=1)
    return report


def main():
    rep = score(get_store(), QuestionRegistry())
    print(json.dumps({k: v for k, v in rep.items()
                      if k not in ("reliability_bins",)}, indent=1))


if __name__ == "__main__":
    main()
