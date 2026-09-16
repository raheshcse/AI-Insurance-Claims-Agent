"""Provider selection.

`LLM_PROVIDER` chooses. The default is deliberately `stub`: a POC that only
works with a paid API key is a POC nobody can run.

    stub                  deterministic, offline, no key           (default)
    gemini                Google Gemini, Interactions API          GEMINI_API_KEY
    openai | azure-openai | openai-compatible | http
                          any OpenAI-compatible /chat/completions  OPENAI_API_KEY

An unknown value falls back to the stub **with a warning**, never silently: a
typo in `LLM_PROVIDER` must not look like a working configuration.

Selecting a provider is not the same as reaching one. Every provider here
degrades to deterministic narration when its key is missing or its endpoint is
unreachable, and reports `degraded=True` when it does — so "configured" and
"actually answering" stay distinguishable in the analysis result.
"""

from __future__ import annotations

import logging
import os

from bootstrap import load_project_env
from llm.base import LLMProvider
from llm.gemini_provider import GeminiLLMProvider
from llm.http_provider import HttpChatLLMProvider
from llm.stub import StubLLMProvider

logger = logging.getLogger("claims.llm")

_GEMINI = {"gemini", "google", "google-gemini"}
_HTTP_COMPATIBLE = {"openai", "azure-openai", "openai-compatible", "http"}


def get_llm_provider(name: str | None = None) -> LLMProvider:
    # Read `.env` before reading the environment. Without this, a correctly
    # configured `.env` is invisible and every caller silently gets the stub --
    # the exact bug this line fixes. Idempotent, so calling it here is cheap.
    load_project_env()

    provider_name = (name or os.environ.get("LLM_PROVIDER") or "stub").strip().lower()

    if provider_name in _GEMINI:
        provider = GeminiLLMProvider()
        if not provider.configured:
            # Selected but unusable. Said out loud at startup rather than
            # discovered later from prose that quietly came from the fallback.
            logger.warning(
                "LLM_PROVIDER=%s selected but GEMINI_API_KEY is not set; narration "
                "will fall back to deterministic text and report degraded=True.",
                provider_name,
            )
        return provider

    if provider_name in _HTTP_COMPATIBLE:
        return HttpChatLLMProvider(name=provider_name)

    if provider_name != "stub":
        logger.warning(
            "Unknown LLM_PROVIDER %r; using deterministic narration instead.",
            provider_name,
        )
    return StubLLMProvider()
