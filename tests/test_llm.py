"""Task 76 — OpenAI-compatible vLLM client + NLU assist via vLLM (no GPU; ASGI mock)."""
import os, sys, importlib.util, time, statistics as st
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

import pytest
from services.llm.client import LLMClient, LLMError
from services.copilot import nlu
from services.copilot.config import get_settings, reset_settings_cache

# import the mock by file path (benchmarks isn't a package)
_m = importlib.util.spec_from_file_location(
    "mock_vllm", os.path.join(os.path.dirname(__file__), "..", "benchmarks", "mock_vllm.py"))
mock_vllm = importlib.util.module_from_spec(_m)
_m.loader.exec_module(mock_vllm)

PINNED = "Qwen2.5-1.5B-Instruct"


def _client(app):
    return LLMClient("http://vllm/v1", PINNED, http_client=mock_vllm.mock_client(app))


# --------------------------------------------------------------- client -----
def test_chat_returns_content_and_sends_pinned_model():
    app = mock_vllm.make_mock_vllm(model=PINNED)
    out = _client(app).chat([{"role": "user", "content": "hi"}])
    assert "intent" in out                                  # canned JSON content
    assert app.state.last["model"] == PINNED                # pinned model id sent


def test_health_reports_pinned_model_present():
    app = mock_vllm.make_mock_vllm(model=PINNED)
    assert _client(app).health() is True
    assert LLMClient("http://vllm/v1", "other-model",
                     http_client=mock_vllm.mock_client(app)).health() is False


def test_server_error_raises_llmerror():
    app = mock_vllm.make_mock_vllm(fail=True)
    with pytest.raises(LLMError):
        _client(app).chat([{"role": "user", "content": "hi"}])


# ------------------------------------------------- NLU assist via vLLM -------
@pytest.fixture
def vllm_env(monkeypatch):
    monkeypatch.setenv("ARGUS_LLM_URL", "http://vllm/v1")
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    reset_settings_cache()
    nlu.reset_metrics()
    yield
    reset_settings_cache()


def _route(app, monkeypatch):
    llm = LLMClient.from_settings(get_settings(), http_client=mock_vllm.mock_client(app))
    monkeypatch.setattr(nlu, "_vllm_generate", lambda prompt: llm.chat(
        [{"role": "user", "content": prompt}], response_format={"type": "json_object"}))


def test_unknown_question_resolved_via_vllm(vllm_env, monkeypatch):
    _route(mock_vllm.make_mock_vllm(), monkeypatch)
    p = nlu.parse("tell me about oil markets generally")    # UNKNOWN -> vLLM assist
    assert p["intent"] == "FORECAST" and p["keys"] == ["Brent_gt120_1y"]
    assert nlu.get_metrics()["llm_accepted"] == 1


def test_vllm_assist_json_retry(vllm_env, monkeypatch):
    _route(mock_vllm.make_mock_vllm(
        replies=["not json at all", '{"intent": "EWI", "keys": []}']), monkeypatch)
    p = nlu.parse("freeform unmatched gibberish")
    assert p["intent"] == "EWI"
    m = nlu.get_metrics()
    assert m["llm_json_failures"] == 1 and m["llm_accepted"] == 1


def test_contamination_report_labels_vllm(vllm_env):
    assert nlu.contamination_report()["llm_assist"] == "vllm"


def test_assist_p95_under_slo(vllm_env, monkeypatch):
    _route(mock_vllm.make_mock_vllm(), monkeypatch)
    q = "tell me about oil markets generally"
    nlu.parse(q)
    lat = []
    for _ in range(30):
        t = time.time(); nlu.parse(q); lat.append(1000 * (time.time() - t))
    p95 = sorted(lat)[max(0, int(0.95 * len(lat)) - 1)]
    assert p95 < 300, f"assist p95 {p95:.1f}ms exceeds 300ms"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
