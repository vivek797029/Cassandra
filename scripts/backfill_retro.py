"""Task 96 — 10-year retro backfill (RETRO-CAST v1).

Deterministically generates ~5,000 retrospective questions stratified across
domain x horizon x rule-family over a 10-year window, runs a leakage check (the
resolution window must sit entirely inside the historical window and after the
ask-time `asof`), and freezes the set as RETRO-CAST v1 — a manifest pinning the
count, strata, and a content SHA-256. The dataset is reproducible from the seed, so
the manifest hash "freezes" it without committing a multi-MB file.

    python scripts/backfill_retro.py --freeze     # write data/retrocast/manifest.json
    python scripts/backfill_retro.py --verify      # re-generate + check the frozen hash
"""
from __future__ import annotations
import argparse, hashlib, json, os, random, time
from collections import Counter
from datetime import date, timedelta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(_ROOT, "data", "retrocast")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

DOMAINS = ["security", "energy", "macro", "tech", "climate"]
HORIZONS = [30, 90, 180, 365]
FAMILIES = ["series_threshold", "event_count"]
WINDOW_START = date(2016, 1, 1)
WINDOW_END = date(2026, 6, 1)
N_DEFAULT = 5000
SEED = 42


def generate(n: int = N_DEFAULT, seed: int = SEED) -> list[dict]:
    cells = [(d, h, f) for d in DOMAINS for h in HORIZONS for f in FAMILIES]  # 40 strata
    rng = random.Random(seed)
    span = (WINDOW_END - WINDOW_START).days
    out = []
    for i in range(n):
        d, h, f = cells[i % len(cells)]                 # round-robin → even strata
        asof = WINDOW_START + timedelta(days=rng.randint(0, span - h))
        by = asof + timedelta(days=h)
        if f == "series_threshold":
            snap = round(80 + rng.random() * 60, 2)     # ask-time series value
            rule = {"kind": f, "threshold": round(snap * 1.1, 2)}
        else:
            snap = rng.randint(0, 20)                    # ask-time trailing count
            rule = {"kind": f, "threshold": max(1, snap + 3)}
        out.append({"id": f"rc-{i:05d}", "domain": d, "horizon_days": h, "family": f,
                    "asof": asof.isoformat(), "by": by.isoformat(),
                    "rule": rule, "snapshot": {"asof_value": snap}})
    return out


def leakage_check(qs: list[dict]) -> list[dict]:
    bad = []
    for q in qs:
        asof, by = date.fromisoformat(q["asof"]), date.fromisoformat(q["by"])
        if not (WINDOW_START <= asof < by <= WINDOW_END):
            bad.append(q["id"])
    return bad


def strata_counts(qs: list[dict]) -> dict:
    c = Counter((q["domain"], q["horizon_days"], q["family"]) for q in qs)
    return {f"{d}|{h}|{f}": n for (d, h, f), n in sorted(c.items())}


def content_hash(qs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(qs, sort_keys=True).encode()).hexdigest()


def freeze(n: int = N_DEFAULT, seed: int = SEED) -> dict:
    qs = generate(n, seed)
    leaks = leakage_check(qs)
    if leaks:
        raise SystemExit(f"leakage check failed for {len(leaks)} questions")
    sc = strata_counts(qs)
    manifest = {"name": "RETRO-CAST", "version": "v1", "n": len(qs), "seed": seed,
                "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
                "strata": {"domains": DOMAINS, "horizons": HORIZONS, "families": FAMILIES,
                           "cells": len(sc), "min_cell": min(sc.values())},
                "sha256": content_hash(qs), "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def verify() -> bool:
    if not os.path.exists(MANIFEST):
        return False
    m = json.load(open(MANIFEST))
    qs = generate(m["n"], m["seed"])
    return content_hash(qs) == m["sha256"] and not leakage_check(qs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("-n", type=int, default=N_DEFAULT)
    a = ap.parse_args()
    if a.freeze:
        m = freeze(a.n)
        print(f"RETRO-CAST {m['version']} frozen: n={m['n']} cells={m['strata']['cells']} "
              f"min_cell={m['strata']['min_cell']} sha={m['sha256'][:12]}")
        return 0
    if a.verify:
        ok = verify()
        print("RETRO-CAST verify:", "OK" if ok else "MISMATCH")
        return 0 if ok else 1
    qs = generate(a.n)
    print(f"generated {len(qs)} questions, {len(strata_counts(qs))} strata, "
          f"leaks={len(leakage_check(qs))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
