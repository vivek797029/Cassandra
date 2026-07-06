"""Real-data evaluation — dataset layer (paper Phase 1).

Loads the Autocast corpus (Zou et al. 2022: resolved forecasting questions from
Metaculus/Good Judgment Open, each with its full crowd-forecast time series),
selects the resolved binary questions inside CASSANDRA's mechanistic domains
(armed conflict, oil, macro), and provides the two primitives every later
stage builds on:

  * time-based calibration/test splits (walk-forward, no leakage), and
  * the crowd-at-as-of baseline (last crowd forecast at or before the
    forecast date — the strongest widely accepted comparator).

Raw data is NOT committed to git (~180 MB): run scripts/fetch_real_data.sh
once; everything here is deterministic given that file.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTOCAST_JSON = os.path.join(_ROOT, "data", "real", "autocast", "autocast_questions.json")

# Domain patterns: keep aligned with the engine's mechanism coverage
# (core/engine.py hazard channels). A question may match several domains.
DOMAIN_PATTERNS: dict[str, str] = {
    "conflict": r"\bwar\b|\bconflict\b|ceasefire|military|invasion|air ?strike|troops|hostilit",
    "oil":      r"\boil\b|\bbrent\b|\bcrude\b|\bopec\b|barrel",
    "macro":    r"recession|inflation|\bgdp\b|growth|sovereign default|\bimf\b|interest rate",
}


@dataclass
class RealQuestion:
    """One resolved binary question with its crowd trajectory."""
    qid: str
    question: str
    background: str
    domains: list[str]
    publish_time: datetime
    close_time: datetime
    answer: bool                                  # resolved outcome
    crowd: list[tuple[datetime, float]] = field(repr=False, default_factory=list)

    def crowd_at(self, asof: datetime) -> float | None:
        """Crowd baseline: last crowd probability at or before `asof`
        (None if the crowd had not yet forecast — caller must skip)."""
        best = None
        for ts, p in self.crowd:                  # stored sorted ascending
            if ts <= asof:
                best = p
            else:
                break
        return best


def _parse_ts(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def classify_domains(text: str) -> list[str]:
    return [d for d, pat in DOMAIN_PATTERNS.items() if re.search(pat, text, re.I)]


def load_autocast(path: str = AUTOCAST_JSON) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def select_mechanistic(raw: list[dict],
                       domains: tuple[str, ...] = ("conflict", "oil", "macro"),
                       min_crowd_points: int = 5) -> list[RealQuestion]:
    """Resolved true/false questions in the engine's domains, with a usable
    crowd trajectory and an unambiguous yes/no resolution."""
    out: list[RealQuestion] = []
    for q in raw:
        if q.get("status") != "Resolved" or q.get("qtype") != "t/f":
            continue
        if q.get("answer") not in ("yes", "no"):
            continue
        doms = [d for d in classify_domains(q["question"]) if d in domains]
        if not doms:
            continue
        crowd = sorted(
            ((_parse_ts(c["timestamp"]), float(c["forecast"])) for c in q.get("crowd", [])),
            key=lambda t: t[0])
        if len(crowd) < min_crowd_points:
            continue
        out.append(RealQuestion(
            qid=str(q["id"]), question=q["question"].strip(),
            background=(q.get("background") or "").strip(), domains=doms,
            publish_time=_parse_ts(q["publish_time"]),
            close_time=_parse_ts(q["close_time"]),
            answer=(q["answer"] == "yes"), crowd=crowd))
    out.sort(key=lambda r: r.close_time)
    return out


def time_split(qs: list[RealQuestion], train_end: datetime
               ) -> tuple[list[RealQuestion], list[RealQuestion]]:
    """Walk-forward split: calibration set = questions fully resolved before
    `train_end`; test set = questions PUBLISHED at/after `train_end` (questions
    straddling the boundary are dropped — their crowd/rationale windows would
    leak calibration-period information into the test period)."""
    calib = [q for q in qs if q.close_time < train_end]
    test = [q for q in qs if q.publish_time >= train_end]
    return calib, test


def base_rate(qs: list[RealQuestion]) -> float:
    """Historical base rate of YES in a question set (naive baseline)."""
    return sum(q.answer for q in qs) / max(len(qs), 1)
