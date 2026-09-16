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


@dataclass(frozen=True)
class NarrationResult:
    text: str
    provider: str
    model: str | None = None
    degraded: bool = False
    """True when the provider could not be reached and a fallback was used."""

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

    TRANSPORT_ERROR = "transport_error"
    """The request could not be completed -- DNS, TLS, proxy, timeout, or a
    non-2xx status. The exception class name is logged; nothing more."""

    UNUSABLE_STATUS = "unusable_interaction_status"
    """The Interactions API answered, but with a status that carries no answer
    (`failed`, `requires_action`, `in_progress`)."""

    EMPTY_RESPONSE = "empty_response_text"
    """A 200 with no text in it -- typically a safety filter."""


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
