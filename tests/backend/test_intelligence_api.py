"""Phase 2 — the claims intelligence API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_claim_service, get_intelligence_service
from app.main import app
from app.repositories.analysis_repository import InMemoryAnalysisRepository
from app.repositories.claim_repository import InMemoryClaimRepository
from app.services.claim_service import ClaimService
from app.services.intelligence_service import ClaimIntelligenceService


@pytest.fixture
def analyses() -> InMemoryAnalysisRepository:
    return InMemoryAnalysisRepository()


@pytest.fixture
def intelligence_client(claims_graph, analyses):
    """A client whose claims and analyses both live in memory."""
    claims = InMemoryClaimRepository()

    app.dependency_overrides[get_claim_service] = lambda: ClaimService(claims)
    app.dependency_overrides[get_intelligence_service] = lambda: ClaimIntelligenceService(
        claims=claims, analyses=analyses, graph=claims_graph, llm_name="stub"
    )
    with TestClient(app) as client:
        yield client, claims
    app.dependency_overrides.clear()


def _lodge(client, valid_fnol) -> str:
    response = client.post("/api/claims", json=valid_fnol)
    assert response.status_code == 201
    return response.json()["claim_id"]


def test_analyse_returns_a_structured_result(intelligence_client, valid_fnol):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)

    response = client.post(f"/api/claims/{claim_id}/analyze")

    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == claim_id
    assert set(body["agent_results"]) == {
        "intake",
        "policy",
        "validation",
        "assessment",
        "fraud_risk",
    }
    assert body["recommended_next_step"]
    assert body["overall_confidence"]["value"] > 0


def test_analysis_does_not_change_the_claim(intelligence_client, valid_fnol):
    client, claims = intelligence_client
    claim_id = _lodge(client, valid_fnol)
    before = claims.get(claim_id)

    client.post(f"/api/claims/{claim_id}/analyze")

    after = claims.get(claim_id)
    assert after == before
    assert after["claim_state"] == "Submitted"
    assert after["internal_status"] is None


def test_response_states_the_recommendation_boundary(intelligence_client, valid_fnol):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["is_recommendation_only"] is True
    assert body["action_taken"] == "none"
    assert body["claim_state_changed"] is False
    assert "no customer has been contacted" in body["boundary_note"]


def test_analysis_is_stored_and_reused(intelligence_client, valid_fnol, analyses):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)

    first = client.post(f"/api/claims/{claim_id}/analyze").json()
    second = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert first["analysis_id"] == second["analysis_id"]
    assert len(analyses.all_for_claim(claim_id)) == 1


def test_force_reanalysis_runs_again(intelligence_client, valid_fnol, analyses):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)

    first = client.post(f"/api/claims/{claim_id}/analyze").json()
    second = client.post(
        f"/api/claims/{claim_id}/analyze", json={"force_reanalysis": True}
    ).json()

    assert first["analysis_id"] != second["analysis_id"]
    assert len(analyses.all_for_claim(claim_id)) == 2


def test_stored_analysis_can_be_read_back(intelligence_client, valid_fnol):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)
    created = client.post(f"/api/claims/{claim_id}/analyze").json()

    response = client.get(f"/api/claims/{claim_id}/analysis")

    assert response.status_code == 200
    assert response.json()["analysis_id"] == created["analysis_id"]


def test_analysing_an_unknown_claim_is_a_customer_safe_404(intelligence_client):
    client, _ = intelligence_client

    response = client.post("/api/claims/CLM-2026-999999/analyze")

    assert response.status_code == 404
    assert response.json()["error"] == "claim_not_found"


def test_reading_an_analysis_that_does_not_exist(intelligence_client, valid_fnol):
    client, _ = intelligence_client
    claim_id = _lodge(client, valid_fnol)

    response = client.get(f"/api/claims/{claim_id}/analysis")

    assert response.status_code == 404
    assert response.json()["error"] == "analysis_not_found"


def test_a_workflow_crash_is_reported_safely(claims_graph, valid_fnol, analyses):
    """A broken graph must not leak internals, and must say nothing changed."""
    claims = InMemoryClaimRepository()

    class BrokenGraph:
        def invoke(self, _state):  # noqa: ANN001, ANN202
            raise RuntimeError("graph exploded")

    app.dependency_overrides[get_claim_service] = lambda: ClaimService(claims)
    app.dependency_overrides[get_intelligence_service] = lambda: ClaimIntelligenceService(
        claims=claims, analyses=analyses, graph=BrokenGraph(), llm_name="stub"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            claim_id = _lodge(client, valid_fnol)
            response = client.post(f"/api/claims/{claim_id}/analyze")

            assert response.status_code == 503
            body = response.json()
            assert body["error"] == "claim_analysis_failed"
            assert "Nothing about the claim has changed" in body["message"]
            for leak in ("traceback", "graph exploded", "runtimeerror"):
                assert leak not in str(body).lower()

            assert claims.get(claim_id)["claim_state"] == "Submitted"
    finally:
        app.dependency_overrides.clear()


def test_openapi_documents_the_analyze_endpoint(intelligence_client):
    client, _ = intelligence_client
    schema = client.get("/openapi.json").json()

    assert "/api/claims/{claim_id}/analyze" in schema["paths"]
    assert "post" in schema["paths"]["/api/claims/{claim_id}/analyze"]
