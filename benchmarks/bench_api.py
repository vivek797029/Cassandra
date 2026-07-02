"""ARGUS Copilot latency/throughput benchmark.
Run: python3 benchmarks/bench_api.py (from repo root)
SLOs (Phase-1): read p95 < 50ms · whatif p95 < 500ms · policy p95 < 2s · startup < 30s."""
import sys, os, time, statistics as st
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_DB", "/tmp/argus/bench.db")
from fastapi.testclient import TestClient
from services.copilot.main import app

CASES = {
    "read:forecasts": ("GET", "/v1/forecasts", None, 30),
    "read:ewi": ("GET", "/v1/ewi", None, 30),
    "ask:forecast": ("POST", "/v1/ask", {"text": "chance of global recession?"}, 20),
    "ask:explain": ("POST", "/v1/ask", {"text": "why is middle east war risk high?"}, 20),
    "ask:whatif": ("POST", "/v1/ask", {"text": "what if we deploy a gulf maritime coalition?"}, 8),
    "ask:policy": ("POST", "/v1/ask", {"text": "best policy portfolio budget 8"}, 5),
}
SLO_P95_MS = {"read:forecasts": 50, "read:ewi": 50, "ask:forecast": 100,
              "ask:explain": 100, "ask:whatif": 500, "ask:policy": 2000}

def main():
    t0 = time.time()
    with TestClient(app) as c:
        startup = time.time() - t0
        print(f"startup: {startup:.1f}s (SLO <30s) {'PASS' if startup < 30 else 'FAIL'}")
        ok = True
        for name, (method, path, body, n) in CASES.items():
            lat = []
            for _ in range(n):
                t = time.time()
                r = c.post(path, json=body) if method == "POST" else c.get(path)
                assert r.status_code == 200, (name, r.status_code)
                lat.append(1000 * (time.time() - t))
            p50, p95 = st.median(lat), sorted(lat)[max(0, int(0.95 * len(lat)) - 1)]
            slo = SLO_P95_MS[name]
            passed = p95 < slo
            ok &= passed
            print(f"{name:16s} n={n:<3d} p50={p50:7.1f}ms  p95={p95:7.1f}ms  "
                  f"SLO<{slo}ms {'PASS' if passed else 'FAIL'}")
        print("BENCHMARK:", "ALL SLOs PASS" if ok else "SLO FAILURES")
        return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
