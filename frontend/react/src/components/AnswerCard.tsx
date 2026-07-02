import { useEffect, useState } from "react";
import { AskResponse, Forecast, CalibrationReport, getCalibration } from "../api";

const pct = (p: number) => `${(100 * p).toFixed(0)}%`;

// Task 61 — track-record badge: for a forecast at probability p, report how
// often past forecasts in the same reliability bin actually verified.
let calCache: Promise<CalibrationReport> | null = null;
export function useCalibration(): CalibrationReport | null {
  const [cal, setCal] = useState<CalibrationReport | null>(null);
  useEffect(() => {
    calCache = calCache ?? getCalibration().catch(() => ({ n_scored: 0 }));
    calCache.then(setCal);
  }, []);
  return cal;
}

export function badgeFor(p: number, cal: CalibrationReport | null): string | null {
  if (!cal || !cal.n_scored || !cal.reliability_bins) return null;
  const bin = cal.reliability_bins.find(b => {
    const [lo, hi] = b.bin.split("-").map(Number);
    return p >= lo && (p < hi || (hi === 1 && p === 1));
  });
  if (!bin || bin.n < 10) return `track record: insufficient data at this level (n=${bin?.n ?? 0})`;
  return `forecasts near ${pct(bin.avg_p)} verified ${pct(bin.freq)} of the time (n=${bin.n})`;
}

export function BandBar({ f }: { f: Forecast }) {
  return (
    <div className="bar">
      <div className="fill" style={{ width: pct(f.probability) }} />
      {f.band && (
        <div className="band"
             style={{ left: pct(f.band.lo), width: pct(Math.max(0.01, f.band.hi - f.band.lo)) }} />
      )}
    </div>
  );
}

export function ForecastChip({ f }: { f: Forecast }) {
  const cal = useCalibration();
  const badge = badgeFor(f.probability, cal);
  return (
    <div className="fc">
      <span>{f.question_text}</span>
      {f.verdict && <span className={`chip ${f.verdict}`}>{f.verdict}</span>}
      <b> {pct(f.probability)}</b>
      {f.band && <span className="mut"> [{pct(f.band.lo)}–{pct(f.band.hi)}]</span>}
      <BandBar f={f} />
      {badge && <div className="badge">{badge}</div>}
    </div>
  );
}

export function AnswerCard({ resp, fallback }: { resp?: AskResponse; fallback?: string }) {
  if (!resp) return <div className="msg bot">{fallback}</div>;
  return (
    <div className="msg bot">
      <div className="md" dangerouslySetInnerHTML={{ __html: mdLite(resp.answer_markdown) }} />
      {resp.forecasts.map(f => <ForecastChip key={f.key} f={f} />)}
      {resp.counterfactual && (
        <table className="cf">
          <thead><tr><th>target</th><th>baseline</th><th>counterfactual</th><th>Δ</th></tr></thead>
          <tbody>{resp.counterfactual.effects.map(e => (
            <tr key={e.target}><td>{e.target}</td><td>{pct(e.baseline)}</td>
              <td>{pct(e.counterfactual)}</td><td>{e.rel_change_pct}%</td></tr>))}
          </tbody>
        </table>
      )}
      <div className="meta">
        intent {resp.intent} · {resp.latency_ms} ms{resp.abstained && " · abstained"}
        {resp.manifest_id &&
          <> · <a href={`/v1/audit/${resp.manifest_id}`} target="_blank">audit</a></>}
      </div>
    </div>
  );
}

function mdLite(t: string): string {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\n/g, "<br/>");
}
