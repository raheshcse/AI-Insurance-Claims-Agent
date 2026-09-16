"""What the conversational assistant API returns.

Two rules shape these models, both from the phase brief:

1. **The customer view carries no governance vocabulary.** Nothing a customer
   sees says VSL, PreNode, Invariant, Gamma, VerbaLedger or an agent name. The
   `governance` field on a turn exists for the staff console and the tests, and
   the customer UI does not render it.

2. **Progress is a fact, not a feeling.** `collected_count` / `required_count`
   come from the field catalogue, so the progress bar and the assistant's next
   question can never disagree.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.claim_state import ClaimState
from conversation.contracts import ConversationStage


class CollectedItem(BaseModel):
    """One thing the assistant has recorded, rendered for display."""

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    value: str


class MissingItem(BaseModel):
    """One thing still needed, with the question that would get it."""

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    question: str


class UncertainItem(BaseModel):
    """Something the customer said that could not be pinned down.

    Published separately from `missing` because they mean different things to a
    customer: one is "we have not asked yet", the other is "you told us and we
    could not use it", and showing them as the same thing would look like the
    assistant was not listening.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    said: str
    why: str


class ConversationView(BaseModel):
    """The whole conversation, as the customer UI needs it."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    claim_id: str | None = None
    current_stage: ConversationStage

    collected_information: list[CollectedItem] = Field(default_factory=list)
    missing_information: list[MissingItem] = Field(default_factory=list)
    uncertain_information: list[UncertainItem] = Field(default_factory=list)

    claim_ready: bool = False
    customer_confirmed: bool = False

    collected_count: int = 0
    required_count: int = 0

    messages: list[dict[str, Any]] = Field(default_factory=list)

    assistant_authority_note: str = (
        "This assistant collects the information needed to report a claim. It "
        "does not approve, decline or settle a claim — a claims specialist "
        "decides that."
    )


class StartConversationRequest(BaseModel):
    """Deliberately empty.

    A conversation starts with nothing known. Accepting a pre-populated state
    here would let a caller inject collected values that never came from a
    customer, which is the fabrication INV-05 exists to stop, arriving by API.
    """

    model_config = ConfigDict(extra="forbid")


class CustomerMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class AssistantTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str
    conversation: ConversationView
    governance: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The VSL decision on this turn's governed model call. INTERNAL — "
            "the customer interface does not render it."
        ),
    )


class ConfirmRequest(BaseModel):
    """The explicit confirmation.

    `confirmed` must be True. A request body that could be omitted or defaulted
    would make an accidental POST create a claim, and "explicit customer
    confirmation" has to survive a stray retry.
    """

    model_config = ConfigDict(extra="forbid")

    confirmed: bool = Field(
        description="Must be true. The customer has seen the summary and agreed to submit."
    )


class ClaimCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_state: ClaimState
    submitted_at: str
    message: str
    conversation: ConversationView
    poc_note: str = (
        "The claim has been lodged. It has not been assessed, approved, declined "
        "or settled, and no payment has been made."
    )
