"""Chat-completions provider over plain HTTP.

Talks to any OpenAI-compatible `/chat/completions` endpoint. OpenAI is the first
target, but Azure OpenAI, a local gateway and several other vendors expose the
same shape, so provider independence is real rather than aspirational -- and it
needs no vendor SDK, only `httpx`, which the project already depends on.

The API key comes from the environment. Nothing is hard-coded, and the key is
never logged or returned.

**Failure is never fatal.** Any error -- no key, timeout, bad status, malformed
body -- falls back to the stub and returns `degraded=True`. An LLM outage must
not fail a claims workflow, and must never leave a claim in a state where a
consequential action looks authorised.
"""

from __future__ import annotations

import logging
import os

import httpx

from llm.base import SYSTEM_PROMPT, NarrationRequest, NarrationResult
from llm.stub import StubLLMProvider

logger = logging.getLogger("claims.llm")

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class HttpChatLLMProvider:
    """OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        name: str = "openai",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        temperature: float | None = None,
    ) -> None:
        self.name = name
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = (base_url or os.environ.get("LLM_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or "gpt-4o-mini"
        self._timeout = timeout_seconds or float(
            os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS", "60")
        )
        self._temperature = (
            temperature
            if temperature is not None
            else float(os.environ.get("LLM_TEMPERATURE", "0"))
        )
        self._fallback = StubLLMProvider()

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        if not self._api_key:
            logger.info("No LLM API key configured; using deterministic narration.")
            return self._degraded(request)

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": self._temperature,
                    "max_tokens": max(64, request.max_words * 3),
                    "messages": [
                        {
                            "role": "system",
                            "content": request.system_instruction or SYSTEM_PROMPT,
                        },
                        {"role": "user", "content": self._user_message(request)},
                    ],
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
            if not text:
                raise ValueError("Empty completion")
            return NarrationResult(
                text=text, provider=self.name, model=self.model, degraded=False
            )
        except Exception as exc:  # noqa: BLE001 - narration must never raise
            logger.warning(
                "LLM narration failed (%s); falling back to deterministic narration.",
                exc.__class__.__name__,
            )
            return self._degraded(request)

    def _degraded(self, request: NarrationRequest) -> NarrationResult:
        fallback = self._fallback.narrate(request)
        return NarrationResult(
            text=fallback.text, provider=self.name, model=self.model, degraded=True
        )

    @staticmethod
    def _user_message(request: NarrationRequest) -> str:
        import json

        return (
            f"Purpose: {request.purpose}\n"
            f"Write at most {request.max_words} words.\n\n"
            f"Facts:\n{json.dumps(request.facts, indent=2, default=str)}"
        )
