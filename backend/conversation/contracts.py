"""The conversation domain.

Phase 5 turns a six-step form into a conversation. The thing that makes that
safe rather than merely pleasant is this module: a **structured state** that is
authoritative, and a chat transcript that is not.

    messages              what was said. Presentation. Never a source of truth.
    collected             what we know, with the customer's own words attached.
    missing               what we still need, derived from the field catalogue.
    uncertain             what was said but could not be pinned down.

An LLM reading its own chat history and re-deciding what it knows is the
architecture this deliberately avoids: it makes every turn a chance to forget a
fact, invent one, or quietly change one the customer already confirmed.
`collected` is written by deterministic validation, never by the model directly,
and `missing` is computed from it -- so "what do we still need?" has one answer
and it does not depend on what the model remembers.

FIELD NAMES MATCH THE FNOL. Every key in `collected` maps onto
`app.schemas.claim.ClaimSubmissionRequest` (docs/SYNTHETIC_DATA_SPEC.md 4.2), so
claim creation is a projection rather than a translation. A second vocabulary
for the same facts is how two systems drift apart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ConversationStage(str, Enum):
    """Where the conversation has got to.

    A stage is a *view* over the state, not a lock: a customer who volunteers
    their policy number while being asked about damage has that fact recorded,
    and the stage simply moves on. Stages that gate what may be said next would
    turn a conversation back into a form with extra steps.
    """

    START = "start"
    CUSTOMER_INFORMATION = "customer_information"
    POLICY_INFORMATION = "policy_information"
    INCIDENT_INFORMATION = "incident_information"
    DAMAGE_INFORMATION = "damage_information"
    SAFETY_CHECK = "safety_check"
    MISSING_INFORMATION = "missing_information"
    REVIEW = "review"
    READY_FOR_CONFIRMATION = "ready_for_confirmation"
    CUSTOMER_CONFIRMATION = "customer_confirmation"
    CLAIM_CREATED = "claim_created"


MessageRole = Literal["customer", "assistant"]


class ConversationMessage(BaseModel):
    """One turn. Transcript only -- nothing downstream reads a fact from here."""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole
    text: str
    at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CollectedValue(BaseModel):
    """One fact, with its provenance.

    `source_text` is the customer's own wording, kept so a reviewer can always
    answer "where did this number come from?" without re-reading the transcript.
    `confirmed_by_customer` is set only at the confirmation step -- a value the
    assistant extracted is a proposal until the customer has seen the summary.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any
    source_text: str | None = None
    source: Literal["customer_message", "deterministic", "customer_confirmation"] = (
        "customer_message"
    )
    at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UncertainValue(BaseModel):
    """Something the customer said that could not be pinned down.

    The existence of this model is the point. "Sometime last week" is not a date
    and is not nothing -- recording it as neither missing nor known is what lets
    the assistant ask a specific follow-up instead of either guessing a Tuesday
    or asking again from scratch.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    said: str
    why: str = Field(description="Why it could not be accepted, in plain language")


class ConversationState(BaseModel):
    """The authoritative record of one claim conversation."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    claim_id: str | None = None
    customer_id: str | None = None
    policy_id: str | None = None

    current_stage: ConversationStage = ConversationStage.START

    collected_information: dict[str, CollectedValue] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    uncertain_information: list[UncertainValue] = Field(default_factory=list)

    claim_ready: bool = False
    customer_confirmed: bool = False

    last_asked: str | None = Field(
        default=None,
        description=(
            "The field the assistant's last question was about, or None if it "
            "has not asked anything yet."
        ),
    )
    """Recorded, not derived, and that distinction cost a bug worth keeping the
    note for.

    Deriving it as "the next required field" looks equivalent and is not: on the
    opening turn the assistant has asked nothing, yet the next required field is
    `full_name` -- so "A storm damaged my roof last night" was accepted as the
    customer's name, and the conversation then asked for an email while holding
    a sentence as a person. A reply can only answer a question that was actually
    put."""

    messages: list[ConversationMessage] = Field(default_factory=list)

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # -- helpers ----------------------------------------------------------

    def value(self, field_name: str) -> Any:
        entry = self.collected_information.get(field_name)
        return entry.value if entry else None

    def values(self) -> dict[str, Any]:
        return {name: item.value for name, item in self.collected_information.items()}

    def record(
        self,
        field_name: str,
        value: Any,
        *,
        source_text: str | None = None,
        source: str = "customer_message",
    ) -> None:
        self.collected_information[field_name] = CollectedValue(
            value=value, source_text=source_text, source=source  # type: ignore[arg-type]
        )

    def add_message(self, role: MessageRole, text: str) -> None:
        self.messages.append(ConversationMessage(role=role, text=text))
        self.touch()

    def flag_uncertain(self, field_name: str, said: str, why: str) -> None:
        """Replace any previous uncertainty about the same field.

        Keeping a history of everything the customer could not pin down would
        make the assistant re-ask questions it has already moved past.
        """
        self.uncertain_information = [
            item for item in self.uncertain_information if item.field != field_name
        ]
        self.uncertain_information.append(
            UncertainValue(field=field_name, said=said, why=why)
        )

    def clear_uncertain(self, field_name: str) -> None:
        self.uncertain_information = [
            item for item in self.uncertain_information if item.field != field_name
        ]

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
