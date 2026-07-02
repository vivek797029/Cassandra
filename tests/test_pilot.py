"""Task 86 — pilot onboarding kit exists and covers the required ground."""
import os

PILOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "pilot")


def _read(name):
    p = os.path.join(PILOT, name)
    assert os.path.exists(p), f"missing docs/pilot/{name}"
    return open(p, encoding="utf-8").read()


def test_onboarding_guide_present_and_complete():
    t = _read("README.md")
    for s in ["golden rules", "No naked numbers", "Abstention", "clearance",
              "Pilot scope", "20 analysts"]:
        assert s.lower() in t.lower(), s


def test_consent_form_present():
    t = _read("CONSENT.md")
    for s in ["Informed Consent", "voluntary", "withdraw", "Signature"]:
        assert s.lower() in t.lower(), s


def test_feedback_form_present():
    t = _read("FEEDBACK.md")
    for s in ["manifest_id", "Weekly survey", "Incident reporting", "calibration"]:
        assert s.lower() in t.lower(), s


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
