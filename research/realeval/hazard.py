"""Real-data evaluation — hazard-clock family (paper Phase 2b).

The engine's conflict block is a hazard machine: escalation events fire with
calibrated quarterly rates (theta's *_base channels). This module extends that
same mechanism family to real conflict questions: an event of class c in
window Δ occurs with P = 1 − exp(−λ_c Δ), a continuous-time hazard clock.

Discipline (the properties reviewers will probe):
  * λ_c is fitted by maximum likelihood ONLY on questions RESOLVED BEFORE the
    forecast date (the walk-forward harness enforces close_time < asof), so
    no outcome information leaks forward.
  * Classes are partially pooled: each class MLE is smoothed toward the
    global conflict rate with `alpha` pseudo-observations — sparse classes
    degrade gracefully to the pooled rate instead of memorizing 1-2 outcomes.
  * Robust bands reuse the engine's plausibility-ball semantics: the rate is
    perturbed multiplicatively (λ·e^±rho) and the band is the induced
    probability interval. Conformal widening happens in the harness, where
    calibration residuals exist.
  * As-of clipping: forecasting mid-window uses only the REMAINING exposure
    (asof→window end) — the clock cannot count time that already passed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from research.realeval.compiler import Excluded, extract_window

LAMBDA_LO, LAMBDA_HI = 0.01, 20.0             # events/year — clamp for stability

EVENT_CLASSES: dict[str, str] = {              # precedence order matters
    "CASUALTY_THRESHOLD": r"casualt|death toll|killed .* exceed|fatalit",
    "AIRSTRIKE":          r"airstrike|air strike|aerial attack|conduct .*strikes",
    "CEASEFIRE":          r"ceasefire|cease-fire|truce",
    "DEPLOYMENT":         r"deploy|combat troops|ground forces|boots on the ground",
    "CONFRONTATION":      r"confrontation|clash|lethal|skirmish|fire upon|exchange of fire",
    "MILITARY_ACTION":    r"military action|military exercise|armed conflict|invasion|"
                          r"attack|expand by means of armed",
}


@dataclass
class CompiledHazard:
    event_class: str
    window: tuple[date, date]
    kind: str                                  # 'by' | 'between'

    def exposure_years(self, asof: date) -> float:
        """Remaining exposure from `asof` (as-of clipping)."""
        start = max(asof, self.window[0])
        return max(0.0, (self.window[1] - start).days / 365.25)


def classify_event(text: str) -> str | None:
    t = text.lower()
    for cls, pat in EVENT_CLASSES.items():
        if re.search(pat, t):
            return cls
    return None


def compile_hazard(text: str, publish: datetime) -> CompiledHazard | Excluded:
    """Compile a conflict question to a hazard clock, or refuse."""
    cls = classify_event(text)
    if cls is None:
        return Excluded("NON_MECHANISTIC", "no recognizable conflict event class")
    if cls == "CASUALTY_THRESHOLD":
        return Excluded("COUNT_THRESHOLD", "count data needs an intensity model, "
                                           "not a first-event clock")
    win = extract_window(text, publish)
    if win is None:
        return Excluded("UNPARSEABLE_WINDOW", "no deadline found")
    d1, d2, kind = win
    if (d2 - d1).days < 14:
        return Excluded("DEGENERATE_WINDOW", f"{(d2 - d1).days}d window")
    return CompiledHazard(cls, (d1, d2), kind)


# --------------------------------------------------------------------------
# maximum-likelihood rate fitting
# --------------------------------------------------------------------------
def fit_lambda(obs: list[tuple[float, float]],
               lo: float = LAMBDA_LO, hi: float = LAMBDA_HI) -> float:
    """MLE of the hazard rate from (exposure_years, outcome) pairs, where
    outcome may be fractional (pseudo-observations for pooling).

    Log-likelihood  L(l) = sum yi*log(1-exp(-l*di)) - (1-yi)*l*di,  which is
    concave in l; the gradient is monotone decreasing, so bisection on the
    gradient finds the unique root (or the clamped boundary)."""
    obs = [(d, y) for d, y in obs if d > 0]
    if not obs:
        return lo

    def grad(lam: float) -> float:
        g = 0.0
        for d, y in obs:
            e = math.exp(-lam * d)
            if y > 0:
                g += y * d * e / max(1.0 - e, 1e-12)
            g -= (1.0 - y) * d
        return g

    if grad(lo) <= 0:
        return lo
    if grad(hi) >= 0:
        return hi
    a, b = lo, hi
    for _ in range(80):
        m = 0.5 * (a + b)
        if grad(m) > 0:
            a = m
        else:
            b = m
    return 0.5 * (a + b)


class HazardModel:
    """Per-class hazard rates, partially pooled toward the global rate."""

    def __init__(self, alpha: float = 2.0, rho: float = 0.10):
        self.alpha, self.rho = alpha, rho      # rho mirrors the engine's theta ball
        self.global_rate = LAMBDA_LO
        self.rates: dict[str, float] = {}
        self.n_by_class: dict[str, int] = {}

    def fit(self, samples: list[tuple[str, float, bool]]) -> "HazardModel":
        """samples: (event_class, exposure_years, occurred)."""
        all_obs = [(d, 1.0 if y else 0.0) for _, d, y in samples]
        self.global_rate = fit_lambda(all_obs)
        mean_d = (sum(d for d, _ in all_obs) / len(all_obs)) if all_obs else 1.0
        p_global = 1.0 - math.exp(-self.global_rate * mean_d)
        for cls in {c for c, _, _ in samples}:
            obs = [(d, 1.0 if y else 0.0) for c, d, y in samples if c == cls]
            self.n_by_class[cls] = len(obs)
            # alpha pseudo-observations at the global rate's mean behavior
            obs = obs + [(mean_d, p_global)] * int(self.alpha)
            self.rates[cls] = fit_lambda(obs)
        return self

    def rate(self, event_class: str) -> float:
        return self.rates.get(event_class, self.global_rate)

    def predict(self, cq: CompiledHazard, asof: date) -> dict:
        """Probability + plausibility-ball band for the remaining window."""
        lam, dt = self.rate(cq.event_class), cq.exposure_years(asof)
        p = 1.0 - math.exp(-lam * dt)
        return {"probability": p,
                "band": {"lo": 1.0 - math.exp(-lam * math.exp(-self.rho) * dt),
                         "hi": 1.0 - math.exp(-lam * math.exp(+self.rho) * dt)},
                "lambda": lam, "exposure_years": dt,
                "n_class": self.n_by_class.get(cq.event_class, 0)}


def training_samples(questions, before: datetime,
                     ) -> list[tuple[str, float, bool]]:
    """Leakage-guarded training set: (class, exposure, outcome) from questions
    RESOLVED strictly before `before` that compile to hazard clocks."""
    out = []
    for q in questions:
        if q.close_time >= before:
            continue
        c = compile_hazard(q.question, q.publish_time)
        if isinstance(c, CompiledHazard):
            dt = c.exposure_years(q.publish_time.date())
            if dt > 0:
                out.append((c.event_class, dt, q.answer))
    return out
