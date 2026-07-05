"""Task 79 — Prometheus telemetry.

RED metrics (Rate / Errors / Duration) for every HTTP request plus engine, NLU,
and entailment gauges, exposed in Prometheus text exposition at /metrics. A private
CollectorRegistry keeps the output deterministic and test-friendly. Gauges are
refreshed on scrape from the live subsystems; the request metrics are driven by
the middleware in main.py.
"""
from __future__ import annotations

from prometheus_client import (Counter, Histogram, Gauge, CollectorRegistry,
                               generate_latest, CONTENT_TYPE_LATEST)

REGISTRY = CollectorRegistry()

# -- RED ---------------------------------------------------------------------
REQUESTS = Counter("argus_requests_total", "HTTP requests",
                   ["method", "path", "status"], registry=REGISTRY)
ERRORS = Counter("argus_request_errors_total", "HTTP 5xx responses",
                 ["method", "path"], registry=REGISTRY)
DURATION = Histogram("argus_request_duration_seconds", "HTTP request duration (s)",
                     ["method", "path"], registry=REGISTRY,
                     buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))

# -- engine / availability gauges --------------------------------------------
G_UP = Gauge("argus_engine_up", "1 if the live engine is warm, 0 if degraded", registry=REGISTRY)
G_DEGRADED = Gauge("argus_degraded", "1 if serving the cached snapshot", registry=REGISTRY)
G_UPTIME = Gauge("argus_uptime_seconds", "process uptime in seconds", registry=REGISTRY)
G_PATHS = Gauge("argus_engine_paths_cached", "cached baseline ensemble path count", registry=REGISTRY)

# -- subsystem snapshot gauges -----------------------------------------------
G_NLU_PARSES = Gauge("argus_nlu_parses", "NLU parses", registry=REGISTRY)
G_NLU_INJECTIONS = Gauge("argus_nlu_injection_detections", "NLU injection detections", registry=REGISTRY)
G_NLU_LLM_CALLS = Gauge("argus_nlu_llm_calls", "NLU LLM-assist calls", registry=REGISTRY)
G_ENT_CHECKED = Gauge("argus_entailment_checked", "sentences checked by the entailment gate", registry=REGISTRY)
G_ENT_VIOLATIONS = Gauge("argus_entailment_violations", "entailment violations found", registry=REGISTRY)
G_ANSWERS = Gauge("argus_answers_total", "assistant answers logged", registry=REGISTRY)


def record_request(method: str, path: str, status: int, dur_seconds: float) -> None:
    REQUESTS.labels(method, path, str(status)).inc()
    if status >= 500:
        ERRORS.labels(method, path).inc()
    DURATION.labels(method, path).observe(dur_seconds)


def _refresh_gauges(uptime: float) -> None:
    G_UPTIME.set(uptime)
    # engine availability without crashing on a degraded engine
    try:
        from services.copilot.engines import get_engines
        e = get_engines()
        G_UP.set(1)
        G_DEGRADED.set(0)
        try:
            G_PATHS.set(int(e.base_sim["N"]))
        except Exception:
            pass
    except Exception:
        G_UP.set(0)
        G_DEGRADED.set(1)
    try:
        from services.copilot import nlu
        from services.llm import entail
        nm = nlu.get_metrics()
        G_NLU_PARSES.set(nm.get("parses", 0))
        G_NLU_INJECTIONS.set(nm.get("injection_detections", 0))
        G_NLU_LLM_CALLS.set(nm.get("llm_calls", 0))
        em = entail.get_metrics()
        G_ENT_CHECKED.set(em.get("checked", 0))
        G_ENT_VIOLATIONS.set(em.get("violations", 0))
    except Exception:
        pass
    try:
        from services.copilot.store import get_store
        G_ANSWERS.set(get_store().answers_stats().get("answers_total", 0))
    except Exception:
        pass


def render(uptime: float) -> tuple[bytes, str]:
    _refresh_gauges(uptime)
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
