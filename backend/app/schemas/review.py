"""Human review queue and review-action models.

The queue is how Phase 0's requirement that "human review is a real workflow
state" becomes something you can point at: a claim in Human Review has a queue
entry, a priority, and structured reasons a reviewer can read.

The review actions are **POC actions**. `complete_review` records that a reviewer
finished with the claim; it does not approve, settle or pay anything, and the
model says so in a field rather than in a comment nobody reads.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.claim_state import ClaimState, InternalStatus
from routing.contracts import EscalationReason, ReviewPriority, ReviewType


class QueueStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    CLOSED = "closed"


class ReviewAction(str, Enum):
    """What a reviewer can do in the POC. Deliberately few, and deliberately blunt."""

    START_REVIEW = "start_review"
    """Claim it. Moves the entry to in_review; changes no claim state."""

    REQUEST_INFORMATION = "request_information"
    """Send the claim back for more information → Information Required."""

    REFER_TO_SPECIALIST = "refer_to_specialist"
    """Hand to a specialist reviewer. Stays in Human Review."""

    COMPLETE_REVIEW = "complete_review"
    """Record that the reviewer has finished → Approved/Completed.

    A POC bookkeeping outcome, not an insurance approval. Nothing is paid,
    no reserve is set, and no customer is told anything.
    """


# ---------------------------------------------------------------------------
# Phase 4: how a governance decision is published.
# ---------------------------------------------------------------------------


class GovernanceDecision(BaseModel):
    """One VSL gate decision, as the API reports it.

    `extra="ignore"` because `governance/gates.py` owns this payload's shape;
    the schema is a published view of it, and a new field added there should not
    500 the review screen. Nothing here is editable by a client — it is only
    ever written from a `GovernanceOutcome`.
    """

    model_config = ConfigDict(extra="ignore")

    action: Literal["proceed", "human_queue", "action_denied", "suspended"]
    permitted: bool
    automated_action_allowed: bool = Field(
        default=False,
        description=(
            "Whether the AUTOMATED CLAIM ACTION was permitted. Distinct from "
            "`permitted` on purpose: a gate can return without approving the "
            "automated action, and reading one as the other is the mistake this "
            "field exists to prevent."
        ),
    )
    automated_action_attempted: bool = Field(
        default=False,
        description=(
            "Whether the layer above actually tried to take the automated "
            "action. A denial with this False is routine (routing and "
            "governance agree); with it True it is an incident, and the claim "
            "enters a TerminalState."
        ),
    )
    observed_value: float | None = None
    threshold_value: float | None = None
    decision_id: str
    claim_id: str
    specification: str
    pre_node: str
    pre_node_denied: bool = False
    denial_reason: str | None = None
    invariant_violated: str | None = None
    terminal_state: str | None = None
    fallback: str | None = None
    assurance_level: str | None = Field(
        default=None,
        description="Derived by VSL from the F1/F2 facts, not asserted. LOW for an "
        "output-layer gate — it blocks a bad action, it does not change how the "
        "model decides.",
    )
    gamma_threshold: float | None = None
    confidence: float | None = None
    confidence_floor: float | None = None
    ledger_entry_ids: list[str] = Field(default_factory=list)
    side_effect_performed: bool = False
    automation_suspended: bool = False


class ReEnablementRequest(BaseModel):
    """A claims authority's request to lift a TerminalState.

    Evidence is mandatory and the framework validates it. There is no automatic
    recovery from a terminal state, and this is the only route out of one.
    """

    model_config = ConfigDict(extra="forbid")

    authorised_by: Annotated[str, Field(min_length=2, max_length=120)] = Field(
        description="The claims authority accepting responsibility for re-enabling automation"
    )
    root_cause_analysis: Annotated[str, Field(min_length=20, max_length=4000)] = Field(
        description="Why the Invariant was violated. Required — an empty analysis is refused."
    )
    specification_update_proposal: Annotated[
        str, Field(min_length=20, max_length=4000)
    ] = Field(description="What should change in the governance specification, and why")


class ReEnablementResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    terminal_state: str
    invariant: str
    authorised_by: str
    authority: str
    human_authorised_transition_id: str
    re_enablement_entry_id: str
    new_instance_id: str
    generation: int
    decision_source: Literal["human"] = "human"
    poc_note: str = (
        "Automation is re-enabled for this claim. The claim itself is unchanged: "
        "nothing has been approved, settled or communicated."
    )


class QueueEntrySummary(BaseModel):
    """One row in the queue list.

    A deliberate projection of the full entry — the list view carries what a
    reviewer needs to triage, not the whole case. Extra keys are ignored rather
    than rejected so the same stored record validates as either shape.
    """

    model_config = ConfigDict(extra="ignore")

    queue_id: str
    claim_id: str
    claim_state: ClaimState
    internal_status: str | None = None
    queue_status: QueueStatus
    priority: ReviewPriority
    review_type: ReviewType | None = None
    primary_reason_code: str | None = None
    primary_reason_label: str | None = None
    reason_count: int = 0
    customer_name: str | None = None
    policy_number: str | None = None
    peril: str | None = None
    date_of_loss: str | None = None
    estimated_claim_value: float | None = None
    complexity_band: str | None = None
    risk_level: str | None = None
    confidence: float | None = None
    created_at: str
    updated_at: str
    assigned_to: str | None = None
    automation_suspended: bool = Field(
        default=False,
        description="Phase 4: a TerminalState is open on this claim. Surfaced in the "
        "list view because it changes how a reviewer should treat the row.",
    )


class QueueEntry(QueueEntrySummary):
    """A queue row plus everything a reviewer needs to act."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str | None = None
    reasons: list[EscalationReason] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    routing_summary: str | None = None
    recommended_next_step: str | None = None
    vulnerable_customer: bool = False
    emergency: bool = False
    history: list[dict[str, Any]] = Field(
        default_factory=list, description="Review actions taken, oldest first"
    )

    # -- Phase 4 ----------------------------------------------------------
    governance: GovernanceDecision | None = Field(
        default=None,
        description="The VSL decision that put this entry here, when governance did",
    )


class ReviewQueueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    open_count: int
    urgent_count: int
    entries: list[QueueEntrySummary] = Field(default_factory=list)


class ClaimReviewDetail(BaseModel):
    """Everything the claim review screen needs, in one response.

    Structured so a reviewer can answer the six questions the requirements ask:
    what the customer reported, what the policy says, what the agents found, what
    risks were identified, why it was escalated, and what the AI recommends.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_state: ClaimState
    internal_status: str | None = None
    queue_entry: QueueEntry | None = None
    customer_report: dict[str, Any] = Field(
        default_factory=dict, description="What the customer told us — the FNOL"
    )
    intelligence: dict[str, Any] | None = Field(
        default=None, description="The full claims intelligence result"
    )
    available_actions: list[ReviewAction] = Field(default_factory=list)
    automation_suspended: bool = Field(
        default=False,
        description="Phase 4: a TerminalState is open. A person must re-enable "
        "automation before any automated step can run on this claim again.",
    )
    governance: GovernanceDecision | None = Field(
        default=None, description="The VSL decision recorded against this claim"
    )
    decision_authority_note: str = (
        "Everything the AI produced is a recommendation. The reviewer's action is "
        "the decision. These are recorded separately and must not be conflated."
    )


class ReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    reviewer: Annotated[str, Field(min_length=2, max_length=120)] = Field(
        description="Who is taking the action. No authentication in the POC — Phase 6."
    )
    notes: Annotated[str, Field(max_length=2000)] = Field(
        default="", description="The reviewer's own reasoning, in their words"
    )
    information_requested: list[str] = Field(
        default_factory=list,
        description="For request_information: what the customer is being asked for",
    )


class ReviewActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    action: ReviewAction
    performed_by: str
    performed_at: str
    previous_claim_state: ClaimState
    claim_state: ClaimState
    internal_status: str | None = None
    queue_status: QueueStatus
    notes: str = ""
    decision_source: Literal["human"] = "human"
    """Structural. A review outcome is a person's decision, never the model's."""

    poc_note: str = (
        "A POC review outcome. It records what the reviewer decided in this "
        "demonstration. It does not approve a claim for payment, set a reserve, "
        "settle anything, or notify the customer."
    )


VULNERABLE_REASON_CODE = "E-12_VULNERABLE_CUSTOMER"
EMERGENCY_REASON_CODE = "E-11_EMERGENCY"

# Which internal status accompanies each claim state after a routing decision.
# Internal statuses are NOT official claim states (docs/CLAIM_JOURNEY.md §4).
ROUTING_INTERNAL_STATUS: dict[str, str] = {
    "HUMAN_REVIEW_REQUIRED": InternalStatus.ASSESSMENT_COMPLETE.value,
    "INFORMATION_REQUIRED": InternalStatus.AWAITING_CUSTOMER_RESPONSE.value,
    "AUTOMATED_PATH_RECOMMENDED": InternalStatus.ASSESSMENT_COMPLETE.value,
}
