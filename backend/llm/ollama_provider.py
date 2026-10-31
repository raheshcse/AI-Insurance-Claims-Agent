"""Ollama — a model running on this machine, through the same boundary.

=============================================================================
WHY A LOCAL PROVIDER

Gemini works. It returns HTTP 429: the request reaches Google, authenticates,
and is refused for quota. That is a working integration with no headroom, and
it makes development stop-start in a way that has nothing to do with the code.

A local model removes the quota, the key and the network from the development
loop. It is not a replacement for Gemini -- it is a second option selected by
configuration, and both stay available.

=============================================================================
THIS IS NOT A SECOND ABSTRACTION

It implements `LLMProvider`: one method, `narrate()`, returning a
`NarrationResult`. Everything above it -- the Conversation Agent, the
LangGraph nodes, the VSL gate, the validators -- is unchanged and cannot tell
which provider answered except by reading `provider` on the result.

That is the whole point of the boundary, and it is why adding Ollama needed no
changes to any agent, any graph node, or any governance code.

=============================================================================
NO KEY. DELIBERATELY.

Ollama is a local server. There is nothing to authenticate, so this provider
has no key, reads no key, and must never be given one. `GEMINI_API_KEY` in
particular is Gemini's and stays Gemini's -- a local endpoint that accepted a
cloud credential would be a way to leak one to whatever was listening on
port 11434.

=============================================================================
THE API

Verified against Ollama's own `docs/api.md`:

    POST {base}/api/generate
        model      required
        prompt     the user text
        system     the system instruction
        stream     MUST be false -- see below
        options    {"temperature": ...}
        format     a JSON schema, for structured output

    response: {"response": "<the generated text>", ...timings}

    GET {base}/api/tags   lists the models this server actually has

`stream` defaults to TRUE, and a streaming reply is newline-delimited JSON
objects rather than one document. Forgetting to set it false does not fail
loudly -- it produces a body that will not parse, which this provider would
then report as `response_not_json`. It is set explicitly for that reason.

=============================================================================
FAILURE IS NEVER FATAL, AND NEVER ANONYMOUS

Every failure degrades to deterministic narration and names itself, using the
same `DegradedReason` vocabulary as every other provider. One code is
provider-specific: a 404 from a local server that plainly answered means the
model has not been pulled, not that anything is misconfigured -- so it maps to
`model_not_found`, whose fix is one `ollama pull` away.
"""

from __future__ import annotations

import json
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

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_TIMEOUT_SECONDS = 120.0
"""Two minutes, and not an accident.

On a CPU-only machine an 8B model at 4-bit runs at a few tokens per second, so
a structured extraction of a couple of hundred tokens can take the better part
of a minute. Gemini's 30-second timeout would turn ordinary local inference
into a stream of `network_timeout` reports."""


