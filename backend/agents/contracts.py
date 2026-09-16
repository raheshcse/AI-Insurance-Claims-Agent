"""Agent output contracts.

Every agent returns a structured result, not free text. Narrative exists, but it
sits in one named field beside the structured findings rather than being the
output.

The shared envelope (`AgentResult`) keeps the LangGraph state uniform and makes
the Phase 4 governance work tractable: a gate needs to read a recommendation and
a confidence from a known place, whichever agent produced it.

**Everything here is a recommendation.** No agent result authorises an action.
`AgentResult.is_recommendation_only` is True and cannot be set otherwise.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentStatus(str, Enum):
    """How the agent's own run went -- not a claim outcome."""

    COMPLETE = "complete"
    """The agent produced a full result."""

    INCOMPLETE = "incomplete"
    """The agent ran, but the inputs were insufficient for a full result."""

    DEGRADED = "degraded"
    """The agent produced a result with reduced support (e.g. no LLM, no data)."""

    FAILED = "failed"
    """The agent could not produce a result. Never implies anything about the claim."""


class Severity(str, Enum):
    INFO = "info"
    ATTENTION = "attention"
    CONCERN = "concern"


class Finding(BaseModel):
    """One structured observation. The unit every agent reports in."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable identifier, e.g. 'POLICY_NOT_IN_FORCE'")
    summary: str = Field(description="One line, plain language")
    severity: Severity = Severity.INFO
    detail: str | None = None
    data_reference: str | None = Field(
        default=None,
        description="Where this came from, e.g. 'policies.jsonl:POL-HOME-20117' or 'wording 4.2'",
    )
    assumption: str | None = Field(
        default=None,
        description="Set when the finding rests on a POC-proposed threshold rather than an approved rule",
    )


class Confidence(BaseModel):
    """Confidence in the agent's own output.

    `clears_poc_threshold` reports whether `value` reaches the confidence floor
    implied by the POC-proposed decision boundary. Phase 2 only reports it.
    Nothing gates on it -- the PreNode that will is Phase 4.
    """

    model_config = ConfigDict(extra="forbid")

    value: Annotated[float, Field(ge=0.0, le=1.0)]
    basis: str = Field(description="Why this number, in one line")
    clears_poc_threshold: bool | None = None
    threshold_note: str | None = None


class AgentResult(BaseModel):
    """The envelope every agent returns."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    status: AgentStatus
    findings: list[Finding] = Field(default_factory=list)
    recommendation: str = Field(description="What the agent suggests, in plain language")
    reasons: list[str] = Field(default_factory=list)
    confidence: Confidence | None = None
    data_references: list[str] = Field(default_factory=list)
    next_step: str | None = None
    narrative: str | None = Field(
        default=None, description="Explanatory prose. Never a decision."
    )
    narrative_source: str | None = Field(
        default=None, description="Which provider produced the narrative, and whether degraded"
    )
    narration_governance: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The VSL decision on this agent's LLM call (CP-13). `llm_called` is "
            "the load-bearing field: False means the gate denied and the "
            "provider was never reached, not that its answer was discarded."
        ),
    )
    error: str | None = Field(
        default=None, description="Customer-safe reason the agent failed, if it did"
    )
    is_recommendation_only: Literal[True] = True
    """Structural, not decorative. No agent result authorises an action."""


# ---------------------------------------------------------------------------
# Per-agent payloads. Each rides alongside the envelope in the workflow state.
# ---------------------------------------------------------------------------


class IntakePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    peril: str
    date_of_loss: date
    days_since_loss: int
    loss_address: str
    damaged_item_count: int
    damage_areas: list[str] = Field(default_factory=list)
    itemised_estimate_total: float | None = None
    customer_estimated_value: float | None = None
    description_word_count: int = 0
    missing_information: list[str] = Field(default_factory=list)
    urgency_signals: list[str] = Field(
        default_factory=list,
        description="Observed only. Phase 2 does not route on these -- Phase 3 does.",
    )


class PolicyFacts(BaseModel):
    """What the policy record says. No interpretation."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    policy_status: str
    inception_date: date
    expiry_date: date
    covered_perils: list[str]
    dwelling_sum_insured: float
    contents_sum_insured: float
    standard_excess: float
    storm_excess: float | None = None
    exclusion_codes: list[str] = Field(default_factory=list)
    condition_codes: list[str] = Field(default_factory=list)
    optional_covers: list[str] = Field(default_factory=list)
    insured_address: str


class PolicyInterpretation(BaseModel):
    """The agent's reading of those facts. Not an insurance decision."""

    model_config = ConfigDict(extra="forbid")

    policy_found: bool
    in_force_at_date_of_loss: bool | None = None
    peril_covered: bool | None = None
    address_matches_insured_address: bool | None = None
    applicable_excess: float | None = None
    exclusions_possibly_engaged: list[str] = Field(default_factory=list)
    cover_certainty: Literal["clear", "uncertain", "no_cover_basis", "unknown"] = "unknown"
    relevant_wording_refs: list[str] = Field(default_factory=list)
    caveat: str = (
        "An AI reading of policy wording. Not a cover decision and not an "
        "authoritative interpretation -- a claims specialist decides cover."
    )


class PolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: PolicyFacts | None = None
    interpretation: PolicyInterpretation


class ValidationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_status: Literal["complete", "information_required", "inconsistent"]
    missing_information: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    checks_performed: list[str] = Field(default_factory=list)


class AssessmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_category: str
    complexity_band: Literal["low", "medium", "high"]
    complexity_factors: list[str] = Field(default_factory=list)
    urgency_band: Literal["standard", "high", "emergency"]
    severity_indicators: list[str] = Field(default_factory=list)
    estimated_claim_value: float | None = None
    estimate_basis: str = ""
    value_band: Literal[
        "low_value", "standard", "high_value", "above_automated_authority", "unknown"
    ] = "unknown"
    net_of_excess_estimate: float | None = None


class RiskIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    name: str
    detail: str
    severity: Literal["standard", "severe"]
    data_reference: str
    customer_visible: Literal[False] = False


class RiskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: Literal["low", "medium", "high"]
    indicators: list[RiskIndicator] = Field(default_factory=list)
    historical_claims_considered: int = 0
    framing_note: str = (
        "Risk indicators are prompts for a human to look more closely. They are "
        "not evidence of fraud and must never be shown to or implied to the customer."
    )


AgentPayload = (
    IntakePayload | PolicyPayload | ValidationPayload | AssessmentPayload | RiskPayload
)


class AgentOutput(BaseModel):
    """Envelope plus payload -- what a node writes into the workflow state."""

    model_config = ConfigDict(extra="forbid")

    result: AgentResult
    payload: dict[str, Any] | None = None
