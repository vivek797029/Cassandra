"""Task 69 — Locust load test: 100 concurrent users, mixed intents.

Two user classes model realistic copilot traffic:
  * CopilotReader (weight 9) — cached/light requests: read endpoints + the
    cached `/v1/ask` intents (forecast / explain / EWI / status). These are
    served from the warm baseline ensemble and carry the SLO.
  * CopilotAnalyst (weight 1) — heavy `/v1/ask` intents (what-if, policy) that
    run live CRN simulations. Reported, but not gated by the cached SLO.

GATE (enforced via the `quitting` event, sets the process exit code):
  * every cached:* endpoint p99 < 1000 ms   (blueprint Phase-1 read SLO headroom)
  * zero request failures
  * the cached path actually received traffic

Run headless against a live API:
  locust -f benchmarks/locustfile.py --headless -u 100 -r 50 -t 20s \
         --host http://127.0.0.1:8000
or via the self-contained harness: python benchmarks/run_locust.py
"""
from __future__ import annotations
import logging
import random

from locust import HttpUser, task, between, events

P99_SLO_MS = 1000          # cached-path p99 SLO
MIN_CACHED_REQUESTS = 50   # the run must actually exercise the cached path

FORECAST_QS = [
    "what is the probability of a global recession?",
    "chance Brent crude rises above $120 this year?",
    "odds of a second Hormuz closure by 2027?",
    "how likely is inflation above 5% in 2027?",
    "probability of a Russia-Ukraine ceasefire by end 2027?",
]
EXPLAIN_QS = [
    "why is Middle East war risk elevated?",
    "explain the reasoning behind the oil spike forecast",
    "what caused the rise in recession risk?",
]
WHATIF_QS = [
    "what if we deploy a Gulf maritime verification coalition?",
    "what if we open an EM bridge-financing window?",
    "what if we stand up a strategic energy buffer package?",
]
POLICY_QS = [
    "best policy portfolio to reduce risk with budget 8",
    "which interventions should we fund with budget 12?",
]
READS = ["/v1/forecasts", "/v1/ewi", "/v1/fans"]


class CopilotReader(HttpUser):
    """Cached / light traffic — carries the p99 SLO."""
    weight = 9
    wait_time = between(0.5, 2.0)      # think time of a concurrent user

    @task(5)
    def read_endpoint(self):
        path = random.choice(READS)
        self.client.get(path, name=f"cached:GET {path}")

    @task(4)
    def ask_forecast(self):
        self.client.post("/v1/ask", json={"text": random.choice(FORECAST_QS)},
                         name="cached:ask:forecast")

    @task(3)
    def ask_explain(self):
        self.client.post("/v1/ask", json={"text": random.choice(EXPLAIN_QS)},
                         name="cached:ask:explain")

    @task(2)
    def ask_ewi(self):
        self.client.post("/v1/ask", json={"text": "what early-warning indicators should we watch?"},
                         name="cached:ask:ewi")

    @task(2)
    def ask_status(self):
        self.client.post("/v1/ask", json={"text": "give me a situation overview"},
                         name="cached:ask:status")


class CopilotAnalyst(HttpUser):
    """Heavy live-simulation traffic — reported, not gated by the cached SLO."""
    weight = 1
    wait_time = between(1.0, 3.0)      # heavier think time for analyst workflows

    @task(2)
    def ask_whatif(self):
        self.client.post("/v1/ask", json={"text": random.choice(WHATIF_QS)},
                         name="heavy:ask:whatif")

    @task(1)
    def ask_policy(self):
        self.client.post("/v1/ask", json={"text": random.choice(POLICY_QS)},
                         name="heavy:ask:policy")


@events.quitting.add_listener
def _enforce_slo(environment, **_):
    st = environment.stats
    problems: list[str] = []

    if st.total.num_failures > 0:
        problems.append(f"{st.total.num_failures} request failure(s)")

    cached_reqs = 0
    cached_entries = [e for e in st.entries.values() if e.name.startswith("cached:")]
    logging.info("---- cached-path latency (SLO p99 < %d ms) ----", P99_SLO_MS)
    for e in sorted(cached_entries, key=lambda x: x.name):
        cached_reqs += e.num_requests
        p99 = e.get_response_time_percentile(0.99)
        p50 = e.get_response_time_percentile(0.50)
        logging.info("  %-26s n=%-5d p50=%5dms p99=%5dms %s",
                     e.name, e.num_requests, p50, p99,
                     "OK" if p99 < P99_SLO_MS else "FAIL")
        if e.num_requests and p99 >= P99_SLO_MS:
            problems.append(f"{e.name} p99={p99}ms ≥ {P99_SLO_MS}ms")

    # visibility into the heavy path (not gated here)
    for e in sorted((e for e in st.entries.values() if e.name.startswith("heavy:")),
                    key=lambda x: x.name):
        logging.info("  %-26s n=%-5d p50=%5dms p99=%5dms (heavy, ungated)",
                     e.name, e.num_requests, e.get_response_time_percentile(0.50),
                     e.get_response_time_percentile(0.99))

    if cached_reqs < MIN_CACHED_REQUESTS:
        problems.append(f"cached path under-exercised: {cached_reqs} < {MIN_CACHED_REQUESTS}")

    if problems:
        logging.error("LOAD GATE FAIL — %s", "; ".join(problems))
        environment.process_exit_code = 1
    else:
        logging.info("LOAD GATE PASS — cached p99 < %d ms across %d requests, 0 failures",
                     P99_SLO_MS, cached_reqs)
        environment.process_exit_code = 0
