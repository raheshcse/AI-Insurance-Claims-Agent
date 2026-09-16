"""Phase 3 — the human review queue API and claim-state transitions."""

from __future__ import annotations

import pytest

# `review_client` moved to conftest_phase2 in Phase 4, so the governance tests
# drive the same fully-wired application rather than standing up a second one
# that could drift from it. Nothing about the fixture itself changed.


def _lodge(client, fnol) -> str:
    response = client.post("/api/claims", json=fnol)
    assert response.status_code == 201
    return response.json()["claim_id"]


def _escalating_fnol(valid_fnol: dict) -> dict:
    """A claim the routing rules will send to a person: no photographs plus an
    unsafe property, which is the emergency pathway."""
    import copy

    fnol = copy.deepcopy(valid_fnol)
    fnol["property"]["property_habitable"] = False
    return fnol


# ------------------------------------------------- routing applies the state


def test_escalating_claim_moves_to_human_review_and_is_queued(
    review_client, valid_fnol
):
    client, claims, queue = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))

    assert claims.get(claim_id)["claim_state"] == "Submitted"

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["routing"]["outcome"] == "HUMAN_REVIEW_REQUIRED"
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert body["claim_state_changed"] is True
    assert body["routing_applied"] is True
    assert queue.get(claim_id) is not None


def test_information_required_claim_moves_to_information_required(
    review_client, valid_fnol
):
    import copy

    client, claims, queue = review_client
    fnol = copy.deepcopy(valid_fnol)
    fnol["damage"]["photos_supplied"] = False
    claim_id = _lodge(client, fnol)

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["routing"]["outcome"] == "INFORMATION_REQUIRED"
    assert claims.get(claim_id)["claim_state"] == "Information Required"
    # Not a review job -- the customer holds the claim, not a reviewer.
    assert queue.get(claim_id) is None


def test_automated_path_claim_moves_to_assessment_not_completed(
    review_client, valid_fnol
):
    client, claims, queue = review_client
    claim_id = _lodge(client, valid_fnol)

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["routing"]["outcome"] == "AUTOMATED_PATH_RECOMMENDED"
    assert claims.get(claim_id)["claim_state"] == "Assessment"
    # Never straight to Approved/Completed.
    assert claims.get(claim_id)["claim_state"] != "Approved/Completed"
    assert queue.get(claim_id) is None


