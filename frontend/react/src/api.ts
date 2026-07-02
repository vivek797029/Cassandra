// ARGUS API client — typed mirror of services/copilot/schemas.py
const BASE = import.meta.env.VITE_API_BASE ?? "";

export interface Band { lo: number; hi: number; conformal_q80?: number }
export interface Forecast {
  key: string; question_text: string; probability: number;
  band?: Band | null; verdict?: string | null; horizon?: string | null;
  confidence?: string | null; manifest_id?: string | null;
}
export interface Explanation {
  forecast: string; probability?: number; evidence: string[];
  causal_pathway: string; historical_analog: string; counterargument: string;
  confidence: string; failure_conditions: string[];
}
export interface EffectEstimate {
  target: string; baseline: number; counterfactual: number;
  delta: number; rel_change_pct: number;
}
export interface CounterfactualResult {
  effects: EffectEstimate[]; harm_baseline: number; harm_counterfactual: number;
  assumptions: string[]; manifest_id: string;
}
export interface PolicyRecommendation {
  budget: number; spent: number; portfolio: string[];
  base_harm: number; portfolio_harm: number; harm_reduction_pct: number;
  greedy_steps: { added: string; cost: number; portfolio_harm: number;
                  marginal_value_per_cost: number }[];
  singles_ranked: { name: string; cost: number; harm_reduction: number;
                    value_per_cost: number; desc: string }[];
  caveats: string[]; manifest_id: string;
}
export interface AskResponse {
  session_id: string; intent: string; answer_markdown: string;
  forecasts: Forecast[]; explanation?: Explanation | null;
  counterfactual?: CounterfactualResult | null;
  policy?: PolicyRecommendation | null;
  abstained: boolean; manifest_id: string; latency_ms: number;
}

export async function ask(text: string, persona = "analyst",
                          sessionId?: string): Promise<AskResponse> {
  const r = await fetch(`${BASE}/v1/ask`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, persona, session_id: sessionId }),
  });
  if (!r.ok) throw new Error(`ask failed: ${r.status}`);
  return r.json();
}
export const getForecasts = (): Promise<Forecast[]> =>
  fetch(`${BASE}/v1/forecasts`).then(r => r.json());
export const getEwi = () => fetch(`${BASE}/v1/ewi`).then(r => r.json());
export const getScenarios = () => fetch(`${BASE}/v1/scenarios`).then(r => r.json());

export async function optimizePolicy(budget: number): Promise<PolicyRecommendation> {
  const r = await fetch(`${BASE}/v1/policy/optimize?budget=${budget}`, { method: "POST" });
  if (!r.ok) throw new Error(`optimize failed: ${r.status}`);
  return r.json();
}

export interface ReliabilityBin { bin: string; n: number; avg_p: number; freq: number }
export interface CalibrationReport {
  n_scored: number; brier?: number; ece?: number | null;
  brier_skill_score?: number; reliability_bins?: ReliabilityBin[];
  by_stratum?: Record<string, { n: number; brier: number; avg_p: number;
                                base_rate: number }>;
}
export const getCalibration = (): Promise<CalibrationReport> =>
  fetch(`${BASE}/v1/calibration`).then(r => r.json());

export interface Alert {
  indicator: string; severity: string; value: number | null;
  threshold: number | null; message: string; fired_at: number;
}
export const getAlerts = (since = 0): Promise<{ alerts: Alert[]; served_at: number }> =>
  fetch(`${BASE}/v1/ewi/alerts?since=${since}`).then(r => r.json());
