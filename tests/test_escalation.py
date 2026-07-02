"""Task 97 — escalation routing + game-day. Every alert routes to the right tier
within SLA; the game-day exercise passes."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.ops import escalation as E

OPS = os.path.join(os.path.dirname(__file__), "..", "docs", "ops")


def test_all_alerts_have_a_route():
    cov = E.coverage()
    assert cov["covered"] and cov["unrouted"] == []
    assert cov["n_alerts"] >= 8


def test_severity_routing():
    assert E.route("ArgusHighErrorRate")["action"] == "page"
    assert E.route("ArgusHighErrorRate")["ack_sla_min"] == 15
    assert E.route("ArgusPromptInjectionSpike")["action"] == "notify"
    assert E.route("ArgusEntailmentViolations")["action"] == "ticket"


def test_game_day_passes():
    gd = E.game_day()
    assert gd["passed"] is True and gd["n"] >= 8
    # every paged alert is within the 15-min ack SLA
    assert all(r["ack_sla_min"] <= 15 for r in gd["routes"] if r["action"] == "page")


def test_ops_docs_present():
    for name in ("watch-rota.md", "escalation-policy.md", "game-day.md"):
        assert os.path.exists(os.path.join(OPS, name)), name
    assert "passed" in open(os.path.join(OPS, "game-day.md"), encoding="utf-8").read().lower()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
