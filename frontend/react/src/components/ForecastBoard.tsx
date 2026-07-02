import { Forecast } from "../api";
import { ForecastChip } from "./AnswerCard";

export function ForecastBoard({ forecasts }: { forecasts: Forecast[] }) {
  const sorted = [...forecasts].sort((a, b) => b.probability - a.probability);
  return (
    <main className="board">
      <p className="mut">
        All probabilities from the calibration-trained ensemble; red strips are
        adversarial-conformal bands; verdict chips grade robustness under parameter attack.
      </p>
      <div className="grid">
        {sorted.map(f => <ForecastChip key={f.key} f={f} />)}
      </div>
    </main>
  );
}
