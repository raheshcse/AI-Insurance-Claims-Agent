"""The Conversation Agent.

The sixth specialist agent, and deliberately not a replacement for the other
five. Its responsibility is narrow and stated here so it stays narrow:

    READ one customer message and propose structured values for the claim.

It does not assess damage, interpret policy, validate cover, score risk or route
anything. Those are the existing agents' jobs and they still do them, after the
claim exists. Merging them into one "chatbot agent" would collapse five auditable
responsibilities into one prompt.

=============================================================================
THE GOVERNED SEQUENCE

Its model call is a governed commitment point, and it follows the approved
baseline architecture exactly:

    Conversation Agent
        -> VSL PreNode + Monitor
        -> Gamma evaluation / threshold
        -> ALLOW
        -> Gemini
        -> Generated Output
        -> VSL Invariant   (INV-05 no-fabricated-claim-values,
                            INV-06 no-claim-decision-in-assistant-output)
        -> PASS
        -> deterministic validation -> conversation state

On a PreNode DENY the model is never called. On an Invariant VIOLATION the
generated output is never returned to this agent, so it cannot reach the
conversation state -- `govern_conversation_extraction` returns `None` and this
agent falls back to the deterministic path.

The agent does not perform that sequence itself. It hands the call in and is
handed the outcome; the gate lives in `governance/gates.py` for the same reason
CP-13's does -- a component that gates itself can stop gating itself.
=============================================================================

WHAT HAPPENS WHEN THERE IS NO MODEL

Everything still works. The deterministic path in `ConversationService` treats a
reply as an answer to the question just asked, validates it, and moves on. The
model adds one thing on top: understanding a message that carries several facts
at once, or facts nobody asked for yet. That is why a denial, a violation, a
missing API key and an outage all degrade to "asks one question at a time"
rather than to "cannot take a claim".
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.contracts import AgentResult, AgentStatus
from conversation.fields import EXTRACTABLE_FIELDS
from llm.base import LLMProvider, NarrationRequest

logger = logging.getLogger("claims.agents")

EXTRACTION_INSTRUCTION = (
    "You read a single message from a customer reporting storm damage to a New "
    "Zealand home, and return ONLY a JSON object. No prose, no code fence, no "
    "explanation.\n\n"
    "The JSON object has exactly two keys:\n"
    '  "extracted"   an object holding ONLY the fields listed below that the '
    "message actually states\n"
    '  "uncertain"   an object mapping a field name to the customer\'s own words, '
    "for anything mentioned but not pinned down\n\n"
    "Rules you must follow:\n"
    "- Include a field ONLY if the message states it. Omit everything else.\n"
    "- Never guess, never infer a likely value, never fill a field to be helpful.\n"
    '- If the customer is vague ("sometime last week", "a few thousand"), put it '
    'in "uncertain", never in "extracted".\n'
    "- A policy number and a money amount must be copied from the message "
    "exactly. Do not reconstruct either from memory.\n"
    "- Resolve a relative date ONLY when it is unambiguous, and return it as "
    "YYYY-MM-DD. Otherwise mark it uncertain.\n"
    "- Never state or imply that a claim is approved, declined, covered, "
    "settled or fraudulent.\n"
)
"""The task instruction for the extraction call.

It asks for a reading, not a decision, and the application does not depend on
the model obeying it: every value is validated in `conversation/fields.py` and
INV-05 checks the output before it is used. A prompt is guidance; the validator
and the Invariant are the enforcement."""


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "extracted": {
            "type": "object",
            "description": (
                "Only the fields the message actually states. Omit everything else."
            ),
            "properties": {name: {} for name in EXTRACTABLE_FIELDS},
        },
        "uncertain": {
            "type": "object",
            "description": (
                "Fields the customer mentioned but did not pin down, mapped to "
                "their own words."
            ),
            "properties": {name: {"type": "string"} for name in EXTRACTABLE_FIELDS},
        },
    },
    "required": ["extracted", "uncertain"],
}
"""What the model is asked to return, as a schema rather than as a hope.

Two things it buys, and the second is the one that mattered:

1. The reply parses. A model that wraps JSON in a code fence, or opens with
   "Here is the JSON:", used to have its whole answer discarded by the parser.
2. The field names are pinned to the catalogue. A schema listing exactly the
   extractable fields is a much stronger hint than a sentence in a prompt
   asking nicely for the same thing.

