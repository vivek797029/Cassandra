"""Task 73 — release consistency. VERSION is the single source of truth and must
equal the running app version, the committed OpenAPI artifact, and have a matching
CHANGELOG entry. Prevents a half-cut release (bumped here, stale there)."""
import os, re, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _version() -> str:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version()), _version()


def test_app_version_matches_version_file():
    os.environ.setdefault("ARGUS_FAST", "1")
    from services.copilot.main import app
    assert app.version == _version()


def test_openapi_artifact_matches_version():
    v = _version()
    with open(os.path.join(ROOT, "docs", "openapi", "openapi.json"), encoding="utf-8") as f:
        assert json.load(f)["info"]["version"] == v
    assert os.path.exists(os.path.join(ROOT, "docs", "openapi", f"openapi-{v}.json")), \
        f"missing pinned artifact openapi-{v}.json"


def test_changelog_has_entry_for_current_version():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        assert f"## [{_version()}]" in f.read()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
