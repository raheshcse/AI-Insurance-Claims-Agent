"""The LLM boundary.

Two rules shape this module, both from the source documents:

1. **Provider independence.** Business logic depends on `LLMProvider`, never on
   a vendor SDK. Swapping provider is a configuration change.

2. **The LLM is not the business authority.** In Phase 2 the model contributes
   *narrative* -- a plain-language summary, an explanation of why something
   matters. Every value that a decision could turn on (status, band, flag,
   confidence) is derived by rule from the Phase 0 decision table, in the agent,
   not by the model. So an unavailable, slow or wrong model degrades the prose
   and nothing else.

That division is why `narrate()` is the only method agents call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class NarrationRequest:
    """A request for explanatory prose about facts the agent already has."""

    purpose: str
    """What the narration is for, e.g. 'claim summary for a claims employee'."""

    facts: dict
    """Structured facts the model may describe. It must not invent beyond these."""

    max_words: int = 90

    system_instruction: str | None = None
    """Override the default system prompt for this one request.

    Added in Phase 5 for the conversational assistant, which needs the model to
    read a customer's sentence and propose structured values rather than write
    prose about facts already decided. Deliberately a FIELD on the request and
    NOT a second method on the provider: `narrate()` stays the only thing an
    agent can call, so there is still nowhere to put "model, decide this".

    That matters more than it looks. The model's structured proposal is text
    like any other narration -- the application parses it, validates every value
    deterministically in `conversation/fields.py`, and an Invariant checks the
    result before it is used. A model that returns nonsense here produces a
    rejected proposal, never a claim value.

    Whatever is set here, a provider still applies its own refusal rules; this
    replaces the task instruction, not the safety of the boundary."""

    response_schema: dict | None = None
    """Ask the provider for JSON matching this schema, rather than prose.

    Added because the conversational assistant asks the model for a structured
    proposal and then had to SCRAPE it out of whatever came back -- a model that
    wrapped its answer in a code fence, or prefixed "Here is the JSON:", was a
    model whose answer got thrown away. The Interactions API supports
    `response_format`, so asking properly is both more reliable and less code.

    Providers that cannot honour it ignore it and return prose; the caller's
    parser still has to cope, because a schema is a request rather than a
    guarantee. It changes the odds, not the contract."""


@dataclass(frozen=True)
class NarrationResult:
    text: str
    provider: str
    model: str | None = None
    degraded: bool = False
    """True when the provider could not be reached and a fallback was used."""

    http_status: int | None = None
    """The HTTP status Google returned, when it returned one.

    A status code is not a credential and is the single most useful fact about
    a failed integration. `None` means the request never got a response."""

    degraded_reason: str | None = None
    """A short, credential-free explanation of WHY the provider degraded.

    A degraded result that cannot say why is the failure mode this field exists
    to prevent: "provider: stub" with no reason sent a whole afternoon looking
    for a bug in the wrong layer. The value is a fixed code from
    `DegradedReason` -- never an exception's string form, which can carry a URL,
    and a URL is one careless refactor away from carrying a key.
    """


class DegradedReason:
    """The fixed set of reasons a provider may report. Deliberately not an Enum:
    these are published verbatim in the API response, and a bare string keeps
    that contract obvious at the call site.

    Each value is safe to display to a staff user and to write to a log. None of
    them is derived from a response body, a URL or an exception message.
    """

    NOT_CONFIGURED = "api_key_not_configured"
    """`GEMINI_API_KEY` is empty or unset. Nothing was sent."""

    # -- the request never reached Google, or never came back ----------------

    TIMEOUT = "network_timeout"
    """No response inside `GEMINI_REQUEST_TIMEOUT_SECONDS`."""

    CONNECTION_FAILED = "connection_failed"
    """DNS, TLS, proxy or routing. The request did not reach the API."""

    TRANSPORT_ERROR = "transport_error"
    """Something else went wrong in transport. The catch-all, and deliberately
    the LAST resort rather than the first: see the note below."""

    # -- Google answered, and said no ----------------------------------------

    BAD_REQUEST = "request_rejected_400"
    """The API understood the request and refused it. Almost always a malformed
    body or an unsupported field."""

    AUTH_REJECTED = "auth_rejected_401_403"
    """The key is missing, wrong, revoked, restricted to other referrers/IPs, or
    the API is not enabled for its project. A CONFIGURATION problem, not a
    network one."""

    NOT_FOUND = "endpoint_or_model_not_found_404"
    """The endpoint path or the model name does not exist. `GEMINI_MODEL` and
    `GEMINI_BASE_URL` are the two things to check."""

    RATE_LIMITED = "rate_limited_429"
    """Quota or rate limit. The integration is correct; there is no headroom."""

    PROVIDER_ERROR = "provider_server_error_5xx"
    """Google's side. Nothing in this project is wrong."""

    INVALID_JSON = "response_not_json"
    """A 2xx whose body would not parse. Usually a proxy or captive portal
    answering instead of the API."""

    # WHY THESE ARE SEPARATE
    #
    # They used to be one value. Every failure -- a wrong key, a wrong model, a
    # quota wall, a DNS failure, a corporate proxy -- came back as
    # `transport_error`, so the only honest thing anyone could say about a
    # broken integration was "it did not work". Diagnosing it meant reading the
    # server log for an exception class name, which is not a thing a person
    # should have to do to learn that their API key is wrong.
    #
    # Each value above maps to one action. None of them carries a credential:
    # an HTTP status is not a secret, and the response body -- which can quote
    # the request -- is never included.

    MODEL_NOT_FOUND = "model_not_found"
    """The server answered but does not have the model.

    Distinct from `endpoint_or_model_not_found_404` because for a LOCAL server
    the two are not the same problem at all: the server is plainly there, and
    the fix is `ollama pull <model>` rather than anything about configuration."""

    UNUSABLE_STATUS = "unusable_interaction_status"
    """The Interactions API answered, but with a status that carries no answer
    (`failed`, `requires_action`, `in_progress`)."""

    EMPTY_RESPONSE = "empty_response_text"
    """A 200 with no text in it -- typically a safety filter."""


