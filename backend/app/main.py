"""FastAPI application entry point.

Phase 1 architecture:

    React  ->  FastAPI  ->  Synthetic claim data

Phase 2 will insert LangGraph and the specialist agents between the API and the
data, and Phase 4 will insert the X-Verba/VSL gate immediately before each
governed side effect. The VSL spec's import rule -- app.py calls
governance.gates, never the model directly for a governed action -- is why this
module talks only to the service layer.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# FIRST, before any module reads os.environ. `.env` is not loaded by magic:
# every setting in this project is read with os.environ.get(), which sees only
# what the shell exported until this call runs.
from bootstrap import load_project_env

load_project_env()

from app.api import (  # noqa: E402
    assistant,
    claims,
    governance,
    health,
    intelligence,
    review,
)
from app.config import get_settings  # noqa: E402
from app.errors import ClaimsAppError
from app.schemas.claim import ErrorDetail

logger = logging.getLogger("claims")

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="AI Insurance Claims Agent - Claims API",
    version="0.1.0",
    description=(
        "POC API for Home Insurance / Storm Damage / First Notice of Loss.\n\n"
        "**Synthetic data only.** No real customer, policy or claim data.\n\n"
        "**Phase 1** lodges a claim and sets its state to Submitted.\n\n"
        "**Phase 2** runs a LangGraph multi-agent workflow over a submitted claim "
        "and returns a structured claims intelligence result.\n\n"
        "**Phase 3** routes that result: a claim needing a person moves to Human "
        "Review and appears in the review queue; a claim needing information moves "
        "to Information Required. Routing moves a claim towards a person — it never "
        "decides one. Nothing here approves, declines or settles a claim, and no "
        "customer is contacted.\n\n"
        "**Phase 4** enforces X-Verba/VSL governance at the commitment points. A "
        "PreNode and three Invariants run *before* the claim-state write, which is "
        "passed into the gate as a callable so no denial path can reach it. "
        "Decisions are recorded in a hash-chained VerbaLedger; `/api/governance` "
        "reports what was declared, what happened and whether it holds up.\n\n"
        "Derived assurance is **LOW** — output-layer control. The gates block a bad "
        "action; they do not change how the model decides."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(assistant.router)
app.include_router(claims.router)
app.include_router(intelligence.router)
app.include_router(review.router)
app.include_router(governance.router)


# --------------------------------------------------------------------------
# Error handling -- customers never see a Python exception or a stack trace
# --------------------------------------------------------------------------


@app.exception_handler(ClaimsAppError)
async def handle_app_error(_: Request, exc: ClaimsAppError) -> JSONResponse:
    logger.warning("Handled application error: %s", exc.__class__.__name__, exc_info=exc)
    return JSONResponse(
        status_code=exc.http_status,
        content=ErrorDetail(error=exc.code, message=exc.customer_message).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn Pydantic's field errors into per-field customer-safe messages."""
    fields: dict[str, str] = {}
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", []) if part != "body"]
        key = ".".join(location) or "form"
        fields[key] = _friendly_validation_message(error)

    return JSONResponse(
        status_code=422,
        content=ErrorDetail(
            error="invalid_claim_submission",
            message=(
                "Some of the claim details need attention before we can lodge "
                "your claim."
            ),
            fields=fields,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    """Last resort. Log the detail; tell the customer nothing technical."""
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorDetail(
            error="internal_error",
            message=(
                "Something went wrong at our end. Your claim has not been "
                "submitted. Please try again shortly."
            ),
        ).model_dump(),
    )


def _friendly_validation_message(error: dict) -> str:
    error_type = error.get("type", "")
    if error_type == "missing":
        return "This is required."
    if error_type in {"too_short", "string_too_short"}:
        return "Please provide a little more detail."
    if error_type == "too_long" or error_type == "string_too_long":
        return "This is longer than we can accept."
    if "email" in error_type:
        return "Please enter a valid email address."
    if error_type.startswith("date") or error_type.startswith("time"):
        return "Please enter a valid date."
    message = str(error.get("msg", "")).removeprefix("Value error, ").strip()
    return message or "Please check this value."
