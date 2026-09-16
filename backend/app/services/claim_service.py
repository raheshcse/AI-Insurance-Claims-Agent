"""Claim creation service.

This module is the ONLY place in Phase 1 where a claim record comes into
existence and a claim state is assigned. That is deliberate: commitment point
CP-02 (issue claim reference + write claim record) and CP-09 (claim-state write)
both live here, so Phase 4 has a single call site to gate rather than a scatter
of writes across the API layer.

See docs/COMMITMENT_POINTS.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.domain.claim_state import ClaimState, is_transition_allowed
from app.domain.reference import generate_claim_reference
from app.errors import ClaimCreationError
from app.repositories.claim_repository import ClaimRepository
from app.schemas.claim import ClaimResponse, ClaimSubmissionRequest, ClaimSummary

_MAX_REFERENCE_ATTEMPTS = 5

_NEXT_STEP_SUBMITTED = (
    "Your claim has been lodged. A claims specialist will review the details you "
    "provided and contact you about what happens next."
)


class ClaimService:
    def __init__(self, repository: ClaimRepository) -> None:
        self._repository = repository

    # -- public API ---------------------------------------------------------

    def submit_claim(self, submission: ClaimSubmissionRequest) -> ClaimResponse:
        """Create a claim from a validated FNOL and move it Draft -> Submitted.

        ------------------------------------------------------------------
        GOVERNANCE BOUNDARY -- Phase 4, not Phase 1.

        This is the single call site where the X-Verba/VSL gate for CP-02 and
        CP-09 will be awaited, immediately BEFORE `self._repository.save(...)`
        fires. Nothing resembling a governance check is implemented here now:
        a placeholder that always passes would be a false claim of governance,
        which docs/GOVERNANCE_POLICY_CATALOGUE.md explicitly rules out.

        What Phase 4 inserts, in order:
            decision = await governed_claim_creation(candidate)
            if decision["action"] != "proceed": return / route accordingly
            ... then, and only then, the save below.
        ------------------------------------------------------------------
        """
        # The claim is conceptually in Draft while the customer is filling it in.
        # Phase 1 does not persist drafts, so the transition is asserted here to
        # keep the state model authoritative rather than implicit.
        if not is_transition_allowed(ClaimState.DRAFT, ClaimState.SUBMITTED):
            raise ClaimCreationError("Draft -> Submitted is not a permitted transition.")

        claim_id = self._allocate_claim_reference()
        submitted_at = datetime.now(timezone.utc)

        record = self._build_record(claim_id, submitted_at, submission)

        # CP-02 / CP-09 side effect. Everything above is reversible; this is not.
        self._repository.save(record)

        return ClaimResponse(
            claim_id=claim_id,
            claim_state=ClaimState.SUBMITTED,
            internal_status=None,
            submitted_at=submitted_at.isoformat(),
            next_step=_NEXT_STEP_SUBMITTED,
            summary=self._build_summary(submission),
        )

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        return self._repository.get(claim_id)

    # -- internals ----------------------------------------------------------

    def _allocate_claim_reference(self) -> str:
        for _ in range(_MAX_REFERENCE_ATTEMPTS):
            candidate = generate_claim_reference()
            if not self._repository.exists(candidate):
                return candidate
        raise ClaimCreationError("Could not allocate a unique claim reference.")

    @staticmethod
    def _build_record(
        claim_id: str,
        submitted_at: datetime,
        submission: ClaimSubmissionRequest,
    ) -> dict[str, Any]:
        """Build the persisted claim record.

        Field names follow docs/SYNTHETIC_DATA_SPEC.md section 4 so that the
        Phase 2 agents read the shape Phase 0 defined. Derived AI fields
        (classification, complexity, confidence, risk) are intentionally absent:
        nothing has assessed this claim.
        """
        return {
            "claim_id": claim_id,
            "policy_id": None,  # Phase 2: resolved by the Policy Agent
            "customer_id": None,  # Phase 2: resolved from the policy number
            "claim_state": ClaimState.SUBMITTED.value,
            "internal_status": None,
            "created_at": submitted_at.isoformat(),
            "updated_at": submitted_at.isoformat(),
            "submitted_at": submitted_at.isoformat(),
            "source": "customer_portal",
            "synthetic": True,  # POC data marker -- see INV-04 candidate
            "fnol": submission.model_dump(mode="json"),
        }

    @staticmethod
    def _build_summary(submission: ClaimSubmissionRequest) -> ClaimSummary:
        address = submission.property.loss_address
        return ClaimSummary(
            policy_number=submission.customer.policy_number,
            customer_name=submission.customer.full_name,
            peril=submission.damage.peril,
            date_of_loss=submission.damage.date_of_loss,
            loss_address=(
                f"{address.address_line_1}, {address.suburb}, "
                f"{address.city} {address.postcode}"
            ),
            damaged_item_count=len(submission.damage.damaged_items),
            customer_estimated_value=submission.damage.customer_estimated_value,
        )
