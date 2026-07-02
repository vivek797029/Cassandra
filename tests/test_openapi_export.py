"""Task 71 — the committed OpenAPI artifact stays in sync with the live app,
and the published contract exposes the expected surface."""
import os, sys, importlib.util
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "export_openapi.py")
_spec = importlib.util.spec_from_file_location("export_openapi", _PATH)
ox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ox)


def test_committed_artifact_in_sync_with_live_schema():
    ok, msg = ox.check()
    assert ok, msg                                  # drift gate as a unit test


def test_serialization_is_deterministic():
    assert ox.canonical(ox.build_spec()) == ox.canonical(ox.build_spec())


def test_contract_exposes_expected_surface():
    spec = ox.build_spec()
    assert spec["openapi"].startswith("3.")
    with open(os.path.join(os.path.dirname(__file__), "..", "VERSION"), encoding="utf-8") as vf:
        assert spec["info"]["version"] == vf.read().strip()
    for path in ["/v1/ask", "/v1/forecasts", "/v1/forecasts/{key}", "/readyz",
                 "/healthz", "/metrics", "/v1/nlu/health", "/v1/counterfactual",
                 "/v1/whoami", "/v1/admin/ping"]:
        assert path in spec["paths"], f"missing path {path}"
    # Task 68 + Task 70 fields must be part of the published contract
    props = spec["components"]["schemas"]["AskResponse"]["properties"]
    assert "degraded" in props and "staleness" in props


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