It is a request, not a guarantee. `parse_extraction` still copes with prose,
every value still goes through `conversation/fields.py`, and INV-05 still judges
the output. A schema improves the odds; it is not a control."""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_extraction(text: str | None) -> dict[str, Any]:
    """Pull the JSON object out of the model's reply. Never raises.

    Models add code fences, a leading "Here is the JSON:", or a trailing
    apology. A parser that only accepts a bare object would degrade a working
    model to no model at all, so this finds the outermost braces. Anything it
    cannot read becomes an empty extraction, which is the same as the model
    having said nothing -- the safe direction.
    """
    if not text:
        return {"extracted": {}, "uncertain": {}}

    candidate = text.strip()
    if not candidate.startswith("{"):
        match = _JSON_BLOCK.search(candidate)
        candidate = match.group(0) if match else ""

    if not candidate:
        return {"extracted": {}, "uncertain": {}}

    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return {"extracted": {}, "uncertain": {}}

    if not isinstance(parsed, dict):
        return {"extracted": {}, "uncertain": {}}

    extracted = parsed.get("extracted")
    uncertain = parsed.get("uncertain")

    # Keys the catalogue does not know about are dropped HERE, before anything
    # sees them. A model that returns `{"claim_id": "CLM-..."}` or
    # `{"customer_confirmed": true}` has no route into the state at all -- not
    # because the validator would reject it, but because it is not in the
    # allow-list and never becomes a field in the first place.
    return {
        "extracted": {
            key: value
            for key, value in (extracted or {}).items()
            if key in EXTRACTABLE_FIELDS
        }
        if isinstance(extracted, dict)
        else {},
        "uncertain": {
            key: str(value)
            for key, value in (uncertain or {}).items()
            if key in EXTRACTABLE_FIELDS
        }
        if isinstance(uncertain, dict)
        else {},
    }


class ConversationAgent:
    """Proposes structured values from one customer message.

    Not a `ClaimsAgent` subclass. `ClaimsAgent.narrate()` is built around
    governing CP-13 for a claim that already exists; this agent's model call is
    a different commitment point, governed by a different gate, on a
    conversation that has no claim yet. Inheriting would have meant overriding
    the one method that matters, which is a signal it is not the same thing.
    """

    name = "conversation"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def provider_name(self) -> str:
        """Which provider CONFIGURATION selected -- not whether it answered.

        Published beside `request_succeeded` so the two can never be confused.
        A Gemini provider that degraded still reports `gemini` here, because
        that is what was selected, and pretending otherwise is what made a
        broken key look like a deliberate choice of the stub."""
        return getattr(self._llm, "name", "unknown")

    # -- what the gate calls ----------------------------------------------

    def build_request(
        self, message: str, *, asked_about: str | None, known: list[str]
    ) -> NarrationRequest:
        """The model request. Built here so a test can assert its contents.

        Note what is NOT in it: no customer name, email, phone or address, and
        no previously collected values -- only the FIELD NAMES already known, so
        the model does not re-propose them. Sending the collected values back
        would put the policyholder's own details into an outbound payload and
        trip INV-04, correctly.
        """
        return NarrationRequest(
            purpose="extract structured claim information from a customer message",
            facts={
                "customer_message": message,
                "question_just_asked": asked_about,
                "fields_already_known": known,
                "fields_you_may_return": list(EXTRACTABLE_FIELDS),
            },
            max_words=400,
            system_instruction=EXTRACTION_INSTRUCTION,
            response_schema=EXTRACTION_SCHEMA,
        )

    def extract(self, request: NarrationRequest) -> Any:
        """Make the call. Invoked BY THE GATE, never directly by the service."""
        return self._llm.narrate(request)

    @staticmethod
    def inspect(result: Any) -> dict[str, Any]:
        """Turn a provider result into the candidate the Invariants judge.

        Separate from `extract` so the gate never has to know what a provider
        response looks like, and so the Invariants are handed the facts they
        judge and nothing else.
        """
        parsed = parse_extraction(getattr(result, "text", None))
        return {
            "extracted": parsed["extracted"],
            "uncertain": parsed["uncertain"],
            "assistant_message": getattr(result, "text", "") or "",
        }

    # -- reporting ---------------------------------------------------------

    def result(self, *, status: AgentStatus, recommendation: str, reasons: list[str]) -> AgentResult:
        """An AgentResult for the trace, in the same shape as every other agent."""
        return AgentResult(
            agent=self.name,
            status=status,
            recommendation=recommendation,
            reasons=reasons,
            confidence=None,
            next_step="continue_conversation",
        )