def test_routing_never_settles_approves_or_declines(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["is_recommendation_only"] is True
    assert body["action_taken"] == "none"
    assert body["routing"]["decision_authority"] == "business_rules"
    assert "never decides" in body["boundary_note"]


# ------------------------------------------------------------ the queue


def test_queue_lists_the_escalated_claim_with_its_reasons(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = client.get("/api/review-queue").json()

    assert body["total"] == 1
    assert body["open_count"] == 1
    assert body["urgent_count"] == 1

    entry = body["entries"][0]
    assert entry["claim_id"] == claim_id
    assert entry["priority"] == "urgent"
    assert entry["review_type"] == "priority_review"
    assert entry["primary_reason_code"] == "E-11_EMERGENCY"
    assert entry["reason_count"] >= 1
    assert entry["customer_name"] == "Marama Whitcombe"
    assert entry["claim_state"] == "Human Review"


def test_queue_puts_urgent_claims_first(review_client, valid_fnol):
    import copy

    client, _, _ = review_client

    standard = copy.deepcopy(valid_fnol)
    standard["damage"]["customer_estimated_value"] = 14_000
    standard_id = _lodge(client, standard)
    client.post(f"/api/claims/{standard_id}/analyze")

    urgent_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{urgent_id}/analyze")

    entries = client.get("/api/review-queue").json()["entries"]

    assert [e["claim_id"] for e in entries][0] == urgent_id
    assert entries[0]["priority"] == "urgent"


def test_queue_can_be_filtered(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    assert client.get("/api/review-queue?status=open").json()["total"] == 1
    assert client.get("/api/review-queue?status=closed").json()["total"] == 0
    assert client.get("/api/review-queue?priority=urgent").json()["total"] == 1
    assert client.get("/api/review-queue?priority=standard").json()["total"] == 0


def test_reanalysis_updates_the_entry_rather_than_duplicating_it(
    review_client, valid_fnol
):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))

    client.post(f"/api/claims/{claim_id}/analyze")
    first = client.get("/api/review-queue").json()["entries"][0]["queue_id"]

    client.post(f"/api/claims/{claim_id}/analyze", json={"force_reanalysis": True})
    body = client.get("/api/review-queue").json()

    assert body["total"] == 1
    assert body["entries"][0]["queue_id"] == first


# ------------------------------------------------------- review detail


def test_review_detail_answers_the_six_reviewer_questions(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = client.get(f"/api/review-queue/{claim_id}").json()

    # 1. what the customer reported
    assert body["customer_report"]["damage"]["peril"] == "storm"
    # 2. policy, 3. agent findings, 4. risk, 6. recommendation
    assert body["intelligence"]["policy_assessment"] is not None
    assert set(body["intelligence"]["agent_results"]) >= {"intake", "policy"}
    assert body["intelligence"]["risk_assessment"] is not None
    assert body["intelligence"]["recommended_next_step"]
    # 5. why it was escalated
    assert body["queue_entry"]["reasons"]
    assert body["queue_entry"]["explanation"]
    # and the boundary between AI and human
    assert "recommendation" in body["decision_authority_note"]
    assert body["available_actions"]


def test_review_detail_flags_the_emergency_pathway(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    entry = client.get(f"/api/review-queue/{claim_id}").json()["queue_entry"]
    assert entry["emergency"] is True


def test_vulnerable_customer_is_flagged_on_the_queue_entry(review_client, valid_fnol):
    import copy

    client, _, _ = review_client
    fnol = copy.deepcopy(valid_fnol)
    fnol["customer"]["policy_number"] = "POL-HOME-20233"
    fnol["property"]["loss_address"] = {
        "address_line_1": "7 Rangiora Avenue",
        "suburb": "Kaiapoi",
        "city": "Christchurch",
        "postcode": "7630",
    }
    claim_id = _lodge(client, fnol)
    client.post(f"/api/claims/{claim_id}/analyze")

    entry = client.get(f"/api/review-queue/{claim_id}").json()["queue_entry"]
    assert entry["vulnerable_customer"] is True
    assert any(r["code"] == "E-12_VULNERABLE_CUSTOMER" for r in entry["reasons"])


# ------------------------------------------------------- review actions


def _act(client, claim_id, action, **kwargs):
    return client.post(
        f"/api/review-queue/{claim_id}/action",
        json={"action": action, "reviewer": "A. Reviewer", **kwargs},
    )


def test_start_review_assigns_without_changing_the_claim_state(
    review_client, valid_fnol
):
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = _act(client, claim_id, "start_review").json()

    assert body["queue_status"] == "in_review"
    assert body["claim_state"] == "Human Review"
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert body["decision_source"] == "human"


def test_request_information_moves_the_claim_and_closes_the_entry(
    review_client, valid_fnol
):
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = _act(
        client,
        claim_id,
        "request_information",
        information_requested=["Photographs of the roof"],
    ).json()

    assert body["claim_state"] == "Information Required"
    assert body["queue_status"] == "closed"
    assert claims.get(claim_id)["claim_state"] == "Information Required"


def test_refer_to_specialist_keeps_the_claim_in_human_review(review_client, valid_fnol):
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = _act(client, claim_id, "refer_to_specialist", notes="Needs a closer look").json()

    assert body["claim_state"] == "Human Review"
    assert body["internal_status"] == "specialist_referral"
    assert claims.get(claim_id)["internal_status"] == "specialist_referral"
    entry = client.get(f"/api/review-queue/{claim_id}").json()["queue_entry"]
    assert entry["review_type"] == "specialist_review"


def test_complete_review_is_a_human_decision_and_is_labelled_poc(
    review_client, valid_fnol
):
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    body = _act(client, claim_id, "complete_review", notes="Reviewed, progressing").json()

    assert body["claim_state"] == "Approved/Completed"
    assert body["decision_source"] == "human"
    assert "does not approve a claim for payment" in body["poc_note"]
    assert claims.get(claim_id)["claim_state"] == "Approved/Completed"


def test_only_a_human_action_can_reach_approved_completed(review_client, valid_fnol):
    """Routing can never produce Approved/Completed; a reviewer can."""
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))

    client.post(f"/api/claims/{claim_id}/analyze")
    assert claims.get(claim_id)["claim_state"] != "Approved/Completed"

    _act(client, claim_id, "complete_review")
    assert claims.get(claim_id)["claim_state"] == "Approved/Completed"


def test_review_actions_are_recorded_in_the_entry_history(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    _act(client, claim_id, "start_review", notes="Picking this up")
    _act(client, claim_id, "refer_to_specialist", notes="Risk indicators")

    history = client.get(f"/api/review-queue/{claim_id}").json()["queue_entry"]["history"]

    assert [h["action"] for h in history] == ["start_review", "refer_to_specialist"]
    assert all(h["decision_source"] == "human" for h in history)
    assert all(h["reviewer"] == "A. Reviewer" for h in history)


def test_an_action_not_available_is_refused_not_forced(review_client, valid_fnol):
    client, claims, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")
    _act(client, claim_id, "complete_review")  # closes the entry

    response = _act(client, claim_id, "start_review")

    assert response.status_code == 409
    assert response.json()["error"] == "invalid_review_action"
    assert claims.get(claim_id)["claim_state"] == "Approved/Completed"


def test_a_reviewer_name_is_required(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, _escalating_fnol(valid_fnol))
    client.post(f"/api/claims/{claim_id}/analyze")

    response = client.post(
        f"/api/review-queue/{claim_id}/action",
        json={"action": "complete_review", "reviewer": ""},
    )
    assert response.status_code == 422


# ------------------------------------------------------------- errors


def test_unknown_claim_returns_a_customer_safe_404(review_client):
    client, _, _ = review_client

    response = client.get("/api/review-queue/CLM-2026-999999")

    assert response.status_code == 404
    assert response.json()["error"] == "claim_not_found"


def test_action_on_a_claim_not_in_the_queue_returns_404(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = _lodge(client, valid_fnol)
    client.post(f"/api/claims/{claim_id}/analyze")  # automated path -- not queued

    response = _act(client, claim_id, "start_review")

    assert response.status_code == 404
    assert response.json()["error"] == "review_entry_not_found"


def test_errors_never_leak_internal_detail(review_client):
    client, _, _ = review_client
    body = client.get("/api/review-queue/CLM-2026-999999").json()

    for leak in ("traceback", "app.", "file \"", "keyerror"):
        assert leak not in str(body).lower()


def test_openapi_documents_the_review_endpoints(review_client):
    client, _, _ = review_client
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/review-queue" in paths
    assert "/api/review-queue/{claim_id}" in paths
    assert "/api/review-queue/{claim_id}/action" in paths
