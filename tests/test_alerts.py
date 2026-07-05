"""Task 81 — alert rules. Validates structure, proves the promtool unit tests are
consistent with the rule definitions (so CI's `promtool test rules` will match),
cross-checks every referenced metric against the live telemetry exposition, and
drives a real synthetic breach through the registry to show the signals move."""
import os, re, sys, yaml
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

from services.copilot import telemetry

OBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "observability")
ALERTS = os.path.join(OBS, "alerts.yaml")
ALERTS_TEST = os.path.join(OBS, "alerts_test.yaml")


def _rules() -> dict:
    doc = yaml.safe_load(open(ALERTS))
    out = {}
    for g in doc["groups"]:
        for r in g["rules"]:
            out[r["alert"]] = r
    return out


def test_every_rule_well_formed():
    rules = _rules()
    assert rules, "no alert rules"
    for name, r in rules.items():
        assert r["expr"].strip(), f"{name} has empty expr"
        assert r["labels"]["severity"] in ("page", "warning", "ticket"), name
        assert r["annotations"].get("summary"), f"{name} missing summary"


def test_unit_tests_consistent_with_rules():
    """Each promtool exp_alert carries its rule's static labels and exact
    annotations. Expected labels may include MORE than the rule's static set:
    a fired alert inherits the matched series' labels too (e.g. `job` from
    `up{job=...} == 0` — a filter, not an aggregation), so the rule's labels
    must be a subset of exp_labels, not equal to them."""
    rules = _rules()
    doc = yaml.safe_load(open(ALERTS_TEST))
    seen = set()
    for t in doc["tests"]:
        for art in t["alert_rule_test"]:
            name = art["alertname"]
            assert name in rules, f"test references unknown alert {name}"
            for exp in art.get("exp_alerts", []):
                seen.add(name)
                labels = {k: v for k, v in exp["exp_labels"].items() if k != "alertname"}
                assert exp["exp_labels"].get("alertname") == name
                assert rules[name]["labels"].items() <= labels.items(), f"{name} label mismatch"
                assert exp["exp_annotations"] == rules[name]["annotations"], f"{name} annotation mismatch"
    # the breaching alerts are all exercised by the unit tests
    assert {"ArgusHighErrorRate", "ArgusHighLatencyP99", "ArgusEngineDown",
            "ArgusDegraded", "ArgusTargetMissing"} <= seen


def test_referenced_metrics_exist_in_telemetry():
    telemetry.record_request("GET", "/x", 200, 0.01)      # ensure histogram emits buckets
    text = telemetry.render(uptime=1.0)[0].decode()
    names = set(re.findall(r"^#\s+TYPE\s+(\S+)", text, re.M)) | set(re.findall(r"^(argus_\w+)", text, re.M))
    referenced = set(re.findall(r"argus_[a-z0-9_]+", open(ALERTS).read()))
    missing = {m for m in referenced if m not in names}
    assert not missing, f"alerts reference metrics not exposed: {missing}"


def test_synthetic_breach_moves_the_signals():
    """Drive a real breach state and confirm the data the alerts watch reflects it."""
    for _ in range(80):
        telemetry.record_request("POST", "/v1/ask", 200, 0.02)
    for _ in range(20):
        telemetry.record_request("POST", "/v1/ask", 500, 2.5)   # 20% errors, slow
    text = telemetry.render(uptime=1.0)[0].decode()
    # error counter present and non-trivial
    errs = [float(v) for v in re.findall(r'argus_request_errors_total\{[^}]*\}\s+([0-9.e+]+)', text)]
    assert errs and max(errs) >= 20
    # latency observations landed in a >1s bucket (le="+Inf" count exceeds le="1" count)
    def _bucket(le):
        m = re.search(r'argus_request_duration_seconds_bucket\{[^}]*le="%s"[^}]*\}\s+([0-9.e+]+)'
                      % re.escape(le), text)
        return float(m.group(1)) if m else 0.0
    assert _bucket("+Inf") > _bucket("1"), "no observations above the 1s SLO bucket"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
