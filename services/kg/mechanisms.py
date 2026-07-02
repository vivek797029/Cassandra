"""Single registry of mechanism cards (blueprint §5) — Task 57.

Each card binds simulator theta parameters to a causal mechanism with an
identification status. The GATE rule (blueprint §3/§5): parameters owned by a
`hypothesis`-grade mechanism may NOT deviate from the expert prior — trained
values are reverted before deployment. identified/estimated/expert feed the
simulator; `estimated` carries a confounding-risk flag in reports.

Cards are the shared source of truth for services/kg/loader.py (graph MERGE)
and services/kg/gate.py (theta gating).
"""
from __future__ import annotations

ALLOWED_STATUSES = {"identified", "estimated", "expert"}     # hypothesis -> blocked

MECHANISM_CARDS = [
    # id, from_var, to_var, form, id_status, sign, lag_q, theta_params
    {"id": "me_war__oil", "from": "me_regime", "to": "brent_usd",
     "form": "regime_anchor_jump", "id_status": "identified", "sign": 1, "lag_q": 0,
     "params": ["oil_jump_war", "oil_jump_hormuz"]},
    {"id": "me_escalation", "from": "me_regime", "to": "me_regime",
     "form": "markov_hazard", "id_status": "identified", "sign": 1, "lag_q": 0,
     "params": ["me_esc_base", "me_esc_decay_amp", "me_hz_base", "me_hz_decay_amp",
                "me_deesc_base", "me_war_deesc", "me_hz_persist", "me_war_hz_base"]},
    {"id": "ua_settlement", "from": "ua_regime", "to": "ua_regime",
     "form": "markov_hazard", "id_status": "expert", "sign": -1, "lag_q": 0,
     "params": ["ua_cf_base", "ua_cf_ramp"]},
    {"id": "tw_coercion", "from": "tw_regime", "to": "tw_regime",
     "form": "markov_hazard", "id_status": "expert", "sign": 1, "lag_q": 0,
     "params": ["tw_block_base"]},
    {"id": "oil__inflation", "from": "brent_usd", "to": "infl_global",
     "form": "linear_passthrough_above_80", "id_status": "estimated", "sign": 1,
     "lag_q": 1, "params": ["oil_pass_infl"]},
    {"id": "oil__growth", "from": "brent_usd", "to": "growth_global",
     "form": "linear_drag_above_80", "id_status": "estimated", "sign": -1,
     "lag_q": 1, "params": ["oil_drag_growth"]},
    {"id": "food__em_stress", "from": "food_idx", "to": "em_defaults",
     "form": "hazard_increment", "id_status": "expert", "sign": 1, "lag_q": 2,
     "params": ["em_haz_base"]},
]


def card_for_param(param: str) -> dict | None:
    for c in MECHANISM_CARDS:
        if param in c["params"]:
            return c
    return None
