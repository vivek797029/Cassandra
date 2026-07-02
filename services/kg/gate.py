"""Task 57 — mechanism id-status gate.

`gate_theta(theta)` enforces the blueprint rule before any theta reaches the
simulator: parameters owned by a hypothesis-grade mechanism are REVERTED to
the expert prior (trained deviations blocked); identified/expert pass clean;
estimated pass with a confounding-risk flag; parameters with no mechanism
card pass with an 'uncarded' warning (visible debt, not silent).

Wired into: engines startup (after theta load) and the retrain worker
(before promotion). Exposed at GET /v1/mechanisms.
"""
from __future__ import annotations
import numpy as np

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core.engine import THETA_NAMES, THETA_DEFAULT
from services.kg.mechanisms import MECHANISM_CARDS, ALLOWED_STATUSES, card_for_param


def gate_theta(theta, cards: list[dict] | None = None) -> tuple[np.ndarray, dict]:
    """-> (gated_theta, report). Blocking reverts the param to THETA_DEFAULT."""
    cards = cards if cards is not None else MECHANISM_CARDS
    by_param = {}
    for c in cards:
        for p in c["params"]:
            by_param[p] = c
    theta = np.array(theta, float).copy()
    blocked, estimated, uncarded = [], [], []
    for i, name in enumerate(THETA_NAMES):
        card = by_param.get(name)
        if card is None:
            uncarded.append(name)
            continue
        if card["id_status"] not in ALLOWED_STATUSES:
            if abs(theta[i] - THETA_DEFAULT[i]) > 1e-12:
                blocked.append({"param": name, "mechanism": card["id"],
                                "trained": round(float(theta[i]), 5),
                                "reverted_to": round(float(THETA_DEFAULT[i]), 5)})
            theta[i] = THETA_DEFAULT[i]
        elif card["id_status"] == "estimated":
            estimated.append(name)
    return theta, {"blocked": blocked, "estimated_flagged": sorted(set(estimated)),
                   "uncarded": uncarded, "n_cards": len(cards)}


def mechanisms_view() -> dict:
    """For GET /v1/mechanisms: cards + current gate posture."""
    _, report = gate_theta(THETA_DEFAULT)
    return {"cards": MECHANISM_CARDS, "allowed_statuses": sorted(ALLOWED_STATUSES),
            "gate_report_on_prior": report}
