"""The conversational assistant service.

Owns the conversation lifecycle and the one moment that matters:

    CLAIM CREATION HAPPENS IN EXACTLY ONE PLACE, ONCE, AFTER EXPLICIT
    CUSTOMER CONFIRMATION, THROUGH THE EXISTING `ClaimService`.

There is no second claim store, no second claim ID scheme and no second
workflow. `confirm()` builds an FNOL from collected values and hands it to the
same service the form-based journey uses, so a conversationally-lodged claim is
indistinguishable downstream -- the same claim record, the same states, the same
intelligence workflow, the same review queue, the same governance.

WHY CONFIRMATION IS A SEPARATE ENDPOINT

Because "the customer said yes" must not be something the assistant can decide
it heard. A message endpoint that created a claim when the model judged the
reply affirmative would make claim creation depend on a model reading the word
"yeah". `confirm()` is a distinct HTTP call the UI makes when the customer
presses a button, and it refuses if the conversation is not ready.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.errors import ClaimsAppError
from app.schemas.assistant import (
    AssistantTurn,
    ClaimCreated,
    ConversationView,
    CollectedItem,
    MissingItem,
    UncertainItem,
)
from app.services.claim_service import ClaimService
from conversation.builder import ConversationIncompleteError, claim_summary, to_submission
from conversation.contracts import ConversationStage, ConversationState
from conversation.fields import FIELDS_BY_NAME, progress
from conversation.store import ConversationRepository

logger = logging.getLogger("claims.assistant")

OPENING_MESSAGE = (
    "Hello! I'm your insurance claims assistant. Tell me what happened, and "
    "I'll help you report it."
)


class ConversationNotFoundError(ClaimsAppError):
    code = "conversation_not_found"
    http_status = 404
    customer_message = (
        "We could not find that conversation. Please start a new one and we will "
        "help you report your claim."
    )


class ConversationNotReadyError(ClaimsAppError):
    code = "conversation_not_ready"
    http_status = 409
    customer_message = (
        "There are still a few details we need before your claim can be "
        "submitted."
    )


class ClaimAlreadyCreatedError(ClaimsAppError):
    code = "claim_already_created"
    http_status = 409
    customer_message = (
        "This claim has already been submitted. You do not need to submit it "
        "again."
    )


class AssistantService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        claims: ClaimService,
        graph: Any,
    ) -> None:
        self._conversations = conversations
        self._claims = claims
        self._graph = graph

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> AssistantTurn:
        """Open a conversation. Nothing is asked yet -- the customer speaks first."""
        state = ConversationState(conversation_id=f"CNV-{uuid.uuid4().hex[:12].upper()}")
        state.add_message("assistant", OPENING_MESSAGE)
        state.missing_information = [
            name for name in FIELDS_BY_NAME if state.value(name) is None
        ]
        self._conversations.save(state)
        logger.info("assistant.conversation_started conversation_id=%s", state.conversation_id)
        return AssistantTurn(reply=OPENING_MESSAGE, conversation=self._view(state))

    def get(self, conversation_id: str) -> ConversationView:
        return self._view(self._load(conversation_id))

    # -- one turn ----------------------------------------------------------

    def send(self, conversation_id: str, message: str) -> AssistantTurn:
        """Run one customer message through the conversational graph."""
        state = self._load(conversation_id)

        if state.customer_confirmed:
            raise ClaimAlreadyCreatedError()

        state.add_message("customer", message)

        # What the assistant last asked about. Recorded here rather than read
        # back out of the model, so the deterministic path always knows which
        # field a bare reply like "yes" or "POL-HOME-20117" belongs to.
        asked_about = self._asked_about(state)

        result = self._graph.invoke(
            {
                "conversation_id": state.conversation_id,
                "message": message,
                "state": state,
                "asked_about": asked_about,
                "proposed": {},
                "proposed_uncertain": {},
                "accepted": {},
                "rejected": {},
                "trace": [],
            }
        )

        reply = result.get("reply") or ""
        state.add_message("assistant", reply)
        self._conversations.save(state)

        logger.info(
            "assistant.turn conversation_id=%s stage=%s accepted=%d missing=%d "
            "llm_called=%s",
            state.conversation_id,
            state.current_stage.value,
            len(result.get("accepted") or {}),
            len(result.get("missing") or []),
            (result.get("governance") or {}).get("llm_called"),
        )

        return AssistantTurn(
            reply=reply,
            conversation=self._view(state),
            governance=result.get("governance"),
        )

    # -- the commitment ----------------------------------------------------

    def confirm(self, conversation_id: str) -> ClaimCreated:
        """Create the claim. Reached ONLY by an explicit customer action.

        Three refusals before anything is created, in order: the claim already
        exists, the conversation is not ready, or the FNOL will not build. Only
        past all three does `ClaimService.submit_claim` run -- the same call the
        form-based journey makes.
        """
        state = self._load(conversation_id)

        if state.customer_confirmed and state.claim_id:
            raise ClaimAlreadyCreatedError()

        if not state.claim_ready:
            raise ConversationNotReadyError()

        try:
            submission = to_submission(state)
        except ConversationIncompleteError as exc:
            logger.warning(
                "assistant.confirm_refused conversation_id=%s missing=%s",
                conversation_id,
                exc.missing,
            )
            raise ConversationNotReadyError() from exc

        # THE side effect. One call, to the existing service.
        response = self._claims.submit_claim(submission)

        state.claim_id = response.claim_id
        state.customer_confirmed = True
        state.current_stage = ConversationStage.CLAIM_CREATED
        state.record(
            "customer_confirmed",
            True,
            source_text="customer confirmed the summary",
            source="customer_confirmation",
        )
        message = (
            f"Your claim has been created successfully.\n\nClaim ID: "
            f"{response.claim_id}\n\n{response.next_step}"
        )
        state.add_message("assistant", message)
        self._conversations.save(state)

        logger.info(
            "assistant.claim_created conversation_id=%s claim_id=%s",
            conversation_id,
            response.claim_id,
        )

        return ClaimCreated(
            claim_id=response.claim_id,
            claim_state=response.claim_state,
            submitted_at=response.submitted_at,
            message=message,
            conversation=self._view(state),
        )

    # -- internals ---------------------------------------------------------

    def _load(self, conversation_id: str) -> ConversationState:
        state = self._conversations.get(conversation_id)
        if state is None:
            raise ConversationNotFoundError()
        return state

    @staticmethod
    def _asked_about(state: ConversationState) -> str | None:
        """Which field the assistant's last question was about.

        Read from the state, where `respond_node` recorded it. It is NOT derived
        as "the next required field": on the opening turn the assistant has
        asked nothing while the next required field is `full_name`, so deriving
        it accepts "A storm damaged my roof last night" as the customer's name.
        A reply can only answer a question that was actually put.
        """
        return state.last_asked

    def _view(self, state: ConversationState) -> ConversationView:
        values = state.values()
        have, total = progress(values)
        return ConversationView(
            conversation_id=state.conversation_id,
            claim_id=state.claim_id,
            current_stage=state.current_stage,
            collected_information=[
                CollectedItem(
                    field=row["field"], label=row["label"], value=row["value"]
                )
                for row in claim_summary(state)
            ],
            missing_information=[
                MissingItem(
                    field=name,
                    label=FIELDS_BY_NAME[name].display(),
                    question=FIELDS_BY_NAME[name].question,
                )
                for name in state.missing_information
                if name in FIELDS_BY_NAME
            ],
            uncertain_information=[
                UncertainItem(
                    field=item.field,
                    label=FIELDS_BY_NAME[item.field].display()
                    if item.field in FIELDS_BY_NAME
                    else item.field,
                    said=item.said,
                    why=item.why,
                )
                for item in state.uncertain_information
            ],
            claim_ready=state.claim_ready,
            customer_confirmed=state.customer_confirmed,
            collected_count=have,
            required_count=total,
            messages=[
                {"role": m.role, "text": m.text, "at": m.at} for m in state.messages
            ],
        )
