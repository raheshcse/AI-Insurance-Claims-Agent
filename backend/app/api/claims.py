"""Claims endpoints.

Phase 1 exposes exactly what the customer journey needs:
    POST /api/claims        lodge a storm-damage FNOL
    GET  /api/claims/{id}   read back a lodged claim

Phase 2 adds policy retrieval, validation, assessment and risk endpoints as
separate routers. This router stays about claim intake.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_claim_service
from app.errors import ClaimNotFoundError
from app.schemas.claim import ClaimResponse, ClaimSubmissionRequest, ErrorDetail
from app.services.claim_service import ClaimService

router = APIRouter(prefix="/api/claims", tags=["claims"])

ServiceDep = Annotated[ClaimService, Depends(get_claim_service)]


@router.post(
    "",
    response_model=ClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Lodge a storm-damage FNOL",
    responses={
        422: {"model": ErrorDetail, "description": "The FNOL is incomplete or invalid"},
        503: {"model": ErrorDetail, "description": "The claim could not be lodged"},
    },
)
def submit_claim(payload: ClaimSubmissionRequest, service: ServiceDep) -> ClaimResponse:
    """Create a claim record and set its state to **Submitted**.

    The claim is NOT assessed, classified, risk-checked or routed. Those belong
    to Phase 2 and Phase 3. A successful response means one thing: the claim
    exists and has been lodged.
    """
    return service.submit_claim(payload)


@router.get(
    "/{claim_id}",
    summary="Retrieve a lodged claim",
    responses={404: {"model": ErrorDetail, "description": "No such claim"}},
)
def get_claim(claim_id: str, service: ServiceDep) -> dict:
    """Read back a claim by its reference, for the confirmation and status view."""
    claim = service.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError()
    return claim
