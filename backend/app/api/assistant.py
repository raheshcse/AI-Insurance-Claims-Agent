"""The conversational assistant endpoints.

    POST /api/assistant/conversations                       start
    POST /api/assistant/conversations/{id}/messages         one customer turn
    GET  /api/assistant/conversations/{id}                  read the state back
    POST /api/assistant/conversations/{id}/confirm          create the claim

Four endpoints, and the fourth is the only one that creates anything. That
separation is the design: a message endpoint cannot lodge a claim however the
conversation goes, so "no claim before explicit confirmation" is a property of
the routing table rather than of a condition somewhere inside a handler.

Claim creation reuses `POST /api/claims`'s own service — there is no second
claim workflow and no second store.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_assistant_service
from app.errors import ClaimsAppError
from app.schemas.assistant import (
    AssistantTurn,
    ClaimCreated,
    ConfirmRequest,
    ConversationView,
    CustomerMessageRequest,
    StartConversationRequest,
)
from app.schemas.claim import ErrorDetail
from app.services.assistant_service import AssistantService

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

ServiceDep = Annotated[AssistantService, Depends(get_assistant_service)]


class ConfirmationRequiredError(ClaimsAppError):
    code = "confirmation_required"
    http_status = 400
    customer_message = (
        "Your claim has not been submitted. Please confirm the summary if the "
        "details are correct."
    )


@router.post(
    "/conversations",
    response_model=AssistantTurn,
    status_code=status.HTTP_201_CREATED,
    summary="Start a claims conversation",
)
def start_conversation(
    _: StartConversationRequest, service: ServiceDep
) -> AssistantTurn:
    """Open a conversation and return the assistant's opening message.

    Creates no claim and collects nothing. The customer speaks first.
    """
    return service.start()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AssistantTurn,
    summary="Send one customer message",
    responses={
        404: {"model": ErrorDetail, "description": "No such conversation"},
        409: {"model": ErrorDetail, "description": "The claim has already been created"},
    },
)
def send_message(
    conversation_id: str, payload: CustomerMessageRequest, service: ServiceDep
) -> AssistantTurn:
    """Run one message through the conversational workflow.

    **This endpoint never creates a claim**, whatever the customer says and
    whatever the model extracts. Creation lives behind `/confirm`.
    """
    return service.send(conversation_id, payload.message)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationView,
    summary="Read a conversation back",
    responses={404: {"model": ErrorDetail, "description": "No such conversation"}},
)
def get_conversation(conversation_id: str, service: ServiceDep) -> ConversationView:
    """The structured state: collected, missing, uncertain, stage, readiness."""
    return service.get(conversation_id)


@router.post(
    "/conversations/{conversation_id}/confirm",
    response_model=ClaimCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm the summary and create the claim",
    responses={
        400: {"model": ErrorDetail, "description": "Confirmation was not given"},
        404: {"model": ErrorDetail, "description": "No such conversation"},
        409: {
            "model": ErrorDetail,
            "description": "Not ready, or the claim already exists",
        },
    },
)
def confirm_conversation(
    conversation_id: str, payload: ConfirmRequest, service: ServiceDep
) -> ClaimCreated:
    """Create the claim through the existing claim workflow.

    Refuses unless `confirmed` is true and every required detail is collected.
    Returns the REAL claim ID — the same reference the form-based journey
    produces, from the same service.
    """
    if not payload.confirmed:
        raise ConfirmationRequiredError()
    return service.confirm(conversation_id)
