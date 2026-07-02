"""Task 72 — guard the operations runbook so it doesn't rot.

Checks docs/RUNBOOK.md exists and covers the contract that on-call relies on:
the failure-mode table, the drill commands (which are real CI gates), and the
health/degradation surfaces wired in Tasks 68/70/71."""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RUNBOOK = os.path.join(ROOT, "docs", "RUNBOOK.md")


def _text() -> str:
    assert os.path.exists(RUNBOOK), "docs/RUNBOOK.md is missing"
    with open(RUNBOOK, encoding="utf-8") as f:
        return f.read()


def test_runbook_has_core_sections():
    t = _text()
    for section in ["Failure-modes table", "Triage flow", "Incident procedures",
                    "Drills", "Deploy & rollback", "Escalation"]:
        assert section in t, f"runbook missing section: {section}"


def test_runbook_covers_observability_surfaces():
    t = _text()
    for probe in ["/healthz", "/readyz", "/metrics", "/v1/nlu/health", "X-Argus-Degraded"]:
        assert probe in t, f"runbook missing probe: {probe}"


def test_runbook_documents_real_drill_commands():
    t = _text()
    for cmd in ["tests/test_degradation.py", "services.copilot.nlu --gate",
                "tests/redteam", "benchmarks/run_locust.py", "export_openapi.py --check"]:
        assert cmd in t, f"runbook missing drill command: {cmd}"
    assert "Last drill executed" in t          # drill evidence recorded


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
