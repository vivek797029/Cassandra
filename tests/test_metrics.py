"""Task 79 — Prometheus metrics: /metrics exposes RED + engine/NLU/entailment
gauges in text exposition; the JSON summary stays at /metrics.json; the Grafana
dashboard is valid and references the metrics."""
import os, re, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/metrics_test.db")

from fastapi.testclient import TestClient
from services.copilot.main import app

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_metrics_is_prometheus_exposition():
    c = TestClient(app)
    c.get("/healthz")                                   # generate one request sample
    r = c.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    for name in ("argus_requests_total", "argus_request_duration_seconds_bucket",
                 "argus_engine_up", "argus_uptime_seconds", "argus_nlu_parses",
                 "argus_entailment_checked"):
        assert name in body, f"missing metric {name}"
    # HELP/TYPE metadata present (valid exposition)
    assert "# TYPE argus_requests_total counter" in body


def test_request_counter_increments():
    c = TestClient(app)
    c.get("/healthz")
    body = c.get("/metrics").text
    samples = [float(m) for m in re.findall(r'argus_requests_total\{[^}]*\}\s+([0-9.e+]+)', body)]
    assert samples and max(samples) >= 1


def test_metrics_json_backcompat():
    c = TestClient(app)
    m = c.get("/metrics.json").json()
    assert {"answers_total", "uptime_s", "backend", "nlu", "entailment"} <= set(m)


def test_grafana_dashboard_valid():
    with open(os.path.join(ROOT, "deploy", "observability", "grafana-argus.json")) as f:
        dash = json.load(f)
    assert dash["title"] and len(dash["panels"]) >= 5
    exprs = " ".join(t["expr"] for p in dash["panels"] for t in p.get("targets", []))
    assert "argus_requests_total" in exprs and "histogram_quantile" in exprs


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
