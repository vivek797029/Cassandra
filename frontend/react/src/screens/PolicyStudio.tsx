// Task 59 — Policy Studio: budget slider -> /v1/policy/optimize -> portfolio,
// greedy marginal value/cost curve, and single-intervention ranking.
import { useEffect, useRef, useState } from "react";
import { optimizePolicy, PolicyRecommendation } from "../api";

export function PolicyStudio() {
  const [budget, setBudget] = useState(8);
  const [rec, setRec] = useState<PolicyRecommendation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const timer = useRef<number | undefined>(undefined);

  // debounce slider -> one optimize call per settle
  useEffect(() => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => {
      setBusy(true); setErr("");
      try { setRec(await optimizePolicy(budget)); }
      catch (e) { setErr(String(e)); }
      finally { setBusy(false); }
    }, 350);
    return () => window.clearTimeout(timer.current);
  }, [budget]);

  const maxMv = rec ? Math.max(...rec.greedy_steps.map(s => s.marginal_value_per_cost), 0.01) : 1;

  return (
    <main className="board">
      <div className="studio-head">
        <label>
          Budget <b>{budget.toFixed(1)}</b> (index units)
          <input type="range" min={2} max={14} step={0.5} value={budget}
                 onChange={e => setBudget(Number(e.target.value))} />
        </label>
        {busy && <span className="mut">optimizing…</span>}
        {err && <span className="err">{err}</span>}
      </div>

      {rec && (
        <>
          <section className="card">
            <h2>Portfolio (greedy robust-EV search)</h2>
            <p>
              Harm index <b>{rec.base_harm}</b> → <b>{rec.portfolio_harm}</b>{" "}
              (−{rec.harm_reduction_pct}%) · spent {rec.spent}/{rec.budget}
            </p>
            <div className="mut">{rec.portfolio.join(" → ") || "nothing affordable"}</div>
          </section>

          <section className="card">
            <h2>Marginal value per cost (greedy step curve)</h2>
            {rec.greedy_steps.map((s, i) => (
              <div className="bar-row" key={s.added}>
                <span className="bar-label">{i + 1}. {s.added} (cost {s.cost})</span>
                <div className="bar">
                  <div className="fill"
                       style={{ width: `${(100 * s.marginal_value_per_cost) / maxMv}%` }} />
                </div>
                <span className="bar-val">{s.marginal_value_per_cost.toFixed(3)}</span>
              </div>
            ))}
            {rec.greedy_steps.length === 0 && <p className="mut">no steps within budget</p>}
          </section>

          <section className="card">
            <h2>Single-intervention ranking</h2>
            <table className="cf">
              <thead><tr><th>intervention</th><th>cost</th><th>harm Δ</th>
                <th>value/cost</th></tr></thead>
              <tbody>
                {rec.singles_ranked.map(s => (
                  <tr key={s.name}><td>{s.name}</td><td>{s.cost}</td>
                    <td>{s.harm_reduction}</td><td>{s.value_per_cost}</td></tr>))}
              </tbody>
            </table>
            <p className="mut">{rec.caveats.join(" · ")}</p>
          </section>
        </>
      )}
    </main>
  );
}
