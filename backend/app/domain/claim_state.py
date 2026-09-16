"""Claim lifecycle model.

The six OFFICIAL business claim states come from the requirements document and are
documented in docs/CLAIM_JOURNEY.md section 3. No additional official states are
invented here.

Internal workflow statuses (docs/CLAIM_JOURNEY.md section 4) are deliberately a
SEPARATE enum so that they can never be confused with, or substituted for, an
official state.

Phase 1 implements only the Draft -> Submitted transition. The rest of the
transition map is declared here so later phases extend it rather than replace it.
"""

from __future__ import annotations

from enum import Enum


class ClaimState(str, Enum):
    """The six official business claim states."""

    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    INFORMATION_REQUIRED = "Information Required"
    ASSESSMENT = "Assessment"
    HUMAN_REVIEW = "Human Review"
    APPROVED_COMPLETED = "Approved/Completed"


class InternalStatus(str, Enum):
    """Internal workflow statuses. NOT official claim states.

    Carried alongside a ClaimState so the workflow, the review queue and the
    governance dashboard can describe what is happening without inventing
    business states.
    """

    INTAKE_IN_PROGRESS = "intake_in_progress"
    AWAITING_CUSTOMER_RESPONSE = "awaiting_customer_response"
    POLICY_RETRIEVED = "policy_retrieved"
    VALIDATED = "validated"
    ASSESSMENT_COMPLETE = "assessment_complete"
    GOVERNANCE_PASSED = "governance_passed"
    GOVERNANCE_DENIED_PRENODE = "governance_denied_prenode"
    AUTOMATION_SUSPENDED = "automation_suspended"
    EMERGENCY_PRIORITY = "emergency_priority"
    VULNERABLE_CUSTOMER_SUPPORT = "vulnerable_customer_support"
    SPECIALIST_REFERRAL = "specialist_referral"


# The full transition map from docs/CLAIM_JOURNEY.md section 5.
#
# Declared in full so that Phase 2+ wires new transitions into an existing,
# reviewed structure. Phase 1 only ever performs DRAFT -> SUBMITTED; every other
# entry is unreachable until the phase that owns it is built.
ALLOWED_TRANSITIONS: dict[ClaimState, frozenset[ClaimState]] = {
    ClaimState.DRAFT: frozenset(
        {ClaimState.SUBMITTED, ClaimState.HUMAN_REVIEW}
    ),
    ClaimState.SUBMITTED: frozenset(
        {
            ClaimState.INFORMATION_REQUIRED,
            ClaimState.ASSESSMENT,
            ClaimState.HUMAN_REVIEW,
        }
    ),
    ClaimState.INFORMATION_REQUIRED: frozenset(
        {ClaimState.SUBMITTED, ClaimState.HUMAN_REVIEW}
    ),
    ClaimState.ASSESSMENT: frozenset(
        {
            ClaimState.APPROVED_COMPLETED,
            ClaimState.HUMAN_REVIEW,
            ClaimState.INFORMATION_REQUIRED,
        }
    ),
    ClaimState.HUMAN_REVIEW: frozenset(
        {ClaimState.APPROVED_COMPLETED, ClaimState.INFORMATION_REQUIRED}
    ),
    ClaimState.APPROVED_COMPLETED: frozenset(),
}


def is_transition_allowed(current: ClaimState, target: ClaimState) -> bool:
    """Return True when `current -> target` is a transition the model permits."""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())
