"""Health endpoint.

Used by the frontend to tell "the backend is down" apart from "your form is
invalid" -- the two need different messages to a customer.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/api/health", summary="Service health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "3", "scope": "home-insurance/storm-damage/fnol"}
