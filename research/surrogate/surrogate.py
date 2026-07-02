"""Task 84 — surrogate spike (blueprint B6).

A neural surrogate that maps (state, theta, do-clause) -> headline event
probabilities, approximating the expensive Monte-Carlo world-twin. Training labels
are computed at a FIXED common-random-number seed, so the target is a deterministic
smooth surface the MLP can fit to high accuracy. The surrogate then answers
what-if/counterfactual queries ~100x faster than re-running the simulation — the
B6 building block feeding the Task-85 counterfactual cache.

Goal (this spike): >=100x speedup vs the full sim, held-out error < 2pp.

    python -m research.surrogate.surrogate          # train + print metrics
"""
from __future__ import annotations
import time
import numpy as np

from core.engine import THETA_DEFAULT, THETA_NAMES, WorldEngine, event_probs

SEED = 42
DO_HANDLES = ["me_esc", "me_hz", "em_haz", "food_shock", "tw_block", "ua_cf"]
HEADLINE = ["ME_war_1y", "Hormuz_closure_by_end2027", "Brent_gt120_1y",
            "Global_recession_lt2p5_by_2028", "Inflation_gt5_2027avg",
            "UA_formal_ceasefire_by_end2027"]
_IDX = {n: i for i, n in enumerate(THETA_NAMES)}
# input = 6 do-handles + 1 theta-perturbation scalar
DO_LO, DO_HI = 0.60, 1.20
TH_LO, TH_HI = 0.90, 1.10


def _perturbed_theta(scale: float) -> np.ndarray:
    th = np.array(THETA_DEFAULT, dtype=float)
    for n in ("oil_jump_war", "oil_jump_hormuz", "em_haz_base"):
        if n in _IDX:
            th[_IDX[n]] *= scale
    return th


def simulate_probs(x: np.ndarray, N: int = 1500, Q: int = 12) -> np.ndarray:
    """The expensive ground truth: do-handles + theta scale -> headline probs (fixed CRN)."""
    hm = {h: float(x[i]) for i, h in enumerate(DO_HANDLES)}
    theta = _perturbed_theta(float(x[6]))
    sim = WorldEngine(theta=theta, seed=SEED).simulate(N=N, Q=Q, seed=SEED, hazard_mods=hm)
    ev = event_probs(sim)
    return np.array([ev[k] for k in HEADLINE], dtype=float)


def generate_dataset(n: int, N: int = 1500, Q: int = 12, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = np.empty((n, 7)); Y = np.empty((n, len(HEADLINE)))
    X[:, :6] = rng.uniform(DO_LO, DO_HI, (n, 6))
    X[:, 6] = rng.uniform(TH_LO, TH_HI, n)
    for i in range(n):
        Y[i] = simulate_probs(X[i], N=N, Q=Q)
    return X, Y


class MLP:
    """Tiny 1-hidden-layer MLP (tanh → sigmoid), Adam, full-batch. No deps beyond numpy."""

    def __init__(self, din: int, dh: int = 64, dout: int = 6, seed: int = 0):
        g = np.random.default_rng(seed)
        self.W1 = g.normal(0, 1 / np.sqrt(din), (din, dh)); self.b1 = np.zeros(dh)
        self.W2 = g.normal(0, 1 / np.sqrt(dh), (dh, dout)); self.b2 = np.zeros(dout)
        self.mu = np.zeros(din); self.sd = np.ones(din)

    def _fwd(self, Xn):
        self.A1 = np.tanh(Xn @ self.W1 + self.b1)
        self.P = 1.0 / (1.0 + np.exp(-(self.A1 @ self.W2 + self.b2)))
        return self.P

    def fit(self, X, Y, epochs: int = 4000, lr: float = 0.01):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Xn = (X - self.mu) / self.sd
        params = [self.W1, self.b1, self.W2, self.b2]
        m = [np.zeros_like(p) for p in params]; v = [np.zeros_like(p) for p in params]
        b1, b2, eps = 0.9, 0.999, 1e-8
        n = len(X)
        for t in range(1, epochs + 1):
            P = self._fwd(Xn)
            dZ2 = (P - Y) * P * (1 - P) * (2.0 / n)
            dW2 = self.A1.T @ dZ2; db2 = dZ2.sum(0)
            dZ1 = (dZ2 @ self.W2.T) * (1 - self.A1 ** 2)
            dW1 = Xn.T @ dZ1; db1 = dZ1.sum(0)
            for i, gd in enumerate((dW1, db1, dW2, db2)):
                m[i] = b1 * m[i] + (1 - b1) * gd
                v[i] = b2 * v[i] + (1 - b2) * gd * gd
                mh = m[i] / (1 - b1 ** t); vh = v[i] / (1 - b2 ** t)
                params[i] -= lr * mh / (np.sqrt(vh) + eps)
        return self

    def predict(self, X):
        return self._fwd((X - self.mu) / self.sd)


def build(n_train: int = 500, n_test: int = 150, N: int = 1500, epochs: int = 4000) -> dict:
    Xtr, Ytr = generate_dataset(n_train, N=N, seed=1)
    Xte, Yte = generate_dataset(n_test, N=N, seed=2)
    model = MLP(din=7, dh=64, dout=len(HEADLINE), seed=0).fit(Xtr, Ytr, epochs=epochs)

    pred = model.predict(Xte)
    mae = float(np.mean(np.abs(pred - Yte)))
    max_err = float(np.max(np.abs(pred - Yte)))

    # speedup: full sim vs surrogate over the held-out inputs
    t0 = time.time()
    for i in range(len(Xte)):
        simulate_probs(Xte[i], N=N)
    sim_s = time.time() - t0
    t0 = time.time()
    for _ in range(50):
        model.predict(Xte)
    surr_s = (time.time() - t0) / 50
    speedup = sim_s / max(surr_s, 1e-9)

    return {"mae": mae, "max_err": max_err, "speedup": speedup,
            "n_train": n_train, "n_test": n_test, "model": model}


def main() -> int:
    r = build()
    print(f"surrogate B6: MAE={r['mae']*100:.2f}pp  max_err={r['max_err']*100:.2f}pp  "
          f"speedup={r['speedup']:.0f}x  (train={r['n_train']}, test={r['n_test']})")
    ok = r["mae"] < 0.02 and r["speedup"] >= 100
    print("SPIKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
