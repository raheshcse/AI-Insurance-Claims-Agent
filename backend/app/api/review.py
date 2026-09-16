"""Human review queue endpoints.

    GET  /api/review-queue                    the queue
    GET  /api/review-queue/{claim_id}         one claim, everything a reviewer needs
    POST /api/review-queue/{claim_id}/action  a POC review action

**Internal, claims-staff endpoints.** They return policy interpretation, risk
indicators and vulnerability flags — none of which may reach a customer. Phase 6
adds the authentication that enforces that; in Phase 3 the separation is
architectural only, and saying so is better than implying otherwise.

No endpoint here approves a claim for payment, settles anything, or contacts a
customer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_intelligence_service, get_review_service
from app.schemas.claim import ErrorDetail
from app.schemas.review import (
    ClaimReviewDetail,
    QueueStatus,
    ReEnablementRequest,
    ReEnablementResponse,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewQueueResponse,
)
from app.services.intelligence_service import ClaimIntelligenceService
from app.services.review_service import ReviewService
from routing.contracts import ReviewPriority

router = APIRouter(prefix="/api/review-queue", tags=["human review (internal)"])

ReviewDep = Annotated[ReviewService, Depends(get_review_service)]
IntelligenceDep = Annotated[ClaimIntelligenceService, Depends(get_intelligence_service)]


@router.get(
    "",
    response_model=ReviewQueueResponse,
    summary="List claims awaiting human review (internal)",
)
def list_queue(
    service: ReviewDep,
    status: QueueStatus | None = Query(default=None, description="Filter by queue status"),
    priority: ReviewPriority | None = Query(default=None, description="Filter by priority"),
) -> ReviewQueueResponse:
    """Urgent first, then high, then oldest first within a band.

    A queue that does not surface the emergency claim first is not doing its job,
    so the ordering is part of the contract rather than a UI concern.
    """
    return service.list_queue(
        status=status.value if status else None,
        priority=priority.value if priority else None,
    )


@router.get(
    "/{claim_id}",
    response_model=ClaimReviewDetail,
    summary="Everything a reviewer needs for one claim (internal)",
    responses={404: {"model": ErrorDetail, "description": "No such claim"}},
)
def review_detail(
    claim_id: str, service: ReviewDep, intelligence: IntelligenceDep
) -> ClaimReviewDetail:
    """What the customer reported, what the policy says, what the agents found,
    what risks were identified, why it was escalated, and what the AI recommends —
    kept distinct from what the reviewer decides."""
    stored = intelligence.latest(claim_id)
    return service.review_detail(
        claim_id, stored.model_dump(mode="json") if stored else None
    )


@router.post(
    "/{claim_id}/action",
    response_model=ReviewActionResponse,
    summary="Record a POC review action (internal)",
    responses={
        404: {"model": ErrorDetail, "description": "No such claim, or not in the queue"},
        409: {"model": ErrorDetail, "description": "Action not available for this claim"},
    },
)
def perform_action(
    claim_id: str, payload: ReviewActionRequest, service: ReviewDep
) -> ReviewActionResponse:
    """Record what the reviewer decided, and move the claim accordingly.

    **These are POC actions.** `complete_review` records that a reviewer finished
    with the claim and moves it to Approved/Completed for demonstration purposes.
    It does not approve a claim for payment, set a reserve, settle anything or
    notify the customer, and the response says so.

    The response carries `decision_source: "human"` — a review outcome is a
    person's decision, never the model's.
    """
    return service.perform_action(claim_id, payload)


@router.post(
    "/{claim_id}/re-enable-automation",
    response_model=ReEnablementResponse,
    summary="Lift a governance TerminalState (internal)",
    responses={
        404: {"model": ErrorDetail, "description": "No such claim"},
        409: {"model": ErrorDetail, "description": "Automation is not suspended"},
    },
)
def re_enable_automation(
    claim_id: str, payload: ReEnablementRequest, service: ReviewDep
) -> ReEnablementResponse:
    """The only exit from `claim-automation-suspended`.

    There is no automatic recovery from a terminal state and no timeout that
    lifts one. A claims authority must supply a root-cause analysis and a
    specification-update proposal; VSL validates that evidence and issues the
    HumanAuthorisedTransition together with the successor instance, so neither
    can be obtained without the other. The transition is written to the
    VerbaLedger, caused by the TERMINAL entry it resolves.

    Re-enabling automation does not decide the claim. The reviewer still holds
    it; only future automated steps become permitted again.
    """
    return service.re_enable_automation(claim_id, payload)
