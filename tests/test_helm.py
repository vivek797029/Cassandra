"""Task 78 — Helm chart guard. Validates the chart structurally (offline stand-in
for helm lint/template) and enforces the contract: per-env values exist and secrets
are REFERENCED, never embedded. Authoritative helm lint/template runs in CI."""
import os, importlib.util

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HELM = os.path.join(ROOT, "deploy", "helm", "argus")

_spec = importlib.util.spec_from_file_location(
    "validate_chart", os.path.join(ROOT, "deploy", "helm", "validate_chart.py"))
vc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vc)


def test_chart_validates_structurally():
    assert vc.main() == 0


def test_per_env_values_present():
    for f in ("values.yaml", "values-dev.yaml", "values-prod.yaml"):
        assert os.path.exists(os.path.join(HELM, f)), f


def test_secrets_referenced_not_embedded():
    # deployment injects an existing Secret by reference (envFrom secretRef)
    dep = open(os.path.join(HELM, "templates", "deployment.yaml")).read()
    assert "secretRef" in dep and ".Values.secret.name" in dep
    # no plaintext secret material anywhere in the chart
    bad = ("BEGIN PRIVATE KEY", "password:", "secretKey:", "aws_secret")
    for root, _, files in os.walk(HELM):
        for fn in files:
            blob = open(os.path.join(root, fn), errors="ignore").read().lower()
            for marker in bad:
                assert marker.lower() not in blob, f"{fn} contains '{marker}'"


def test_prod_enables_auth_and_secret():
    import yaml
    prod = yaml.safe_load(open(os.path.join(HELM, "values-prod.yaml")))
    assert prod["env"]["ARGUS_AUTH_ENABLED"] == "1"
    assert prod["secret"]["name"]                       # prod references a Secret


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
