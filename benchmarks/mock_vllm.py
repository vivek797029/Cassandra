"""OpenAI-compatible vLLM mock for tests/benchmarks — no GPU required.

`make_mock_vllm()` returns a FastAPI app exposing `/v1/chat/completions` and
`/v1/models` exactly as vLLM's OpenAI server does; `mock_client()` wraps it in an
httpx ASGITransport client so `LLMClient` can talk to it in-process. The last
request body is captured on `app.state.last` for pinned-model assertions.
"""
from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

DEFAULT_MODEL = "Qwen2.5-1.5B-Instruct"
DEFAULT_REPLY = '{"intent": "FORECAST", "keys": ["Brent_gt120_1y"]}'


def make_mock_vllm(model: str = DEFAULT_MODEL, reply: str = DEFAULT_REPLY,
                   replies: list[str] | None = None, fail: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.last = {}
    seq = {"i": 0}

    @app.post("/v1/chat/completions")
    def chat(body: dict, request: Request):
        request.app.state.last = body
        if fail:
            return JSONResponse({"error": {"message": "boom"}}, status_code=500)
        if replies:
            content = replies[min(seq["i"], len(replies) - 1)]
            seq["i"] += 1
        else:
            content = reply
        return {"id": "cmpl-mock", "object": "chat.completion", "model": body.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}]}

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": model, "object": "model"}]}

    return app


def mock_client(app: FastAPI, base: str = "http://vllm") -> TestClient:
    # Starlette TestClient is a sync httpx client that routes to the ASGI app
    # (by path, ignoring host) — usable as LLMClient's injected http_client.
    return TestClient(app, base_url=base)