def reason_for_status(code: int, *, not_found: str | None = None) -> str:
    """Turn an HTTP status into one of the fixed, safe reason codes.

    Shared by every HTTP-speaking provider so a 401 means the same thing
    whichever one returned it. `not_found` lets a provider say what a 404
    actually means for IT: for a hosted API it is "wrong endpoint or model";
    for a local server that plainly answered, it is "you have not pulled the
    model", which is a different sentence and a different fix.
    """
    if code in (401, 403):
        return DegradedReason.AUTH_REJECTED
    if code == 404:
        return not_found or DegradedReason.NOT_FOUND
    if code == 429:
        return DegradedReason.RATE_LIMITED
    if 500 <= code < 600:
        return DegradedReason.PROVIDER_ERROR
    if 400 <= code < 500:
        return DegradedReason.BAD_REQUEST
    return DegradedReason.TRANSPORT_ERROR


@runtime_checkable
class LLMProvider(Protocol):
    """What the agents are allowed to ask of a language model."""

    name: str

    model: str | None
    """Which model answered, when the provider has one. `None` for the stub.

    Added in Phase 4A and deliberately additive: the protocol's one method is
    unchanged, so every existing provider still satisfies it. It exists because
    "a model wrote this narrative" and "gemini-3.8-flash wrote this narrative"
    are different facts to an auditor, and the second one was not recoverable
    from anywhere in the analysis result.
    """

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        """Return explanatory prose about `request.facts`.

        MUST NOT raise. A provider that cannot answer returns a degraded result
        so that an LLM outage can never fail a claims workflow.
        """
        ...


SYSTEM_PROMPT = (
    "You write short, factual explanations for insurance claims staff at a New "
    "Zealand home insurer. You are given structured facts about a storm damage "
    "claim that have already been determined by business rules.\n\n"
    "Rules you must follow:\n"
    "- Describe only what is in the facts. Never invent details, figures or findings.\n"
    "- Never state or imply that a claim is approved, declined, settled or fraudulent.\n"
    "- Risk indicators are prompts to investigate, never accusations.\n"
    "- Do not give cover decisions or quote policy wording that is not supplied.\n"
    "- Plain professional English. No bullet points, no headings, no preamble."
)
