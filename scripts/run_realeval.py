#!/usr/bin/env python3
"""Run the full real-data evaluation and freeze the results artifact.

    python scripts/run_realeval.py            # writes output/realeval_results.json

The artifact is the single source for every number in the paper; rerunning is
deterministic given data/real/ (see scripts/fetch_real_data.sh)."""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from research.realeval.dataset import load_autocast, select_mechanistic
from research.realeval.harness import full_evaluation

OUT = os.path.join(os.path.dirname(__file__), "..", "output", "realeval_results.json")


def main() -> int:
    qs = select_mechanistic(load_autocast())
    res = full_evaluation(qs)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    p = res["primary"]
    print(f"records: {p['n']} over {p['n_questions']} questions")
    print("mean Brier:", p["mean_brier"])
    print("skill vs crowd:", p["skill_vs_crowd"],
          "| band/error rank-corr:", p["band_error_rank_corr"])
    print("bootstrap crowd-minus-model Brier:", res["bootstrap_crowd_minus_model"])
    for row in res["by_lifetime_fraction"]:
        print(f"  f={row['fraction']:.1f}  n={row['n']:3d}  "
              f"model={row['brier_model']:.4f}  crowd={row['brier_crowd']:.4f}")
    for name, s in res["ablations"].items():
        print(f"ablation {name}: brier={s['mean_brier']['model']} (n={s['n']})")
    print(f"-> {os.path.normpath(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
