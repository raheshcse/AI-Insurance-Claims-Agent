"""Phase 1 backend tests — the claim state model.

Phase 1 performs only Draft -> Submitted. These tests pin the model that Phase 2+
extends, and check that official states and internal statuses stay separate.
"""

from __future__ import annotations

import pytest

from app.domain.claim_state import (
    ClaimState,
    InternalStatus,
    is_transition_allowed,
)
from app.domain.reference import generate_claim_reference


def test_the_six_official_states_exist_and_no_others():
    assert {state.value for state in ClaimState} == {
        "Draft",
        "Submitted",
        "Information Required",
        "Assessment",
        "Human Review",
        "Approved/Completed",
    }


def test_phase_1_transition_is_allowed():
    assert is_transition_allowed(ClaimState.DRAFT, ClaimState.SUBMITTED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ClaimState.DRAFT, ClaimState.ASSESSMENT),
        (ClaimState.DRAFT, ClaimState.APPROVED_COMPLETED),
        (ClaimState.SUBMITTED, ClaimState.APPROVED_COMPLETED),
        (ClaimState.APPROVED_COMPLETED, ClaimState.ASSESSMENT),
    ],
)
def test_shortcuts_through_the_lifecycle_are_not_allowed(current, target):
    assert not is_transition_allowed(current, target)


def test_approved_completed_is_terminal_for_the_poc():
    assert is_transition_allowed(ClaimState.APPROVED_COMPLETED, ClaimState.ASSESSMENT) is False


def test_internal_statuses_are_not_official_states():
    official = {state.value for state in ClaimState}
    internal = {status.value for status in InternalStatus}
    assert official.isdisjoint(internal)


def test_denial_and_suspension_statuses_are_distinct():
    """A PreNode denial and an Invariant suspension must never collapse into one."""
    assert (
        InternalStatus.GOVERNANCE_DENIED_PRENODE.value
        != InternalStatus.AUTOMATION_SUSPENDED.value
    )


def test_claim_reference_format():
    reference = generate_claim_reference()
    prefix, year, sequence = reference.split("-")
    assert prefix == "CLM"
    assert len(year) == 4 and year.isdigit()
    assert len(sequence) == 6 and sequence.isdigit()
