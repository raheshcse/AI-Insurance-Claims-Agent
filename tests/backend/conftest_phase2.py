"""Phase 2 test fixtures.

Imported by conftest.py so Phase 1 fixtures stay untouched.

Every test runs against the deterministic stub LLM. No test depends on a live
model: the workflow's decisions are rule-derived by design, so a test that
needed a network call would be testing the wrong thing.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

import pytest

from agents.assessment import AssessmentAgent
from agents.fraud_risk import FraudRiskAgent
from agents.intake import IntakeAgent
from agents.policy import PolicyAgent
from agents.validation import ValidationAgent
from app.domain.thresholds import Thresholds
from app.repositories.reference_data import SyntheticReferenceData
from graph.builder import build_claims_graph
from llm.stub import StubLLMProvider

YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture
def llm() -> StubLLMProvider:
    return StubLLMProvider()


@pytest.fixture
def thresholds() -> Thresholds:
    return Thresholds()


@pytest.fixture
def reference_data() -> SyntheticReferenceData:
    """Reads the real synthetic datasets -- they are part of what Phase 2 delivers."""
    return SyntheticReferenceData()


@pytest.fixture
def submitted_claim() -> dict[str, Any]:
    """A straightforward storm claim on a clean, in-force policy."""
    return {
        "claim_id": "CLM-2026-000001",
        "policy_id": None,
        "customer_id": None,
        "claim_state": "Submitted",
        "internal_status": None,
        "created_at": f"{YESTERDAY}T09:00:00+00:00",
        "updated_at": f"{YESTERDAY}T09:00:00+00:00",
        "submitted_at": f"{YESTERDAY}T09:00:00+00:00",
        "source": "customer_portal",
        "synthetic": True,
        "fnol": {
            "customer": {
                "full_name": "Marama Whitcombe",
                "email": "m.whitcombe@example.invalid",
                "phone": "+64 20 900 0142",
                "policy_number": "POL-HOME-20117",
                "preferred_contact_method": "email",
            },
            "property": {
                "loss_address": {
                    "address_line_1": "18 Kauri Point Road",
                    "suburb": "Titirangi",
                    "city": "Auckland",
                    "postcode": "0604",
                },
                "property_habitable": True,
                "temporary_accommodation_needed": False,
            },
            "damage": {
                "date_of_loss": YESTERDAY,
                "time_of_loss": "21:30:00",
                "peril": "storm",
                "incident_description": (
                    "Overnight storm tore tiles off the north side of the roof and "
                    "water came through the ceiling in the back bedroom."
                ),
                "damaged_items": [
                    {
                        "area": "Roof",
                        "item": "Roof tiles",
                        "description": "Around fifteen tiles lifted and broken on the north slope.",
                        "estimated_value": 3200,
                    }
                ],
                "damage_ongoing": False,
                "anyone_injured": False,
                "utilities_affected": [],
                "emergency_repairs_done": True,
                "third_party_involved": False,
                "photos_supplied": True,
                "customer_estimated_value": 4200,
            },
        },
    }


@pytest.fixture
def claim_factory(submitted_claim):
    """Vary the baseline claim without mutating it."""

    def build(**overrides: Any) -> dict[str, Any]:
        claim = copy.deepcopy(submitted_claim)
        damage = claim["fnol"]["damage"]
        prop = claim["fnol"]["property"]
        customer = claim["fnol"]["customer"]

        if "policy_number" in overrides:
            customer["policy_number"] = overrides["policy_number"]
        if "loss_address" in overrides:
            prop["loss_address"] = overrides["loss_address"]
        if "habitable" in overrides:
            prop["property_habitable"] = overrides["habitable"]
        if "photos" in overrides:
            damage["photos_supplied"] = overrides["photos"]
        if "estimate" in overrides:
            damage["customer_estimated_value"] = overrides["estimate"]
        if "description" in overrides:
            damage["incident_description"] = overrides["description"]
        if "items" in overrides:
            damage["damaged_items"] = overrides["items"]
        if "injured" in overrides:
            damage["anyone_injured"] = overrides["injured"]
        if "date_of_loss" in overrides:
            damage["date_of_loss"] = overrides["date_of_loss"]
        if "claim_id" in overrides:
            claim["claim_id"] = overrides["claim_id"]
        if "utilities" in overrides:
            damage["utilities_affected"] = overrides["utilities"]
        if "ongoing" in overrides:
            damage["damage_ongoing"] = overrides["ongoing"]
        return claim

    return build


@pytest.fixture
def intake_agent(llm) -> IntakeAgent:
    return IntakeAgent(llm)


@pytest.fixture
def policy_agent(llm, reference_data) -> PolicyAgent:
    return PolicyAgent(llm, reference_data)


@pytest.fixture
def validation_agent(llm) -> ValidationAgent:
    return ValidationAgent(llm)


@pytest.fixture
def assessment_agent(llm, thresholds) -> AssessmentAgent:
    return AssessmentAgent(llm, thresholds)


@pytest.fixture
def risk_agent(llm, reference_data, thresholds) -> FraudRiskAgent:
    return FraudRiskAgent(llm, reference_data, thresholds)


@pytest.fixture
def review_client(claims_graph):
    """A fully-wired application whose claims, analyses and queue are in memory.

    Shared from Phase 4 onwards: the Phase 3 review tests and the Phase 4
    governance tests drive the *same* wiring, so a governance test cannot pass
    against an application assembled differently from the real one.
    """
    from fastapi.testclient import TestClient

    from app.api.dependencies import (
        get_claim_service,
        get_intelligence_service,
        get_review_service,
    )
    from app.main import app
    from app.repositories.analysis_repository import InMemoryAnalysisRepository
    from app.repositories.claim_repository import InMemoryClaimRepository
    from app.repositories.review_queue_repository import InMemoryReviewQueueRepository
    from app.services.claim_service import ClaimService
    from app.services.intelligence_service import ClaimIntelligenceService
    from app.services.review_service import ReviewService

    claims = InMemoryClaimRepository()
    analyses = InMemoryAnalysisRepository()
    queue = InMemoryReviewQueueRepository()
    reviews = ReviewService(claims=claims, queue=queue)

    app.dependency_overrides[get_claim_service] = lambda: ClaimService(claims)
    app.dependency_overrides[get_review_service] = lambda: reviews
    app.dependency_overrides[get_intelligence_service] = lambda: ClaimIntelligenceService(
        claims=claims,
        analyses=analyses,
        graph=claims_graph,
        reviews=reviews,
        llm_name="stub",
    )
    with TestClient(app) as client:
        yield client, claims, queue
    app.dependency_overrides.clear()


def run_graph(graph, claim: dict[str, Any]) -> dict[str, Any]:
    """Drive a compiled graph to completion from synchronous test code.

    Phase 4 put an async VSL gate in the graph, so `invoke` raises; `ainvoke` is
    the correct entry point and this drives the loop for tests that build their
    own graph rather than using the `run_workflow` fixture.
    """
    import asyncio

    from graph.state import initial_state

    return asyncio.run(graph.ainvoke(initial_state(claim)))


@pytest.fixture(scope="session")
def claims_graph():
    """Compiled once; the graph is stateless between runs."""
    return build_claims_graph(llm=StubLLMProvider())


@pytest.fixture
def run_workflow(claims_graph):
    """Run the graph to completion and hand back the intelligence result.

    `ainvoke`, not `invoke`, from Phase 4: the graph now contains a VSL gate
    whose PreNode monitor is a coroutine, and LangGraph's synchronous `invoke`
    would not await it. The loop is driven here so the tests themselves stay
    synchronous -- no existing test had to change shape to accommodate
    governance.
    """
    import asyncio

    from graph.state import initial_state

    def run(claim: dict[str, Any]) -> dict[str, Any]:
        final_state = asyncio.run(claims_graph.ainvoke(initial_state(claim)))
        return final_state["intelligence"]

    return run
