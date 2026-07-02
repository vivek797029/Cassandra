"""
CASSANDRA Core — World Engine
=============================
Regime-switching, agent-modulated, parameterized Monte Carlo world model.

Design goals that distinguish this engine:
  * Every behavioral constant lives in a named THETA vector -> the entire
    simulator is a function world(theta), so it can be TRAINED on proper
    scoring rules (novelty/cassandra.py) and ATTACKED by an adversary.
  * A strategic-actor layer (boundedly rational softmax policies) modulates
    the Markov hazards each quarter -> hazards are endogenous, not constants.
  * A 'replay' mode re-initializes the world at a past date so forecasts can
    be scored against events that have ALREADY resolved (leakage-firewalled
    backtesting: parameters never see the outcomes directly, only the loss).

Regimes:
  ME (Middle East): 0 settled | 1 fragile ceasefire | 2 active war | 3 Hormuz closure
  UA (Ukraine):     0 ceasefire/frozen | 1 low-intensity | 2 active war
  TW (Taiwan):      0 status quo | 1 blockade/quarantine | 2 armed conflict
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field

# ----------------------------------------------------------------------------
# THETA: the learnable parameter vector
# ----------------------------------------------------------------------------
THETA_SPEC = [
    # name,                default, lo,     hi
    ("me_esc_base",        0.045,   0.005,  0.20),   # ME ceasefire->war hazard floor /q
    ("me_esc_decay_amp",   0.110,   0.0,    0.40),   # front-loaded extra hazard (succession)
    ("me_hz_base",         0.004,   0.0005, 0.05),   # ceasefire->Hormuz direct hazard
    ("me_hz_decay_amp",    0.030,   0.0,    0.15),
    ("me_deesc_base",      0.090,   0.01,   0.40),   # ceasefire->settled
    ("me_war_deesc",       0.320,   0.05,   0.60),   # war->ceasefire (wars are short, intense)
    ("me_hz_persist",      0.450,   0.10,   0.85),   # Hormuz closure persistence
    ("me_war_hz_base",     0.060,   0.01,   0.45),   # ACTIVE-WAR -> Hormuz hazard /q
    ("ua_cf_base",         0.050,   0.005,  0.30),   # UA war->frozen hazard floor
    ("ua_cf_ramp",         0.040,   0.0,    0.20),   # rises with exhaustion
    ("tw_block_base",      0.0055,  0.0005, 0.04),   # TW blockade hazard /q
    ("oil_jump_war",       1.12,    1.0,    1.6),    # multiplicative shock on war entry
    ("oil_jump_hormuz",    1.30,    1.0,    2.0),
    ("oil_pass_infl",      0.024,   0.005,  0.08),   # pp inflation per $1 above $80
    ("oil_drag_growth",    0.018,   0.005,  0.06),   # pp growth per $1 above $80
    ("em_haz_base",        0.022,   0.005,  0.10),   # EM default-event hazard floor
]
THETA_NAMES = [s[0] for s in THETA_SPEC]
THETA_DEFAULT = np.array([s[1] for s in THETA_SPEC])
THETA_LO = np.array([s[2] for s in THETA_SPEC])
THETA_HI = np.array([s[3] for s in THETA_SPEC])

def clip_theta(theta: np.ndarray) -> np.ndarray:
    return np.clip(theta, THETA_LO, THETA_HI)

def theta_dict(theta: np.ndarray) -> dict:
    return dict(zip(THETA_NAMES, theta))

# ----------------------------------------------------------------------------
# Strategic actor layer (Phase 6: agent-based modulation)
# ----------------------------------------------------------------------------
# Each actor has a state-dependent 'stance' in [0,1] produced by a softmax/
# logistic policy over simple utility features. Stances multiply hazards.
# This keeps agents cheap (vectorized) while making escalation ENDOGENOUS:
# e.g. cheap oil starves Iran's budget -> revenge stance falls; a distracted
# US raises PRC opportunism; war fatigue raises Russia's settlement stance.

def actor_stances(t, oil, grow, me_state, ua_state, rngN):
    sig = lambda x: 1.0 / (1.0 + np.exp(-x))
    # IRAN hardliner stance: humiliation decays, oil revenue need pushes risk
    iran = sig(1.2 - 0.12 * t + 0.8 * (oil < 80) - 0.6 * (oil > 110))
    # US strike posture: reactive, rises while war regime active
    us = sig(-0.5 + 1.5 * (me_state >= 2))
    # RUSSIA settlement stance: fatigue ramp + economic pain when oil is low
    russia = sig(-1.0 + 0.10 * t + 0.9 * (oil < 75))
    # PRC opportunism: rises when US visibly engaged in ME, falls when economy weak
    prc = sig(-1.6 + 1.1 * (me_state >= 2) + 0.5 * (ua_state == 2) - 0.7 * (grow < 2.4))
    return iran, us, russia, prc

# ----------------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------------
@dataclass
class WorldState:
    """Initial conditions (default = 11 June 2026 observed)."""
    oil: float = 94.0        # Brent, 10 Jun 2026
    growth: float = 3.1      # IMF WEO Apr-2026 reference, 2026
    inflation: float = 4.4   # IMF WEO Apr-2026 reference, 2026
    me: int = 1              # fragile ceasefire
    ua: int = 2              # active war
    tw: int = 0              # status quo
    label: str = "2026Q3"

REPLAY_FEB2026 = WorldState(oil=82.0, growth=3.3, inflation=4.2,
                            me=2, ua=2, tw=0, label="2026Q1-replay")

OIL_ANCHOR = np.array([70.0, 88.0, 112.0, 138.0])
G_PENALTY  = np.array([+0.15, 0.0, -0.55, -1.25])
PI_PREMIUM = np.array([-0.2, 0.0, +0.7, +1.6])

class WorldEngine:
    def __init__(self, theta: np.ndarray | None = None, seed: int = 42):
        self.theta = clip_theta(np.array(theta if theta is not None else THETA_DEFAULT, float))
        self.seed = seed

    # -- transition builders ------------------------------------------------
    def _me_pmat(self, state, t, N, iran, us):
        th = theta_dict(self.theta)
        decay = np.exp(-t / 12.0)
        esc = (th["me_esc_base"] + th["me_esc_decay_amp"] * decay) * (0.5 + iran)      # agent-modulated
        hz  = (th["me_hz_base"] + th["me_hz_decay_amp"] * decay) * (0.5 + 0.7 * iran)
        de  = th["me_deesc_base"] * (1.6 - iran)
        p = np.zeros((N, 4))
        s0, s1, s2, s3 = (state == i for i in range(4))
        p[s0] = [0.93, 0.05, 0.018, 0.002]
        p[s1, 0] = de[s1]; p[s1, 2] = esc[s1]; p[s1, 3] = hz[s1]
        p[s1, 1] = 1.0 - p[s1, 0] - p[s1, 2] - p[s1, 3]
        # active war: US posture raises Hormuz risk; war de-escalates at me_war_deesc
        p[s2, 0] = 0.03; p[s2, 1] = th["me_war_deesc"]
        p[s2, 3] = th["me_war_hz_base"] * (0.6 + 0.8 * us[s2])
        p[s2, 2] = 1.0 - p[s2, 0] - p[s2, 1] - p[s2, 3]
        p[s3, 3] = th["me_hz_persist"]; p[s3, 0] = 0.02
        p[s3, 2] = 0.35; p[s3, 1] = 1.0 - p[s3, 3] - p[s3, 0] - p[s3, 2]
        p = np.clip(p, 1e-6, None)
        return p / p.sum(1, keepdims=True)

    def _ua_pmat(self, state, t, N, russia):
        th = theta_dict(self.theta)
        ramp = min(t / 8.0, 1.0)
        cf = (th["ua_cf_base"] + th["ua_cf_ramp"] * ramp) * (0.5 + russia)
        p = np.zeros((N, 3))
        s0, s1, s2 = (state == i for i in range(3))
        p[s0] = [0.90, 0.08, 0.02]
        p[s1] = [0.12, 0.70, 0.18]
        p[s2, 0] = cf[s2]; p[s2, 1] = 0.10; p[s2, 2] = 1.0 - cf[s2] - 0.10
        p = np.clip(p, 1e-6, None)
        return p / p.sum(1, keepdims=True)

    def _tw_pmat(self, state, t, N, prc):
        th = theta_dict(self.theta)
        window = 1.0 + 0.5 * np.exp(-((t - 22) ** 2) / 60.0)   # 2030-32 window
        pb = th["tw_block_base"] * window * (0.5 + prc)
        pc = 0.16 * pb                                          # conflict mostly via blockade
        p = np.zeros((N, 3))
        s0, s1, s2 = (state == i for i in range(3))
        p[s0, 1] = pb[s0]; p[s0, 2] = pc[s0]; p[s0, 0] = 1.0 - pb[s0] - pc[s0]
        p[s1] = [0.22, 0.66, 0.12]
        p[s2] = [0.05, 0.15, 0.80]
        p = np.clip(p, 1e-6, None)
        return p / p.sum(1, keepdims=True)

    # -- main simulate -------------------------------------------------------
    def simulate(self, N=20000, Q=40, start: WorldState | None = None,
                 hazard_mods: dict | None = None, seed: int | None = None) -> dict:
        """hazard_mods: optional multiplicative intervention handles, e.g.
        {'me_esc':0.8,'me_hz':0.6,'em_haz':0.7,'food_shock':0.8,'tw_block':0.85}"""
        th = theta_dict(self.theta)
        hm = {"me_esc": 1.0, "me_hz": 1.0, "em_haz": 1.0, "food_shock": 1.0,
              "tw_block": 1.0, "ua_cf": 1.0}
        if hazard_mods: hm.update(hazard_mods)
        s = start or WorldState()
        rng = np.random.default_rng(self.seed if seed is None else seed)
        vcat = lambda pm, u: (u[:, None] > np.cumsum(pm, 1)).sum(1)

        oil = np.full(N, s.oil); grow = np.full(N, s.growth); infl = np.full(N, s.inflation)
        me = np.full(N, s.me); ua = np.full(N, s.ua); tw = np.full(N, s.tw)
        ai_max = rng.lognormal(np.log(0.35), 0.45, N)
        elnino = rng.random(N) < 0.82
        fmag = rng.uniform(0.10, 0.22, N) * elnino * hm["food_shock"]
        P_oil = np.zeros((N, Q)); P_g = np.zeros((N, Q)); P_pi = np.zeros((N, Q))
        H_me = np.zeros((N, Q), int); H_ua = np.zeros((N, Q), int); H_tw = np.zeros((N, Q), int)
        em_def = np.zeros(N); food = np.full(N, 100.0)
        A_iran = np.zeros((N, Q))

        for t in range(Q):
            iran, us, russia, prc = actor_stances(t, oil, grow, me, ua, N)
            pme = self._me_pmat(me, t, N, iran, us)
            pme[:, 2] *= hm["me_esc"]; pme[:, 3] *= hm["me_hz"]
            pme = pme / pme.sum(1, keepdims=True)
            pua = self._ua_pmat(ua, t, N, russia)
            pua[:, 0] = np.minimum(pua[:, 0] * hm["ua_cf"], 0.9)
            pua = pua / pua.sum(1, keepdims=True)
            ptw = self._tw_pmat(tw, t, N, prc)
            ptw[:, 1] *= hm["tw_block"]
            ptw = ptw / ptw.sum(1, keepdims=True)
            me_prev = me.copy()
            me = vcat(pme, rng.random(N)); ua = vcat(pua, rng.random(N)); tw = vcat(ptw, rng.random(N))

            jump = np.where((me == 3) & (me_prev < 3), th["oil_jump_hormuz"],
                    np.where((me == 2) & (me_prev < 2), th["oil_jump_war"], 1.0))
            anchor = OIL_ANCHOR[me] + np.where(tw == 1, 18, 0) + np.where(tw == 2, 55, 0)
            vol = np.where(me >= 2, 0.10, 0.06)
            oil = np.clip((oil + 0.35 * (anchor - oil)) * jump + oil * rng.normal(0, 1, N) * vol, 35, 320)
            yr = t / 4.0
            ai = ai_max / (1 + np.exp(-(yr - 4.5)))
            fshk = np.where((t >= 2) & (t <= 6), fmag / 4, 0)
            food *= (1 + 0.0375 * (oil / 94 - 1) + fshk + rng.normal(0, 0.02, N))
            g_t = (3.35 + ai + G_PENALTY[me] + np.where(ua == 2, -0.10, 0)
                   + np.where(tw == 1, -0.9, 0) + np.where(tw == 2, -3.0, 0)
                   - th["oil_drag_growth"] * np.maximum(oil - 80, 0))
            grow = grow + 0.40 * (g_t - grow) + rng.normal(0, 0.22, N)
            pi_t = (2.9 + 1.3 * np.exp(-t / 3.0) + PI_PREMIUM[me]
                    + th["oil_pass_infl"] * np.maximum(oil - 80, 0)
                    + 0.018 * np.maximum(food - 105, 0))
            infl = np.clip(infl + 0.35 * (pi_t - infl) + rng.normal(0, 0.25, N), -1, 25)
            haz = (th["em_haz_base"] + 0.0008 * np.maximum(oil - 85, 0)
                   + 0.004 * np.maximum(infl - 4.5, 0) + 0.006 * np.maximum(2.8 - grow, 0)) * hm["em_haz"]
            em_def += rng.random(N) < np.clip(haz, 0, 0.5)
            P_oil[:, t] = oil; P_g[:, t] = grow; P_pi[:, t] = infl
            H_me[:, t] = me; H_ua[:, t] = ua; H_tw[:, t] = tw; A_iran[:, t] = iran

        return {"oil": P_oil, "growth": P_g, "inflation": P_pi,
                "me": H_me, "ua": H_ua, "tw": H_tw, "em_def": em_def,
                "iran_stance": A_iran, "ai_max": ai_max, "start": s.label, "N": N, "Q": Q}

# ----------------------------------------------------------------------------
# Event extractors: world paths -> named binary event probabilities
# ----------------------------------------------------------------------------
def event_probs(sim: dict) -> dict:
    me, ua, tw = sim["me"], sim["ua"], sim["tw"]
    oil, g, pi = sim["oil"], sim["growth"], sim["inflation"]
    Pm = lambda x: float(np.mean(x))
    ann = lambda a, q0: a[:, q0:q0 + 4].mean(1)
    out = {
        "ME_war_180d":            Pm((me[:, :2] >= 2).any(1)),
        "ME_war_1y":              Pm((me[:, :4] >= 2).any(1)),
        "ME_war_3y":              Pm((me[:, :12] >= 2).any(1)),
        "Hormuz_closure_by_end2027": Pm((me[:, :6] == 3).any(1)),
        "ME_durable_settlement_3y":  Pm(me[:, 11] == 0) if me.shape[1] > 11 else None,
        "UA_ceasefire_by_end2026":   Pm((ua[:, :2] <= 1).any(1)),
        "UA_formal_ceasefire_by_end2027": Pm((ua[:, :6] == 0).any(1)),
        "TW_blockade_by_2030":    Pm((tw[:, :16] >= 1).any(1)) if tw.shape[1] >= 16 else None,
        "TW_blockade_by_2033":    Pm((tw[:, :28] >= 1).any(1)) if tw.shape[1] >= 28 else None,
        "TW_conflict_by_2036":    Pm((tw[:, :40] == 2).any(1)) if tw.shape[1] >= 40 else None,
        "Brent_gt120_1y":         Pm((oil[:, :4] > 120).any(1)),
        "Brent_gt150_2y":         Pm((oil[:, :8] > 150).any(1)) if oil.shape[1] >= 8 else None,
        "Global_recession_lt2p5_by_2028":
            Pm((np.stack([ann(g, 2), ann(g, 6)], 1) < 2.5).any(1)) if g.shape[1] >= 10 else None,
        "Inflation_gt5_2027avg":  Pm(ann(pi, 2) > 5.0) if pi.shape[1] >= 6 else None,
        "EM_default_quarters_ge3_by_2028": Pm(sim["em_def"] >= 3),
    }
    misery = pi[:, min(1, pi.shape[1]-1)] + np.maximum(0, 4.0 - g[:, min(1, g.shape[1]-1)])
    out["Dem_House_Nov2026"] = float(np.mean(1 / (1 + np.exp(-(0.9 + 0.25 * (misery - 5.4))))))
    return {k: (round(v, 4) if v is not None else None) for k, v in out.items()}

# Replay events: resolved Feb->Jun 2026 (outcome, extractor over a 2-quarter replay sim)
RESOLVED_EVENTS = [
    ("Hormuz closed within 2q of war",        1, lambda s: (s["me"][:, :2] == 3).any(1)),
    ("Brent >$120 within 2q",                 1, lambda s: (s["oil"][:, :2] > 120).any(1)),
    ("Ceasefire reached within 2q",           1, lambda s: (s["me"][:, :2] <= 1).any(1)),
    ("Oil back <$100 at end of 2q",           1, lambda s: s["oil"][:, 1] < 100),
    ("H1 mean growth <3.2",                   1, lambda s: s["growth"][:, :2].mean(1) < 3.2),
    ("H1 mean inflation >4.2",                1, lambda s: s["inflation"][:, :2].mean(1) > 4.2),
    ("Taiwan blockade in H1",                 0, lambda s: (s["tw"][:, :2] >= 1).any(1)),
    ("Ukraine ceasefire by Jun",              0, lambda s: (s["ua"][:, :2] == 0).any(1)),
    ("Brent >$150 in H1",                     0, lambda s: (s["oil"][:, :2] > 150).any(1)),
    ("ME fully settled by Jun",               0, lambda s: s["me"][:, 1] == 0),
]

def replay_event_probs(engine: WorldEngine, N=3000, seed=7, events=None,
                       Q: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Simulate the Feb-2026 replay and score an event set against it.

    events: [(name, outcome, extractor(sim)->bool array)] — defaults to the
    hand-built RESOLVED_EVENTS. Q defaults to 2 (the original H1-2026 window);
    registry-derived event sets (Task 51) may need more quarters."""
    ev = events if events is not None else RESOLVED_EVENTS
    sim = engine.simulate(N=N, Q=Q or 2, start=REPLAY_FEB2026, seed=seed)
    preds = np.array([float(np.mean(fn(sim))) for _, _, fn in ev])
    outs = np.array([o for _, o, _ in ev], float)
    return preds, outs
