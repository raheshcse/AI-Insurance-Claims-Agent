"""Phase 2 — individual agent behaviour.

Each agent is tested on its own, against the real synthetic datasets and the
deterministic stub LLM.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from agents.contracts import AgentStatus


def context_for(claim, **payloads):
    return {"claim_id": claim["claim_id"], "claim": claim, **payloads}


# ------------------------------------------------------------------ intake


def test_intake_structures_the_claim(intake_agent, submitted_claim):
    result, payload = intake_agent.run(context_for(submitted_claim))

    assert result.status is AgentStatus.COMPLETE
    assert result.agent == "intake"
    assert payload["peril"] == "storm"
    assert payload["damaged_item_count"] == 1
    assert payload["damage_areas"] == ["Roof"]
    assert payload["itemised_estimate_total"] == 3200
    assert payload["customer_estimated_value"] == 4200
    assert payload["missing_information"] == []


def test_intake_notes_missing_supporting_information(intake_agent, claim_factory):
    _, payload = intake_agent.run(context_for(claim_factory(photos=False)))
    assert "photographs of the damage" in payload["missing_information"]


def test_intake_records_urgency_signals_without_acting_on_them(intake_agent, claim_factory):
    result, payload = intake_agent.run(
        context_for(claim_factory(habitable=False, injured=True))
    )

    assert len(payload["urgency_signals"]) >= 2
    # Observed, never routed on -- routing is Phase 3.
    assert result.next_step in {"policy_retrieval", "information_required"}


def test_intake_never_recommends_an_action(intake_agent, submitted_claim):
    result, _ = intake_agent.run(context_for(submitted_claim))
    assert result.is_recommendation_only is True
    for word in ("approve", "settle", "decline", "pay"):
        assert word not in result.recommendation.lower()


# ------------------------------------------------------------------ policy


def test_policy_agent_retrieves_and_separates_facts_from_interpretation(
    policy_agent, submitted_claim
):
    result, payload = policy_agent.run(context_for(submitted_claim))

    assert result.status is AgentStatus.COMPLETE
    assert payload["facts"]["policy_id"] == "POL-HOME-20117"
    assert payload["facts"]["policy_status"] == "active"

    interpretation = payload["interpretation"]
    assert interpretation["policy_found"] is True
    assert interpretation["in_force_at_date_of_loss"] is True
    assert interpretation["peril_covered"] is True
    assert interpretation["cover_certainty"] == "clear"
    assert interpretation["applicable_excess"] == 1000  # storm excess, not standard
    assert "not a cover decision" in interpretation["caveat"].lower()


def test_policy_agent_reports_a_missing_policy(policy_agent, claim_factory):
    result, payload = policy_agent.run(
        context_for(claim_factory(policy_number="POL-HOME-99999"))
    )

    assert result.status is AgentStatus.INCOMPLETE
    assert payload["interpretation"]["policy_found"] is False
    assert any(f.code == "POLICY_NOT_FOUND" for f in result.findings)
    assert result.next_step == "manual_review"


def test_policy_agent_detects_cover_that_was_not_in_force(policy_agent, claim_factory):
    claim = claim_factory(
        policy_number="POL-HOME-20233",
        loss_address={
            "address_line_1": "7 Rangiora Avenue",
            "suburb": "Kaiapoi",
            "city": "Christchurch",
            "postcode": "7630",
        },
    )
    result, payload = policy_agent.run(context_for(claim))

    assert payload["interpretation"]["in_force_at_date_of_loss"] is False
    assert payload["interpretation"]["cover_certainty"] == "no_cover_basis"
    assert any(f.code == "POLICY_NOT_IN_FORCE" for f in result.findings)


def test_policy_agent_flags_a_possible_exclusion_without_deciding_it(
    policy_agent, claim_factory
):
    claim = claim_factory(
        policy_number="POL-HOME-20455",
        loss_address={
            "address_line_1": "55 Otumoetai Road",
            "suburb": "Otumoetai",
            "city": "Tauranga",
            "postcode": "3110",
        },
        description=(
            "The storm lifted tiles from the roof, which was already worn and due "
            "for replacement, and water came in through the ceiling."
        ),
    )
    result, payload = policy_agent.run(context_for(claim))

    assert payload["interpretation"]["exclusions_possibly_engaged"]
    assert payload["interpretation"]["cover_certainty"] == "uncertain"

    finding = next(f for f in result.findings if f.code == "EXCLUSION_POSSIBLY_ENGAGED")
    assert "not a cover determination" in (finding.detail or "")


def test_policy_agent_detects_an_address_mismatch(policy_agent, claim_factory):
    claim = claim_factory(
        loss_address={
            "address_line_1": "99 Somewhere Else Road",
            "suburb": "Ponsonby",
            "city": "Auckland",
            "postcode": "1011",
        }
    )
    _, payload = policy_agent.run(context_for(claim))
    assert payload["interpretation"]["address_matches_insured_address"] is False


# -------------------------------------------------------------- validation


def test_validation_passes_a_complete_claim(
    validation_agent, policy_agent, intake_agent, submitted_claim
):
    _, intake = intake_agent.run(context_for(submitted_claim))
    _, policy = policy_agent.run(context_for(submitted_claim))

    result, payload = validation_agent.run(
        context_for(submitted_claim, intake_payload=intake, policy_payload=policy)
    )

    assert payload["validation_status"] == "complete"
    assert payload["missing_information"] == []
    assert payload["inconsistencies"] == []
    assert result.next_step == "assessment"


def test_validation_requires_outstanding_information(
    validation_agent, policy_agent, intake_agent, claim_factory
):
    claim = claim_factory(photos=False)
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))

    _, payload = validation_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )

    assert payload["validation_status"] == "information_required"
    assert "photographs of the damage" in payload["missing_information"]


def test_validation_reports_an_inconsistent_estimate(
    validation_agent, policy_agent, intake_agent, claim_factory
):
    claim = claim_factory(estimate=500)  # below the itemised 3200
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))

    _, payload = validation_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )

    assert payload["validation_status"] == "inconsistent"
    assert payload["inconsistencies"]


def test_validation_never_rejects_or_approves(
    validation_agent, policy_agent, intake_agent, claim_factory
):
    claim = claim_factory(estimate=500)
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))
    result, _ = validation_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )

    lowered = result.recommendation.lower()
    for word in ("rejected", "approved", "declined", "denied"):
        assert word not in lowered


# -------------------------------------------------------------- assessment


def _assessed(assessment_agent, intake_agent, policy_agent, validation_agent, claim):
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))
    _, validation = validation_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )
    return assessment_agent.run(
        context_for(
            claim,
            intake_payload=intake,
            policy_payload=policy,
            validation_payload=validation,
        )
    )


def test_assessment_bands_a_straightforward_claim_as_low_complexity(
    assessment_agent, intake_agent, policy_agent, validation_agent, submitted_claim
):
    result, payload = _assessed(
        assessment_agent, intake_agent, policy_agent, validation_agent, submitted_claim
    )

    assert payload["complexity_band"] == "low"
    assert payload["value_band"] == "low_value"
    assert payload["incident_category"] == "roof_damage"
    assert payload["estimated_claim_value"] == 4200
    assert payload["net_of_excess_estimate"] == 3200  # 4200 less the 1000 storm excess
    assert result.status is AgentStatus.COMPLETE


def test_assessment_flags_a_value_above_the_proposed_authority_limit(
    assessment_agent, intake_agent, policy_agent, validation_agent, claim_factory
):
    claim = claim_factory(estimate=42_000)
    result, payload = _assessed(
        assessment_agent, intake_agent, policy_agent, validation_agent, claim
    )

    assert payload["value_band"] == "above_automated_authority"
    finding = next(f for f in result.findings if f.code == "ABOVE_AUTOMATED_AUTHORITY")
    # The distinction between a POC proposal and an insurer rule must survive.
    assert finding.assumption is not None
    assert "Phase 4" in (finding.detail or "")


def test_assessment_treats_an_unknown_value_conservatively(
    assessment_agent, intake_agent, policy_agent, validation_agent, claim_factory
):
    claim = claim_factory(estimate=None, items=[
        {"area": "Roof", "item": "Tiles", "description": "Tiles off", "estimated_value": None}
    ])
    _, payload = _assessed(
        assessment_agent, intake_agent, policy_agent, validation_agent, claim
    )
    assert payload["value_band"] == "unknown"


def test_assessment_marks_emergency_urgency(
    assessment_agent, intake_agent, policy_agent, validation_agent, claim_factory
):
    claim = claim_factory(habitable=False)
    _, payload = _assessed(
        assessment_agent, intake_agent, policy_agent, validation_agent, claim
    )
    assert payload["urgency_band"] == "emergency"


def test_assessment_reports_the_poc_confidence_floor_without_gating_on_it(
    assessment_agent, intake_agent, policy_agent, validation_agent, submitted_claim
):
    result, _ = _assessed(
        assessment_agent, intake_agent, policy_agent, validation_agent, submitted_claim
    )
    assert result.confidence.clears_poc_threshold is not None
    assert "Phase 2" in result.confidence.threshold_note


# -------------------------------------------------------------- fraud/risk


def _risk_for(risk_agent, intake_agent, policy_agent, claim):
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))
    return risk_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )


def test_risk_agent_finds_no_indicators_on_a_clean_history(
    risk_agent, intake_agent, policy_agent, submitted_claim
):
    result, payload = _risk_for(risk_agent, intake_agent, policy_agent, submitted_claim)

    assert payload["risk_level"] == "low"
    assert payload["indicators"] == []
    assert result.next_step == "continue"


def test_risk_agent_raises_indicators_on_a_recent_policy_with_history(
    risk_agent, intake_agent, policy_agent, claim_factory
):
    claim = claim_factory(
        policy_number="POL-HOME-20349",
        loss_address={
            "address_line_1": "142 Wakefield Street",
            "suburb": "Te Aro",
            "city": "Wellington",
            "postcode": "6011",
        },
    )
    result, payload = _risk_for(risk_agent, intake_agent, policy_agent, claim)

    assert payload["risk_level"] == "high"
    assert len(payload["indicators"]) >= 2
    assert result.next_step == "specialist_review"


def test_risk_indicators_are_never_customer_visible(
    risk_agent, intake_agent, policy_agent, claim_factory
):
    claim = claim_factory(
        policy_number="POL-HOME-20349",
        loss_address={
            "address_line_1": "142 Wakefield Street",
            "suburb": "Te Aro",
            "city": "Wellington",
            "postcode": "6011",
        },
    )
    _, payload = _risk_for(risk_agent, intake_agent, policy_agent, claim)

    assert payload["indicators"]
    assert all(i["customer_visible"] is False for i in payload["indicators"])
    assert "not evidence of fraud" in payload["framing_note"]


@pytest.mark.parametrize("forbidden", ["fraudulent", "fraud detected", "proven", "lying", "dishonest"])
def test_risk_agent_language_never_accuses(
    risk_agent, intake_agent, policy_agent, claim_factory, forbidden
):
    claim = claim_factory(
        policy_number="POL-HOME-20349",
        loss_address={
            "address_line_1": "142 Wakefield Street",
            "suburb": "Te Aro",
            "city": "Wellington",
            "postcode": "6011",
        },
    )
    result, payload = _risk_for(risk_agent, intake_agent, policy_agent, claim)

    blob = " ".join(
        [result.recommendation, *(f.summary for f in result.findings)]
        + [i["detail"] for i in payload["indicators"]]
    ).lower()
    assert forbidden not in blob


def test_risk_agent_degrades_safely_without_data(llm, thresholds, submitted_claim, tmp_path):
    from agents.fraud_risk import FraudRiskAgent
    from app.repositories.reference_data import SyntheticReferenceData

    agent = FraudRiskAgent(llm, SyntheticReferenceData(tmp_path), thresholds)
    result, payload = agent.run(context_for(submitted_claim))

    assert result.status is AgentStatus.DEGRADED
    assert result.next_step == "manual_review"
    # Absence of a risk check must never read as "no risk".
    assert "rather than treating the absence" in result.recommendation


def test_agent_failure_is_contained_and_points_at_a_person(intake_agent):
    result, payload = intake_agent.run({"claim": None})  # forces a TypeError inside

    assert result.status is AgentStatus.FAILED
    assert payload is None
    assert result.next_step == "manual_review"
    assert result.confidence is None
    assert "stack" not in (result.error or "").lower()


def test_date_of_loss_in_the_future_is_reported_as_inconsistent(
    validation_agent, intake_agent, policy_agent, claim_factory
):
    future = (date.today() + timedelta(days=5)).isoformat()
    claim = claim_factory(date_of_loss=future)
    _, intake = intake_agent.run(context_for(claim))
    _, policy = policy_agent.run(context_for(claim))
    _, payload = validation_agent.run(
        context_for(claim, intake_payload=intake, policy_payload=policy)
    )
    assert payload["validation_status"] == "inconsistent"
