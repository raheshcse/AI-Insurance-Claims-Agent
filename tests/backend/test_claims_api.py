"""Phase 1 backend tests — claim submission.

Covers the Phase 1 exit criteria: a valid FNOL is accepted, an incomplete one is
rejected with customer-safe messages, a claim ID is generated, the initial state
is Submitted, and the response shape is what the frontend expects.
"""

from __future__ import annotations

import copy
import re
from datetime import date, timedelta

CLAIM_ID_PATTERN = re.compile(r"^CLM-\d{4}-\d{6}$")


# ---------------------------------------------------------------- happy path


def test_valid_submission_returns_201(client, valid_fnol):
    response = client.post("/api/claims", json=valid_fnol)
    assert response.status_code == 201


def test_claim_id_is_generated_in_the_expected_format(client, valid_fnol):
    body = client.post("/api/claims", json=valid_fnol).json()
    assert CLAIM_ID_PATTERN.match(body["claim_id"]), body["claim_id"]


def test_initial_claim_state_is_submitted(client, valid_fnol):
    body = client.post("/api/claims", json=valid_fnol).json()
    assert body["claim_state"] == "Submitted"


def test_claim_is_not_moved_into_assessment(client, valid_fnol):
    """Phase 1 stops at Submitted. Assessment is Phase 2."""
    body = client.post("/api/claims", json=valid_fnol).json()
    assert body["claim_state"] != "Assessment"
    assert body["internal_status"] is None


def test_response_structure(client, valid_fnol):
    body = client.post("/api/claims", json=valid_fnol).json()
    assert set(body) == {
        "claim_id",
        "claim_state",
        "internal_status",
        "submitted_at",
        "next_step",
        "summary",
    }
    assert set(body["summary"]) == {
        "policy_number",
        "customer_name",
        "peril",
        "date_of_loss",
        "loss_address",
        "damaged_item_count",
        "customer_estimated_value",
    }
    assert body["summary"]["policy_number"] == "POL-HOME-20117"
    assert body["summary"]["damaged_item_count"] == 1
    assert body["summary"]["loss_address"].startswith("18 Kauri Point Road")


def test_claim_record_is_persisted_and_readable(client, valid_fnol, repository):
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    stored = repository.get(claim_id)
    assert stored is not None
    assert stored["claim_state"] == "Submitted"
    assert stored["synthetic"] is True
    assert stored["source"] == "customer_portal"
    # Nothing has assessed the claim.
    for derived in ("classification", "complexity_band", "confidence", "risk_level"):
        assert derived not in stored

    response = client.get(f"/api/claims/{claim_id}")
    assert response.status_code == 200
    assert response.json()["claim_id"] == claim_id


def test_claim_ids_are_unique_across_submissions(client, valid_fnol):
    ids = {client.post("/api/claims", json=valid_fnol).json()["claim_id"] for _ in range(5)}
    assert len(ids) == 5


# ------------------------------------------------------------ invalid inputs


def test_missing_required_field_is_rejected(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    del payload["customer"]["policy_number"]

    response = client.post("/api/claims", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_claim_submission"
    assert "customer.policy_number" in body["fields"]
    assert body["fields"]["customer.policy_number"] == "This is required."


def test_empty_submission_is_rejected(client):
    response = client.post("/api/claims", json={})
    assert response.status_code == 422
    assert response.json()["fields"]


def test_invalid_email_is_rejected(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    payload["customer"]["email"] = "not-an-email"

    response = client.post("/api/claims", json=payload)

    assert response.status_code == 422
    assert "customer.email" in response.json()["fields"]


def test_claim_with_no_damaged_items_is_rejected(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    payload["damage"]["damaged_items"] = []

    response = client.post("/api/claims", json=payload)

    assert response.status_code == 422
    assert "damage.damaged_items" in response.json()["fields"]


def test_future_date_of_loss_is_rejected(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    payload["damage"]["date_of_loss"] = (date.today() + timedelta(days=3)).isoformat()

    response = client.post("/api/claims", json=payload)

    assert response.status_code == 422
    assert "future" in response.json()["fields"]["damage.date_of_loss"].lower()


def test_too_short_description_is_rejected(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    payload["damage"]["incident_description"] = "Storm."

    response = client.post("/api/claims", json=payload)

    assert response.status_code == 422
    assert "damage.incident_description" in response.json()["fields"]


def test_rejected_submission_creates_no_claim(client, valid_fnol, repository):
    payload = copy.deepcopy(valid_fnol)
    del payload["damage"]["date_of_loss"]

    client.post("/api/claims", json=payload)

    assert repository._claims == {}


def test_errors_never_leak_internal_detail(client, valid_fnol):
    payload = copy.deepcopy(valid_fnol)
    del payload["customer"]["email"]

    body = client.post("/api/claims", json=payload).json()
    serialised = str(body).lower()

    for leak in ("traceback", "pydantic", "app.", "file \"", "valueerror"):
        assert leak not in serialised


# ------------------------------------------------------------------- lookups


def test_unknown_claim_returns_customer_safe_404(client):
    response = client.get("/api/claims/CLM-2026-999999")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "claim_not_found"
    assert body["message"] == "We could not find a claim with that reference."


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