class OllamaLLMProvider:
    """A model on localhost. Satisfies `LLMProvider`."""

    name = "ollama"

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL
        self._base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._temperature = (
            temperature
            if temperature is not None
            else _float_env("OLLAMA_TEMPERATURE", 0.0)
        )
        self._timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else _float_env("OLLAMA_REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )
        # Injected only by tests, so the request that would go on the wire can
        # be asserted without a running server.
        self._transport = transport
        self._fallback = StubLLMProvider()

    # -- configuration ----------------------------------------------------

    @property
    def configured(self) -> bool:
        """Always True. There is nothing to configure and nothing to get wrong.

        Present because the factory asks every provider this question. For a
        keyed provider it means "a key is present"; here the honest answer is
        that a local server needs no credential, and whether it is RUNNING is a
        different question that only a request can answer."""
        return True

    @property
    def endpoint(self) -> str:
        return f"{self._base_url}/api/generate"

    @property
    def tags_endpoint(self) -> str:
        """Where to ask which models this server actually has."""
        return f"{self._base_url}/api/tags"

    # -- the only method agents may call ----------------------------------

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        try:
            payload = self._post(request)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            # A local server that answered 404 has the endpoint; what it does
            # not have is the model.
            reason = reason_for_status(code, not_found=DegradedReason.MODEL_NOT_FOUND)
            logger.warning(
                "Ollama rejected the request with HTTP %s (%s); falling back to "
                "deterministic narration.",
                code,
                reason,
            )
            return self._degraded(request, reason, http_status=code)
        except httpx.TimeoutException:
            logger.warning(
                "Ollama did not answer within %.0fs; falling back to deterministic "
                "narration. A CPU-only machine may simply need longer -- see "
                "OLLAMA_REQUEST_TIMEOUT_SECONDS.",
                self._timeout,
            )
            return self._degraded(request, DegradedReason.TIMEOUT)
        except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout) as exc:
            logger.warning(
                "Ollama could not be reached at %s (%s); is `ollama serve` "
                "running? Falling back to deterministic narration.",
                self._base_url,
                exc.__class__.__name__,
            )
            return self._degraded(request, DegradedReason.CONNECTION_FAILED)
        except ValueError:
            # A 200 whose body would not parse. The usual cause is `stream`
            # defaulting to true somewhere, which returns NDJSON.
            logger.warning(
                "Ollama returned a body that is not a single JSON document; "
                "falling back to deterministic narration."
            )
            return self._degraded(request, DegradedReason.INVALID_JSON)
        except Exception as exc:  # noqa: BLE001 - narration must never raise
            logger.warning(
                "Ollama narration failed (%s); falling back to deterministic "
                "narration.",
                exc.__class__.__name__,
            )
            return self._degraded(request, DegradedReason.TRANSPORT_ERROR)

        text = str(payload.get("response") or "").strip()
        if not text:
            logger.warning(
                "Ollama returned an empty response; falling back to deterministic "
                "narration."
            )
            return self._degraded(request, DegradedReason.EMPTY_RESPONSE)

        return NarrationResult(
            text=text,
            provider=self.name,
            model=payload.get("model") or self.model,
            degraded=False,
        )

    # -- diagnostics -------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        """Is the server up, and does it have the configured model?

        Returns `(ok, reason)` where `reason` is one of the shared codes, or
        `"ok"`. Used by the CLI diagnostic; it makes no generation request, so
        it is fast and costs no inference.
        """
        try:
            with httpx.Client(transport=self._transport, timeout=5.0) as client:
                response = client.get(self.tags_endpoint)
            response.raise_for_status()
            models = {
                str(item.get("name", "")) for item in (response.json().get("models") or [])
            }
        except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout):
            return False, DegradedReason.CONNECTION_FAILED
        except httpx.TimeoutException:
            return False, DegradedReason.TIMEOUT
        except httpx.HTTPStatusError as exc:
            return False, reason_for_status(exc.response.status_code)
        except Exception:  # noqa: BLE001 - a diagnostic must not raise
            return False, DegradedReason.TRANSPORT_ERROR

        # Ollama reports "qwen3:8b"; a user may configure "qwen3" and mean the
        # same family, so a prefix match counts. Being wrong in the permissive
        # direction costs one clear 404 at request time; being wrong in the
        # strict direction tells someone their working setup is broken.
        if self.model in models or any(m.split(":")[0] == self.model for m in models):
            return True, "ok"
        return False, DegradedReason.MODEL_NOT_FOUND

    # -- internals ---------------------------------------------------------

    def _post(self, request: NarrationRequest) -> dict[str, Any]:
        body = self.build_request_body(request)
        with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
            response = client.post(
                self.endpoint,
                headers={"Content-Type": "application/json"},
                json=body,
            )
        response.raise_for_status()
        return response.json()

    def build_request_body(self, request: NarrationRequest) -> dict[str, Any]:
        """The /api/generate request. Public so a test can assert its shape."""
        body: dict[str, Any] = {
            "model": self.model,
            "system": request.system_instruction or SYSTEM_PROMPT,
            "prompt": _user_message(request),
            # NOT optional. Ollama streams by default, and a streamed body is
            # newline-delimited JSON that will not parse as one document.
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": max(64, request.max_words * 4),
            },
        }

        # Structured output, using the SAME `response_schema` the Gemini
        # provider honours. The conversation layer sets it once and neither
        # provider needs to know about the other.
        if request.response_schema:
            body["format"] = request.response_schema

        return body

    def _degraded(
        self, request: NarrationRequest, reason: str, *, http_status: int | None = None
    ) -> NarrationResult:
        """Deterministic prose, labelled, with the reason and any status.

        `provider` stays `ollama`. Reporting `stub` here would say the system
        chose not to use a model, when what happened is that the model it was
        told to use did not answer."""
        fallback = self._fallback.narrate(request)
        return NarrationResult(
            text=fallback.text,
            provider=self.name,
            model=self.model,
            degraded=True,
            degraded_reason=reason,
            http_status=http_status,
        )


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _user_message(request: NarrationRequest) -> str:
    """The prompt. Identical in shape to the Gemini provider's, on purpose --
    the same facts produce the same prompt whichever model reads it."""
    return (
        f"Purpose: {request.purpose}\n"
        f"Write at most {request.max_words} words.\n\n"
        f"Facts:\n{json.dumps(request.facts, indent=2, default=str)}"
    )
