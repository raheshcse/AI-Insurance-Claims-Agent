"""Google Gemini, through the same `LLMProvider` boundary as everything else.

=============================================================================
WHY THIS IS A SEPARATE PROVIDER AND NOT A `LLM_BASE_URL` ON THE HTTP ONE

`HttpChatLLMProvider` speaks OpenAI chat-completions. Gemini's *current* API is
the **Interactions API**, and it is not that shape in any respect:

    |               | OpenAI chat-completions        | Gemini Interactions           |
    | URL           | POST /v1/chat/completions      | POST /v1beta/interactions     |
    | Auth          | Authorization: Bearer <key>    | x-goog-api-key: <key>         |
    | Prompt        | messages: [{role, content}]    | input + system_instruction    |
    | Tuning        | temperature, max_tokens        | generation_config{...}        |
    | Text is at    | choices[0].message.content     | steps[].content[].text        |

Four differences, each of which would become an `if self.name == "gemini"`
branch inside a class whose whole purpose is to speak one protocol. That is the
thing the provider abstraction exists to prevent, so Gemini gets its own
provider and `HttpChatLLMProvider` is left untouched.

**There is a second route, and it needs no code at all.** Gemini publishes an
OpenAI-compatibility endpoint, so the existing HTTP provider already works
against it with configuration alone:

    LLM_PROVIDER=openai-compatible
    LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
    OPENAI_API_KEY=<your Gemini key>
    LLM_MODEL=gemini-3.8-flash

That is a legitimate option and is documented rather than hidden. It is not the
default here for three reasons: Google labels the compatibility layer beta and
says unsupported parameters are **silently ignored** (this codebase avoids
silent anything); Google's own guidance is to use the native API unless you are
already committed to OpenAI client libraries; and putting a Gemini key in a
variable named `OPENAI_API_KEY` is an incident waiting to happen.

**A note on `generateContent`.** The older `:generateContent` endpoint still
works but Google now documents it as legacy, superseded by the Interactions API.
This provider targets the current one.
=============================================================================

WHAT THIS PROVIDER IS ALLOWED TO DO

Exactly what every other provider is allowed to do: return prose about facts the
agent has already determined. It implements `narrate()` and nothing else,
because `narrate()` is the only method the `LLMProvider` protocol exposes.

Gemini cannot reach a claim decision from here. It never sees the routing rules,
never sees the governance candidate, and its output lands in one field --
`AgentResult.narrative` -- which no rule, gate or router reads. That is a
property of the call graph, not a policy: `backend/routing/` and `governance/`
do not import this module or any LLM module, and a test asserts it.

FAILURE IS NEVER FATAL

No key, DNS failure, timeout, 4xx, 5xx, malformed body, empty completion, a
response blocked by safety filtering, a `failed` status -- every one of them
falls back to the deterministic stub and returns `degraded=True`. An LLM outage
must not fail a claims workflow, and must never leave a claim in a state where a
consequential action looks authorised.

THE KEY

Read from `GEMINI_API_KEY`. Never hard-coded, never logged, never returned in a
`NarrationResult`, and never included in an error message -- exceptions are
reported by class name only, which is also what the HTTP provider does.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from llm.base import (
    SYSTEM_PROMPT,
    DegradedReason,
    NarrationRequest,
    NarrationResult,
    reason_for_status,
)
from llm.stub import StubLLMProvider

logger = logging.getLogger("claims.llm")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.8-flash"
API_KEY_ENV = "GEMINI_API_KEY"

_USABLE_STATUSES = {"completed", "incomplete", None}
"""`incomplete` means the model hit the token limit. The text it did produce is
still a usable narration, so it is accepted rather than discarded -- but only
because narration is decorative. Nothing downstream reads it."""


class GeminiLLMProvider:
    """Gemini via the Interactions API. Satisfies `LLMProvider`."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        max_output_tokens: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
        self.model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self._base_url = (
            base_url or os.environ.get("GEMINI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._temperature = (
            temperature
            if temperature is not None
            else _float_env("GEMINI_TEMPERATURE", 0.0)
        )
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else _float_env("GEMINI_REQUEST_TIMEOUT_SECONDS", 30.0)
        )
        self._max_output_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else int(_float_env("GEMINI_MAX_OUTPUT_TOKENS", 400))
        )
        # Injected only by tests, so the request that would go on the wire can be
        # asserted without a network call or a live key.
        self._transport = transport
        self._fallback = StubLLMProvider()

    @property
    def configured(self) -> bool:
        """True when a key is present. Does not validate it -- only the API can."""
        return bool(self._api_key)

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/interactions"

    # -- the only method agents may call ----------------------------------

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        if not self._api_key:
            logger.info(
                "No %s configured; using deterministic narration instead.", API_KEY_ENV
            )
            return self._degraded(request, DegradedReason.NOT_CONFIGURED)

        try:
            payload = self._post(request)
        except httpx.HTTPStatusError as exc:
            # Google answered and said no. The STATUS is the diagnosis, and a
            # status code is not a credential -- so it is reported, while the
            # response body (which can quote the request back) never is.
            code = exc.response.status_code
            reason = reason_for_status(code)
            logger.warning(
                "Gemini rejected the request with HTTP %s (%s); falling back to "
                "deterministic narration.",
                code,
                reason,
            )
            return self._degraded(request, reason, http_status=code)
        except httpx.TimeoutException:
            logger.warning(
                "Gemini did not answer within %.0fs; falling back to deterministic "
                "narration.",
                self._timeout,
            )
            return self._degraded(request, DegradedReason.TIMEOUT)
        except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout) as exc:
            logger.warning(
                "Gemini could not be reached (%s); falling back to deterministic "
                "narration.",
                exc.__class__.__name__,
            )
            return self._degraded(request, DegradedReason.CONNECTION_FAILED)
        except ValueError:
            # A 2xx whose body would not parse -- typically a proxy or captive
            # portal answering instead of the API.
            logger.warning(
                "Gemini returned a non-JSON body; falling back to deterministic "
                "narration."
            )
            return self._degraded(request, DegradedReason.INVALID_JSON)
        except Exception as exc:  # noqa: BLE001 - narration must never raise
            # The genuine catch-all, and it stays LAST. Class name only: an
            # exception's string form can carry a URL, and a URL is one careless
            # refactor away from carrying a key.
            logger.warning(
                "Gemini narration failed (%s); falling back to deterministic narration.",
                exc.__class__.__name__,
            )
            return self._degraded(request, DegradedReason.TRANSPORT_ERROR)

        status = payload.get("status")
        if status not in _USABLE_STATUSES:
            logger.warning(
                "Gemini returned status %r; falling back to deterministic narration.",
                status,
            )
            return self._degraded(request, DegradedReason.UNUSABLE_STATUS)

        text = _extract_text(payload)
        if not text:
            # A safety-filtered or empty response arrives as a 200 with no text.
            # Treating that as success would put an empty narrative in the report.
            logger.warning(
                "Gemini returned no text (status=%r); falling back to deterministic "
                "narration.",
                status,
            )
            return self._degraded(request, DegradedReason.EMPTY_RESPONSE)

        return NarrationResult(
            text=text,
            provider=self.name,
            model=payload.get("model") or self.model,
            degraded=False,
        )

    # -- internals ---------------------------------------------------------

    def _post(self, request: NarrationRequest) -> dict[str, Any]:
        body = self.build_request_body(request)
        with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
            response = client.post(
                self.endpoint,
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=body,
            )
        response.raise_for_status()
        return response.json()

    def build_request_body(self, request: NarrationRequest) -> dict[str, Any]:
        """The Interactions API request. Public so a test can assert its shape.

        Verified against Google's own reference for POST /v1beta/interactions:
        `model`, `input` (a plain string is accepted), `system_instruction`,
        `generation_config`, and `response_format` for structured output.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "system_instruction": request.system_instruction or SYSTEM_PROMPT,
            "input": _user_message(request),
            "generation_config": {
                "temperature": self._temperature,
                "max_output_tokens": self._max_output_tokens,
            },
        }

        # Structured output, when the caller wants JSON rather than prose.
        # Asking for it beats scraping it back out of a code fence afterwards.
        if request.response_schema:
            body["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": request.response_schema,
            }

        return body

    def _degraded(
        self, request: NarrationRequest, reason: str, *, http_status: int | None = None
    ) -> NarrationResult:
        """Deterministic prose, labelled as such, WITH the reason it happened.

        `degraded=True` is what reaches the report as `narrative_source:
        "gemini (degraded)"`, so a reader can tell the difference between prose
        Gemini wrote and prose the fallback composed. Silently substituting one
        for the other would be the dishonest option.

        Note what this does NOT do: it does not change `provider` to `"stub"`.
        The configured provider stays `gemini` and the failure is reported as a
        reason code, because "everything says stub" hides which layer broke.
        """
        fallback = self._fallback.narrate(request)
        return NarrationResult(
            text=fallback.text,
            provider=self.name,
            model=self.model,
            degraded=True,
            degraded_reason=reason,
            http_status=http_status,
        )


# ---------------------------------------------------------------------------
# Helpers -- module level so tests can exercise them directly.
# ---------------------------------------------------------------------------


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _user_message(request: NarrationRequest) -> str:
    """The prompt. Facts in, prose out -- and the facts are already decided."""
    import json

    return (
        f"Purpose: {request.purpose}\n"
        f"Write at most {request.max_words} words.\n\n"
        f"Facts:\n{json.dumps(request.facts, indent=2, default=str)}"
    )


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the generated text out of an Interactions response.

    Two routes, because the surface offers both: `output_text` when present (the
    convenience field), otherwise walk `steps[].content[]` for text blocks. A
    response carrying tool calls and no text yields "" and is treated as a
    failure by the caller -- this POC sends no tools, so that would mean
    something unexpected happened.
    """
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for step in payload.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("type") not in {"model_output", None}:
            continue
        for block in step.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())

    return " ".join(chunks).strip()
