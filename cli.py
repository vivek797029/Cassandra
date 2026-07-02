"""
CASSANDRA Core CLI
  python cli.py run [--fast]      full 12-phase pipeline -> output/
  python cli.py train             calibration training only, prints theta diff
  python cli.py redteam KEY ...   adversarial bands for chosen forecast keys
  python cli.py intervene         intervention portfolio search
  python cli.py forecast          quick ensemble event probabilities
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from core.engine import WorldEngine, THETA_DEFAULT, event_probs
from novelty.cassandra import CalibrationTrainer, Adversary, InterventionSearch

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        from pipeline import run
        run(fast="--fast" in sys.argv)
    elif cmd == "train":
        tr = CalibrationTrainer()
        tr.train(iters=40)
        rep = tr.report()
        print(json.dumps({k: rep[k] for k in
              ["brier_before", "brier_after", "log_before", "log_after",
               "theta_before", "theta_after"]}, indent=1))
    elif cmd == "redteam":
        keys = [a for a in sys.argv[2:] if not a.startswith("-")] or ["ME_war_1y"]
        adv = Adversary(THETA_DEFAULT, n_probe=16)
        print(json.dumps(adv.bands(keys), indent=1))
    elif cmd == "intervene":
        s = InterventionSearch(THETA_DEFAULT)
        print(json.dumps(s.greedy(), indent=1))
    elif cmd == "forecast":
        sim = WorldEngine(THETA_DEFAULT).simulate(N=8000, Q=40)
        print(json.dumps(event_probs(sim), indent=1))
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
