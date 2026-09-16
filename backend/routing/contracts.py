"""Routing and escalation contracts.

Phase 3 turns the Phase 2 claims intelligence into a **routing decision**: does
this claim continue on the automated path, does it need a person, or does it need
something from the customer first?

Three ideas are kept structurally separate here, because conflating them is how an
AI system ends up appearing to make insurance decisions:

    AI FINDING      what an agent observed        (basis = ai_finding)
    BUSINESS RULE   what the Phase 0 rules say    (basis = business_rule)
    HUMAN DECISION  what a reviewer decided       (never produced here)

`RoutingDecision.is_recommendation_only` is a fixed literal. Routing moves a claim
towards a person; it never decides the claim.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.claim_state import ClaimState


class RoutingOutcome(str, Enum):
    """Where the claim goes next. None of these settles anything."""

    AUTOMATED_PATH_RECOMMENDED = "AUTOMATED_PATH_RECOMMENDED"
    """Nothing in the POC rules argues against continued automated handling.

    NOT an approval. Whether such a claim may ever complete without a person is a
    Phase 4 governance question, decided by a PreNode and the Invariants.
    """

    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    """A claims specialist must handle this claim."""

    INFORMATION_REQUIRED = "INFORMATION_REQUIRED"
    """The claim cannot safely continue until the customer supplies something."""


class ReviewPriority(str, Enum):
    URGENT = "urgent"
    """Emergency pathway. Safety before process."""

    HIGH = "high"
    """Vulnerable customer, no cover basis, or elevated risk."""

    STANDARD = "standard"


class ReviewType(str, Enum):
    STANDARD = "standard_review"
    SPECIALIST = "specialist_review"
    PRIORITY = "priority_review"


class ReasonBasis(str, Enum):
    """Where a reason comes from. The distinction the requirements ask for."""

    AI_FINDING = "ai_finding"
    """An agent observed this. It is a model output, with the uncertainty that implies."""

    BUSINESS_RULE = "business_rule"
    """A Phase 0 rule says so. Deterministic, and traceable to a documented row."""


class EscalationReason(BaseModel):
    """One structured reason a claim needs attention.

    Never "the AI decided to escalate". Every reason names the rule, what was
    observed, and what it was measured against.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable identifier, e.g. 'E-01_LOW_CONFIDENCE'")
    label: str = Field(description="Short human label for the queue, e.g. 'Low confidence'")
    detail: str = Field(description="One sentence a reviewer can act on")
    basis: ReasonBasis
    priority: ReviewPriority = ReviewPriority.STANDARD
    outcome: RoutingOutcome = RoutingOutcome.HUMAN_REVIEW_REQUIRED
    rule_reference: str = Field(
        description="Where the rule is written down, e.g. 'docs/DECISION_TABLE.md D-07'"
    )
    observed_value: str | None = Field(
        default=None, description="What the claim actually showed"
    )
    threshold_value: str | None = Field(
        default=None, description="What it was compared against"
    )
    assumption: str | None = Field(
        default=None,
        description="Set when the rule rests on a POC-proposed threshold rather than an approved one",
    )
    source_agent: str | None = Field(
        default=None, description="Which agent produced the underlying finding"
    )


class RoutingDecision(BaseModel):
    """The Phase 3 output: where the claim goes, and exactly why."""

    model_config = ConfigDict(extra="forbid")

    outcome: RoutingOutcome
    priority: ReviewPriority
    review_type: ReviewType | None = Field(
        default=None, description="Null when no human review is needed"
    )
    reasons: list[EscalationReason] = Field(default_factory=list)
    primary_reason_code: str | None = None
    summary: str = Field(description="One sentence stating the decision")
    explanation: list[str] = Field(
        default_factory=list,
        description="Reader-facing explanation, one line per reason",
    )
    recommended_claim_state: ClaimState
    decided_at: str
    rules_evaluated: int = 0

    # -- the boundary, made structural ------------------------------------
    is_recommendation_only: Literal[True] = True
    """Routing moves a claim towards a person. It never decides the claim."""

    decision_authority: Literal["business_rules"] = "business_rules"
    """Not the model. Every routing outcome is rule-derived from Phase 0."""

    boundary_note: str = (
        "A routing decision, not a claim decision. Nothing here approves, declines "
        "or settles a claim, and the automated path is a POC routing concept rather "
        "than permission to complete a claim without a person."
    )

    @property
    def needs_human(self) -> bool:
        return self.outcome is RoutingOutcome.HUMAN_REVIEW_REQUIRED
