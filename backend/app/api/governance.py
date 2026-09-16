"""Governance dashboard endpoints (internal).

    GET /api/governance                      the dashboard
    GET /api/governance/configuration        the declared specification
    GET /api/governance/ledger               ledger entries
    GET /api/governance/ledger/{claim_id}    one claim's governance trail
    GET /api/governance/audit                integrity + the five audit checks

**Read-only, every one of them.** There is no endpoint here that changes
governance state. Lifting a terminal state is a review action with named human
authority and lives on the review router, where it is recorded as a person's
decision — not a dashboard button.

These are internal claims-staff endpoints. They expose policy interpretation and
risk indicators, which must never reach a customer; Phase 6 adds the
authentication that enforces that.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.schemas.claim import ErrorDetail
from app.schemas.governance import (
    AuditStatus,
    GovernanceConfiguration,
    GovernanceDashboard,
    LedgerEntryView,
)
from app.services.governance_service import GovernanceService

router = APIRouter(prefix="/api/governance", tags=["governance (internal)"])


def get_governance_service() -> GovernanceService:
    return GovernanceService()


ServiceDep = Annotated[GovernanceService, Depends(get_governance_service)]


@router.get(
    "",
    response_model=GovernanceDashboard,
    summary="The governance dashboard (internal)",
)
def dashboard(
    service: ServiceDep,
    limit: int = Query(default=100, ge=1, le=1000, description="Recent entries to return"),
) -> GovernanceDashboard:
    """What is declared, what happened, and whether it holds up.

    `audit.all_passed` is the framework's own verdict and is reported whether it
    passes or not. An open terminal state fails check 5 by design — that is the
    ledger reporting unfinished governance, and it is shown as a failure rather
    than smoothed over.
    """
    return service.dashboard(limit=limit)


@router.get(
    "/configuration",
    response_model=GovernanceConfiguration,
    summary="The active governance specification (internal)",
)
def configuration(service: ServiceDep) -> GovernanceConfiguration:
    """The PreNode, the Invariants, the terminal state and the derived assurance.

    `assurance_level` is LOW, derived by VSL from the F1/F2 facts rather than
    asserted. Every threshold is a POC proposal awaiting business approval.
    """
    return service.configuration()


@router.get(
    "/ledger",
    response_model=list[LedgerEntryView],
    summary="VerbaLedger entries, newest first (internal)",
)
def ledger_entries(
    service: ServiceDep,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[LedgerEntryView]:
    return service.dashboard(limit=limit).recent_entries


@router.get(
    "/ledger/{claim_id}",
    response_model=list[LedgerEntryView],
    summary="One claim's governance trail, oldest first (internal)",
    responses={404: {"model": ErrorDetail, "description": "No such claim"}},
)
def ledger_for_claim(claim_id: str, service: ServiceDep) -> list[LedgerEntryView]:
    """Every governance record for one claim, in causal order.

    An empty list means nothing has been governed for this claim yet. It does
    not mean the claim passed.
    """
    return service.entries_for_claim(claim_id)


@router.get(
    "/audit",
    response_model=AuditStatus,
    summary="Ledger integrity and the five audit checks (internal)",
)
def audit(
    service: ServiceDep,
    max_monitor_gap_seconds: float | None = Query(
        default=None,
        description=(
            "Longest acceptable gap between MONITOR entries. Omitted, the "
            "framework skips check 1 and it is reported as not asserted rather "
            "than passed."
        ),
    ),
) -> AuditStatus:
    return service.audit_status(max_monitor_gap_seconds=max_monitor_gap_seconds)
