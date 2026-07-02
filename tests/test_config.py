"""Task 41 — settings module tests. 12-factor: behavior changes only via env."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import Settings, get_settings, reset_settings_cache


@pytest.fixture(autouse=True)
def clean_cache():
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_defaults(monkeypatch):
    for var in ("ARGUS_FAST", "ARGUS_SEED", "ARGUS_DB", "DATABASE_URL",
                "OLLAMA_URL", "ARGUS_CORS_ORIGINS"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert s.fast is True and s.seed == 42
    assert s.db.endswith("copilot.db")
    assert s.backend == "sqlite" and s.database_url is None
    assert s.cors_origin_list == ["*"]
    assert s.theta_cache.endswith("theta_deployed.json")


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("ARGUS_FAST", "0")
    monkeypatch.setenv("ARGUS_SEED", "7")
    monkeypatch.setenv("ARGUS_DB", "/tmp/argus/other.db")
    s = Settings(_env_file=None)
    assert s.fast is False and s.seed == 7 and s.db == "/tmp/argus/other.db"


def test_database_url_alias_switches_backend(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")   # unprefixed alias
    s = Settings(_env_file=None)
    assert s.backend == "postgres"
    assert s.database_url.startswith("postgresql://")


def test_ollama_aliases(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3")
    s = Settings(_env_file=None)
    assert s.ollama_url == "http://localhost:11434" and s.ollama_model == "qwen3"


def test_cors_csv_parsing(monkeypatch):
    monkeypatch.setenv("ARGUS_CORS_ORIGINS", "https://a.internal, https://b.internal")
    s = Settings(_env_file=None)
    assert s.cors_origin_list == ["https://a.internal", "https://b.internal"]


def test_get_settings_cached_and_resettable(monkeypatch):
    monkeypatch.setenv("ARGUS_SEED", "11")
    a = get_settings()
    assert a.seed == 11
    monkeypatch.setenv("ARGUS_SEED", "12")
    assert get_settings().seed == 11          # cached
    reset_settings_cache()
    assert get_settings().seed == 12          # re-read after reset
