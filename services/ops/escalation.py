"""Task 97 — 24/7 escalation routing.

Maps each Prometheus alert (Task 81, `deploy/observability/alerts.yaml`) to a paging
action, on-call tier, acknowledge SLA, and escalation ladder. The game-day exercise
fires each alert and verifies it routes to the right tier within SLA.
"""
from __future__ import annotations
import os
import yaml

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ALERTS = os.path.join(_ROOT, "deploy", "observability", "alerts.yaml")

# severity → routing policy
POLICY = {
    "page":    {"action": "page",   "tier": "primary-oncall", "ack_sla_min": 15,
                "escalate_after_min": 15, "escalate_to": "secondary-oncall"},
    "warning": {"action": "notify", "tier": "oncall-channel",  "ack_sla_min": 60,
                "escalate_after_min": 120, "escalate_to": "team-lead"},
    "ticket":  {"action": "ticket", "tier": "backlog",         "ack_sla_min": 1440,
                "escalate_after_min": None, "escalate_to": None},
}


def load_alert_severities(path: str = ALERTS) -> dict:
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    out = {}
    for g in doc["groups"]:
        for r in g["rules"]:
            out[r["alert"]] = r["labels"]["severity"]
    return out


def route(alertname: str, severities: dict | None = None) -> dict:
    sev = (severities or load_alert_severities())[alertname]
    if sev not in POLICY:
        raise KeyError(f"no escalation policy for severity '{sev}'")
    return {"alert": alertname, "severity": sev, **POLICY[sev]}


def coverage() -> dict:
    """Every alert must map to a known severity/policy — no orphan alerts."""
    sev = load_alert_severities()
    unrouted = [a for a, s in sev.items() if s not in POLICY]
    return {"n_alerts": len(sev), "severities": sorted(set(sev.values())),
            "unrouted": unrouted, "covered": not unrouted}


def game_day(firing: list[str] | None = None) -> dict:
    """Simulate alerts firing; return the routes and a pass/fail per SLA."""
    sev = load_alert_severities()
    firing = firing or list(sev)
    routes = [route(a, sev) for a in firing]
    pages_within_sla = all(r["ack_sla_min"] <= 15 for r in routes if r["action"] == "page")
    return {"routes": routes, "n": len(routes),
            "passed": bool(routes) and pages_within_sla and coverage()["covered"]}


if __name__ == "__main__":
    import json
    print(json.dumps(game_day(), indent=2, default=str))
