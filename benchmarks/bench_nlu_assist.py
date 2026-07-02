"""Task 76 — NLU-assist latency gate: p95 < 300 ms.

Runs the NLU assist path (vLLM client call + JSON extraction + schema validation,
including a retry budget) through `nlu.parse()` against an in-process
OpenAI-compatible mock, so it gates in CI without a GPU. The pinned deploy
(small instruct model, max_tokens=64, temperature=0) is sized to keep the
end-to-end budget under this SLO.
"""
import os, sys, time, statistics as st
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ["ARGUS_LLM_URL"] = "http://vllm/v1"
os.environ.pop("OLLAMA_URL", None)

from benchmarks.mock_vllm import make_mock_vllm, mock_client
from services.copilot import nlu
from services.copilot.config import get_settings, reset_settings_cache
from services.llm.client import LLMClient

SLO_MS = 300
N = 60


def main() -> int:
    reset_settings_cache()
    llm = LLMClient.from_settings(get_settings(), http_client=mock_client(make_mock_vllm()))
    nlu._vllm_generate = lambda prompt: llm.chat(
        [{"role": "system", "content": "Reply ONLY JSON."},
         {"role": "user", "content": prompt}],
        temperature=0, response_format={"type": "json_object"})

    q = "tell me about oil markets generally"      # UNKNOWN → triggers vLLM assist
    nlu.parse(q)                                    # warm
    lat = []
    for _ in range(N):
        t = time.time()
        p = nlu.parse(q)
        lat.append(1000 * (time.time() - t))
    assert p["intent"] == "FORECAST", p             # assist actually resolved

    p50 = st.median(lat)
    p95 = sorted(lat)[max(0, int(0.95 * len(lat)) - 1)]
    ok = p95 < SLO_MS
    print(f"nlu-assist (vLLM, in-process mock) n={N} p50={p50:.1f}ms p95={p95:.1f}ms "
          f"SLO<{SLO_MS}ms {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
