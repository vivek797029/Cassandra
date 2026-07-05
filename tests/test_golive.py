"""Task 100 — production go-live gate: version consistent across the board (VERSION
file is the single source of truth), the 3.0.0 go-live evidence trail intact, the
checklist signed, and the 100-task build plan complete."""
import os, sys, json, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def test_version_consistent_everywhere():
    """The version is asserted by *consistency*, not by literal: VERSION drives the
    API, the canonical OpenAPI artifact, a versioned artifact copy, and a CHANGELOG
    entry. Releases bump VERSION + artifacts + CHANGELOG together or this fails."""
    v = _read("VERSION").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v), v
    from services.copilot.main import app
    assert app.version == v
    spec = json.loads(_read("docs", "openapi", "openapi.json"))
    assert spec["info"]["version"] == v
    assert os.path.exists(os.path.join(ROOT, "docs", "openapi", f"openapi-{v}.json"))
    assert f"## [{v}]" in _read("CHANGELOG.md")


def test_golive_evidence_trail_intact():
    """3.0.0 go-live anchors (Task 100) are historical evidence — they must keep
    existing regardless of the current version."""
    assert "## [3.0.0]" in _read("CHANGELOG.md")
    assert os.path.exists(os.path.join(ROOT, "docs", "RELEASE_v3.0.0.md"))
    assert os.path.exists(os.path.join(ROOT, "docs", "openapi", "openapi-3.0.0.json"))


def test_go_live_gate_signed():
    t = _read("docs", "go-live", "go-live-checklist.md").lower()
    assert "go-live gate: signed" in t
    assert "cutover" in t and "hypercare" in t
    assert "**decision:** go" in t


def test_build_plan_complete():
    import re
    plan = _read("docs", "BUILD_PLAN.md")
    assert "100. ✅" in plan
    # no numbered task in the 100-task list remains open (◻ only appears in prose legend)
    assert not re.search(r"^\s*\d+\.\s*◻", plan, re.M)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
