"""Task 76 — OpenAI-compatible LLM client (vLLM).

A thin client over the OpenAI `/chat/completions` schema that vLLM serves
(`vllm serve <model>`), used by the NLU layer for intent/slot assist only — never
for numbers. The model id is PINNED via settings (and the revision is pinned in
the deploy manifest). `http_client` may be injected (e.g. an ASGITransport client)
so the path is testable and benchmarkable without a GPU.
"""
from __future__ import annotations
import httpx


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 timeout: float = 10.0, max_tokens: int = 64,
                 http_client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")          # expected to end in /v1
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._client = http_client

    @classmethod
    def from_settings(cls, settings, http_client: httpx.Client | None = None) -> "LLMClient":
        return cls(settings.llm_base_url, settings.llm_model, api_key=settings.llm_api_key,
                   timeout=settings.llm_timeout, max_tokens=settings.llm_max_tokens,
                   http_client=http_client)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, path: str, payload: dict):
        url = f"{self.base_url}{path}"
        if self._client is not None:
            return self._client.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        return httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)

    def chat(self, messages: list[dict], *, temperature: float = 0.0,
             max_tokens: int | None = None, response_format: dict | None = None) -> str:
        """Return the assistant message content for a chat completion, or raise LLMError."""
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens or self.max_tokens}
        if response_format:
            payload["response_format"] = response_format
        try:
            r = self._post("/chat/completions", payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as ex:
            raise LLMError(f"{type(ex).__name__}: {ex}")

    def health(self) -> bool:
        """True if the server lists the pinned model at /models."""
        try:
            if self._client is not None:
                r = self._client.get(f"{self.base_url}/models", timeout=self.timeout)
            else:
                r = httpx.get(f"{self.base_url}/models", timeout=self.timeout)
            r.raise_for_status()
            ids = {m.get("id") for m in r.json().get("data", [])}
            return self.model in ids
        except Exception:
            return False
