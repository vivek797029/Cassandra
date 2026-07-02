"""ARGUS Copilot — canonical API schemas (Pydantic).
These mirror db/postgres/001_init.sql and db/neo4j/schema.cypher."""
from __future__ import annotations
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field

Persona = Literal["principal", "analyst", "planner", "watch"]
Intent = Literal["FORECAST", "EXPLAIN", "CAUSE", "WHATIF", "POLICY",
                 "EWI", "VULNERABILITY", "ANALOG", "SCENARIOS", "STATUS", "UNKNOWN"]

# ---------- event / fact ----------
class Fact(BaseModel):
    id: str
    domain: str
    text: str
    source: str

class Signal(BaseModel):
    name: str
    strength: int
    reliability: int
    growth: str
    horizon: str
    impact: str
    fact_ids: list[str] = []

# ---------- forecast ----------
class Band(BaseModel):
    lo: float
    hi: float
    conformal_q80: Optional[float] = None

class Forecast(BaseModel):
    key: str
    question_text: str
    probability: float
    band: Optional[Band] = None
    verdict: Optional[str] = None            # ROBUST | SENSITIVE | FRAGILE
    horizon: Optional[str] = None
    confidence: Optional[str] = None
    manifest_id: Optional[str] = None

class FanSeries(BaseModel):
    variable: str
    years: list[int]
    p10: list[float]; p25: list[float]; p50: list[float]; p75: list[float]; p90: list[float]

# ---------- explanation ----------
class Explanation(BaseModel):
    forecast: str
    probability: Optional[float] = None
    evidence: list[str] = []
    causal_pathway: str = ""
    historical_analog: str = ""
    counterargument: str = ""
    confidence: str = "low"
    failure_conditions: list[str] = []

# ---------- counterfactual ----------
class DoClause(BaseModel):
    """Either named interventions or raw hazard modifiers."""
    interventions: list[str] = []
    hazard_mods: dict[str, float] = {}

class CounterfactualRequest(BaseModel):
    do: DoClause
    targets: list[str] = Field(default_factory=lambda: ["ME_war_1y", "Brent_gt120_1y"])
    horizon_quarters: int = 12
    n_paths: int = 2000

class EffectEstimate(BaseModel):
    target: str
    baseline: float
    counterfactual: float
    delta: float
    rel_change_pct: float

class CounterfactualResult(BaseModel):
    request: CounterfactualRequest
    effects: list[EffectEstimate]
    harm_baseline: float
    harm_counterfactual: float
    assumptions: list[str]
    manifest_id: str

# ---------- policy ----------
class PolicyStep(BaseModel):
    added: str
    cost: float
    portfolio_harm: float
    marginal_value_per_cost: float

class PolicySingle(BaseModel):
    name: str
    cost: float
    harm_reduction: float
    value_per_cost: float
    desc: str

class PolicyRecommendation(BaseModel):
    budget: float
    spent: float
    portfolio: list[str]
    base_harm: float
    portfolio_harm: float
    harm_reduction_pct: float
    greedy_steps: list[PolicyStep]
    singles_ranked: list[PolicySingle]
    caveats: list[str]
    manifest_id: str

# ---------- analogs / EWI ----------
class Analog(BaseModel):
    name: str
    similarity: int
    similar: str
    different: str
    outcome: str
    lesson: str
    policy_success: str
    policy_failure: str

class EarlyWarning(BaseModel):
    indicator: str
    metric: str
    threshold: str
    lead_time: str
    confidence: str

# ---------- copilot ----------
class AskRequest(BaseModel):
    text: str
    persona: Persona = "analyst"
    session_id: Optional[str] = None

class DissentRequest(BaseModel):              # Task 87: analyst right-of-reply
    key: str
    text: str

class AskResponse(BaseModel):
    session_id: str
    intent: Intent
    parse: dict[str, Any] = {}
    answer_markdown: str
    forecasts: list[Forecast] = []
    explanation: Optional[Explanation] = None
    counterfactual: Optional[CounterfactualResult] = None
    policy: Optional[PolicyRecommendation] = None
    analogs: list[Analog] = []
    early_warnings: list[EarlyWarning] = []
    abstained: bool = False
    degraded: bool = False                        # Task 70: served from a stale snapshot
    staleness: Optional[dict[str, Any]] = None    # as_of / cached_at / age when degraded
    manifest_id: str
    latency_ms: int

class Manifest(BaseModel):
    manifest_id: str
    created_at: str
    kind: str
    theta_hash: str
    seed: int
    snapshot: str
    payload: dict[str, Any] = {}
