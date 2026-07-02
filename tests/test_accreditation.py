"""Task 95 — accreditation evidence pack: every control cites implementation +
evidence artifacts that actually exist, across the expected control families."""
import os, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ACC = os.path.join(ROOT, "docs", "accreditation")


def _controls():
    with open(os.path.join(ACC, "controls.json"), encoding="utf-8") as f:
        return json.load(f)


def test_matrix_covers_families_and_min_controls():
    doc = _controls()
    cs = doc["controls"]
    assert len(cs) >= 15
    families = {c["family"] for c in cs}
    for f in ["Access Control", "System Integrity", "Audit & Accountability",
              "Contingency Planning", "Incident Response", "Configuration Management"]:
        assert f in families, f
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as vf:
        assert doc["version"] == vf.read().strip()


def test_every_cited_artifact_exists():
    for c in _controls()["controls"]:
        for path in c["implementation"] + c["evidence"]:
            assert os.path.exists(os.path.join(ROOT, path)), f"{c['id']} missing {path}"


def test_pack_is_submitted():
    t = open(os.path.join(ACC, "README.md"), encoding="utf-8").read().lower()
    assert "submitted" in t and "submission checklist" in t
    assert os.path.exists(os.path.join(ACC, "controls_matrix.md"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
