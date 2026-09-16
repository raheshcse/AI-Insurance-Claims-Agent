"""Claims intelligence endpoints.

    POST /api/claims/{claim_id}/analyze    run the workflow
    GET  /api/claims/{claim_id}/analysis   read the stored result

These are **internal, claims-staff endpoints**. They return risk indicators and
policy interpretation, which the requirements say must never reach a customer.
Phase 6 adds the authentication that enforces that; in Phase 2 the separation is
architectural only, and that limitation is stated rather than glossed over.

Nothing here settles, approves, declines or progresses a claim.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_intelligence_service
from app.errors import AnalysisNotFoundError
from app.schemas.claim import ErrorDetail
from app.schemas.intelligence import AnalyseClaimRequest, ClaimIntelligenceResult
from app.services.intelligence_service import ClaimIntelligenceService

router = APIRouter(prefix="/api/claims", tags=["claims intelligence (internal)"])

ServiceDep = Annotated[ClaimIntelligenceService, Depends(get_intelligence_service)]


@router.post(
    "/{claim_id}/analyze",
    response_model=ClaimIntelligenceResult,
    status_code=status.HTTP_200_OK,
    summary="Run the claims intelligence workflow (internal)",
    responses={
        404: {"model": ErrorDetail, "description": "No such claim"},
        503: {"model": ErrorDetail, "description": "The analysis could not be completed"},
    },
)
async def analyse_claim(
    claim_id: str,
    service: ServiceDep,
    payload: AnalyseClaimRequest | None = None,
) -> ClaimIntelligenceResult:
    """Run the five specialist agents over a submitted claim.

    Returns a structured **recommendation**. No customer is contacted, and no
    claim is approved, declined or settled.

    The routing decision *is* applied (Phase 3): a claim needing a person moves
    to Human Review and joins the queue. That write is governed (Phase 4) — the
    response carries the VSL decision under `governance`, and where a gate
    denied the automated route the claim is handled more conservatively than the
    business rules alone asked for, never less.

    A stored analysis is returned if one exists; pass `force_reanalysis` to run
    the agents again.
    """
    options = payload or AnalyseClaimRequest()
    return await service.analyse(claim_id, force=options.force_reanalysis)


@router.get(
    "/{claim_id}/analysis",
    response_model=ClaimIntelligenceResult,
    summary="Read the stored claims intelligence result (internal)",
    responses={404: {"model": ErrorDetail, "description": "No claim, or no analysis yet"}},
)
def get_claim_analysis(claim_id: str, service: ServiceDep) -> ClaimIntelligenceResult:
    result = service.latest(claim_id)
    if result is None:
        raise AnalysisNotFoundError()
    return result
