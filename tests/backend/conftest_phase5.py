"""Phase 5 test fixtures — the conversational assistant.

Two deliberate choices here.

**A counting provider, not a mock library.** Every governance test in this file
turns on one number: how many times the model was actually called. A spy that
can be satisfied by `assert_called()` would pass for code that calls the model
and then discards the answer, which is precisely the failure mode being tested.
`CountingProvider.calls` is the evidence.

**A real graph, not a stubbed one.** These tests build the actual LangGraph
StateGraph with the actual compiled VSL gates. A test that stubbed the gate
would prove the test's own arrangement, not the architecture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from agents.conversation import ConversationAgent
from app.repositories.claim_repository import InMemoryClaimRepository
from app.services.assistant_service import AssistantService
from app.services.claim_service import ClaimService
from conversation.store import InMemoryConversationRepository
from graph.conversation_graph import build_conversation_graph


@dataclass
class FakeNarration:
    """The shape every provider returns. Not a Mock -- a real value object."""

    text: str
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass
class CountingProvider:
    """A provider that records every call it receives.

    `calls` is what proves "the model was not called", which no assertion about
    a returned value can prove: a denied gate and a called-then-ignored model
    produce the same downstream result and differ only here.
    """

    reply: str = '{"extracted": {}, "uncertain": {}}'
    name: str = "gemini"
    model: str = "gemini-3.8-flash"
    calls: int = 0
    requests: list[Any] = field(default_factory=list)

    def narrate(self, request: Any) -> FakeNarration:
        self.calls += 1
        self.requests.append(request)
        return FakeNarration(self.reply)


def extraction(extracted: dict | None = None, uncertain: dict | None = None) -> str:
    """The JSON body a well-behaved model returns."""
    return json.dumps({"extracted": extracted or {}, "uncertain": uncertain or {}})


@pytest.fixture
def provider() -> CountingProvider:
    return CountingProvider()


@pytest.fixture
def conversation_repository() -> InMemoryConversationRepository:
    return InMemoryConversationRepository()


@pytest.fixture
def assistant_claims() -> InMemoryClaimRepository:
    """The claim store the assistant writes into -- the ORIGINAL one.

    Named for clarity in tests that assert "the claim landed in the same store
    the form-based journey uses". There is no second store to point at.
    """
    return InMemoryClaimRepository()


@pytest.fixture
def assistant(
    provider: CountingProvider,
    conversation_repository: InMemoryConversationRepository,
    assistant_claims: InMemoryClaimRepository,
) -> AssistantService:
    return AssistantService(
        conversations=conversation_repository,
        claims=ClaimService(assistant_claims),
        graph=build_conversation_graph(agent=ConversationAgent(provider)),
    )


ANSWERS: tuple[tuple[str, str], ...] = (
    ("full_name", "Marama Whitcombe"),
    ("email", "m.whitcombe@example.invalid"),
    ("phone", "+64 20 900 0142"),
    ("policy_number", "POL-HOME-20117"),
    ("date_of_loss", "2026-09-14"),
    (
        "incident_description",
        "Overnight storm tore tiles off the north side of the roof and water "
        "came through the ceiling in the back bedroom.",
    ),
    ("address_line_1", "18 Kauri Point Road"),
    ("suburb", "Titirangi"),
    ("city", "Auckland"),
    ("postcode", "0604"),
    ("damaged_areas", "roof and ceiling"),
    ("estimated_damage_value", "$7,500"),
    ("photos_supplied", "yes"),
    ("property_habitable", "yes"),
    ("anyone_injured", "no"),
    ("damage_ongoing", "no"),
    ("emergency_repairs_done", "yes"),
    ("temporary_accommodation_needed", "no"),
)
"""One reply per required field, in catalogue order.

Plain answers to plain questions, so a complete conversation can be driven with
NO model at all -- which is also the point being demonstrated: the assistant
works when Gemini is unavailable, denied or degraded.
"""


@pytest.fixture
def complete_conversation(assistant: AssistantService):
    """Drive a conversation to `claim_ready` and return its id. No claim yet."""

    def run() -> str:
        turn = assistant.start()
        conversation_id = turn.conversation.conversation_id

        # The customer speaks first, in their own words.
        turn = assistant.send(
            conversation_id, "A storm damaged my roof and ceiling last night."
        )

        # Then ANSWER WHAT IS ASKED, rather than replaying a fixed script.
        #
        # The fixture used to send `ANSWERS` positionally, which quietly assumed
        # the assistant collects one field per turn in catalogue order. It does
        # not any more: deterministic extraction can fill several fields from
        # one sentence, including from the opening message, so a positional
        # script drifts out of step and starts feeding answers to the wrong
        # questions. Reading the next missing field is both more robust and
        # closer to what a customer actually does.
        answers = dict(ANSWERS)
        for _ in range(len(ANSWERS) + 5):
            if turn.conversation.claim_ready:
                break
            pending = turn.conversation.missing_information[0].field
            assert pending in answers, f"the fixture has no answer for {pending}"
            turn = assistant.send(conversation_id, answers[pending])

        assert turn.conversation.claim_ready, (
            "the fixture must reach readiness; missing: "
            f"{[m.field for m in turn.conversation.missing_information]}"
        )
        assert turn.conversation.claim_id is None, "no claim before confirmation"
        return conversation_id

    return run
