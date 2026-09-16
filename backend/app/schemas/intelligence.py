"""The claims intelligence result.

What the workflow produces, and what the API returns.

The central design point is the separation the requirements insist on:

    AI RECOMMENDATION   vs   ACTUAL CLAIM ACTION

Every field below is on the recommendation side. `action_taken` is fixed at
"none" and `claim_state_changed` at False -- structurally, not by convention --
because Phase 2 executes no consequential claim action. Acting on any of this is
a governed commitment (CP-09, CP-11) that belongs to Phase 3 and Phase 4.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.contracts import AgentResult, Confidence
from app.domain.claim_state import ClaimState
from routing.contracts import RoutingDecision


class RecommendedNextStep(str, Enum):
    """What the workflow suggests a human does next. None of these are actions."""

    INFORMATION_REQUIRED = "information_required"
    """Ask the customer for something before the claim can be assessed."""

    MANUAL_REVIEW_RECOMMENDED = "manual_review_recommended"
    """A claims specialist should handle this claim."""

    SPECIALIST_REVIEW_RECOMMENDED = "specialist_review_recommended"
    """Risk indicators warrant a specialist reviewer."""

    STANDARD_PROCESSING_CANDIDATE = "standard_processing_candidate"
    """Nothing in the analysis argues against ordinary handling.

    NOT an approval, and not an instruction to automate. Whether a claim like
    this may ever be handled without a person is a Phase 4 governance question,
    decided by a PreNode and the Invariants -- none of which exist yet.
    """


class WorkflowTraceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    status: str
    next_step: str | None = None
    error: str | None = None


class WorkflowErrorEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    kind: str
    message: str


class ClaimIntelligenceResult(BaseModel):
    """The structured output of the Phase 2 workflow."""

    model_config = ConfigDict(extra="forbid")

    # -- identity ---------------------------------------------------------
    claim_id: str
    analysis_id: str
    analysed_at: str
    workflow_version: str = "phase-4"

    # -- claim context -----------------------------------------------------
    claim_state: ClaimState = Field(
        description="The claim's state as it stands. Phase 2 does not change it."
    )
    claim_summary: dict[str, Any] = Field(default_factory=dict)

    # -- agent output -------------------------------------------------------
    agent_results: dict[str, AgentResult] = Field(default_factory=dict)
    policy_assessment: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    damage_assessment: dict[str, Any] | None = None
    risk_assessment: dict[str, Any] | None = None

    # -- Phase 3: routing ---------------------------------------------------
    routing: RoutingDecision | None = Field(
        default=None,
        description="Where the claim goes next and exactly why. A routing decision, not a claim decision.",
    )
    customer_context: dict[str, Any] | None = Field(
        default=None,
        description="Operational policyholder fields only — support flag, accessibility, contact preference.",
    )

    # -- Phase 4: governance -----------------------------------------------
    governance_gate: dict[str, Any] | None = Field(
        default=None,
        description="PN-01's decision at the workflow's own commitment point (CP-11).",
    )
    governance: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The authoritative governance outcome at the irreversible write "
            "(CP-09/CP-12): PreNode, Invariants, TerminalState and the ledger "
            "entry ids that record them."
        ),
    )

    # -- overall ------------------------------------------------------------
    recommended_next_step: RecommendedNextStep
    recommendation_summary: str
    recommendation_reasons: list[str] = Field(default_factory=list)
    overall_confidence: Confidence | None = None
    recommended_claim_state: ClaimState | None = Field(
        default=None,
        description=(
            "The state a human might move the claim to. A recommendation only -- "
            "applying it is a governed write that Phase 2 does not perform."
        ),
    )

    # -- the recommendation / action boundary, made structural ---------------
    is_recommendation_only: Literal[True] = True
    """The analysis is a recommendation. It never decides a claim."""

    action_taken: Literal["none"] = "none"
    """No consequential claim action: nothing approved, declined, settled or sent."""

    claim_state_changed: bool = False
    """Phase 3: True when routing moved the claim to Human Review or Information
    Required. That is routing into human control, not a claim decision — the only
    states routing can reach are ones where a person or the customer holds the
    claim. Approved/Completed is reachable only by a reviewer's own action."""

    routing_applied: bool = False
    """True when the routing decision was applied (claim state and/or queue)."""

    boundary_note: str = (
        "This is analysis and routing, not a claim decision. No claim has been "
        "approved, declined or settled, and no customer has been contacted. "
        "Routing may move a claim towards a person; it never decides it."
    )

    # -- execution -----------------------------------------------------------
    trace: list[WorkflowTraceEntry] = Field(default_factory=list)
    errors: list[WorkflowErrorEntry] = Field(default_factory=list)
    degraded: bool = Field(
        default=False, description="True when any agent failed or ran without full data"
    )
    llm_governance: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Summary of the CP-13 gate across this run: how many LLM calls were "
            "permitted, how many were blocked before the provider was reached, "
            "and whether any claim entered a TerminalState because of one."
        ),
    )
    llm_provider: str | None = Field(
        default=None, description="Which provider was configured, e.g. 'gemini' or 'stub'"
    )
    llm_model: str | None = Field(
        default=None,
        description="Which model answered, e.g. 'gemini-3.8-flash'. Null for the stub.",
    )
    llm_degraded: bool = Field(
        default=False,
        description=(
            "True when a provider was configured but unreachable, so the "
            "deterministic fallback wrote the narrative. The claim decision is "
            "unaffected either way -- every value a decision turns on is "
            "rule-derived, never model-derived."
        ),
    )


class AnalyseClaimRequest(BaseModel):
    """Options for a run. The claim itself comes from the path parameter."""

    model_config = ConfigDict(extra="forbid")

    force_reanalysis: bool = Field(
        default=False,
        description="Run again even if a stored analysis exists for this claim.",
    )
