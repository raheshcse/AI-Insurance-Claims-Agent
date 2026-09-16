"""Phase 3 — risk routing and escalation.

Covers the twelve scenarios the phase requires, and the properties that matter
more than any individual scenario: routing is rule-derived, reasons are
structured, and nothing here decides a claim.

All data is deterministic — the seeded synthetic policies and the stub LLM.
"""

from __future__ import annotations

import pytest

from routing.contracts import ReviewPriority, RoutingOutcome

WELLINGTON = {
    "address_line_1": "142 Wakefield Street",
    "suburb": "Te Aro",
    "city": "Wellington",
    "postcode": "6011",
}
TAURANGA = {
    "address_line_1": "55 Otumoetai Road",
    "suburb": "Otumoetai",
    "city": "Tauranga",
    "postcode": "3110",
}
CHRISTCHURCH = {
    "address_line_1": "7 Rangiora Avenue",
    "suburb": "Kaiapoi",
    "city": "Christchurch",
    "postcode": "7630",
}

BIG_DAMAGE = [
    {"area": "Roof", "item": "Roof", "description": "Roof partly torn off", "estimated_value": 25_000},
    {"area": "Kitchen", "item": "Ceiling", "description": "Ceiling collapsed", "estimated_value": 12_000},
    {"area": "Garden", "item": "Fence", "description": "Fence flattened", "estimated_value": 4_000},
]


def routing_of(result: dict) -> dict:
    return result["routing"]


def codes(result: dict) -> list[str]:
    return [r["code"] for r in routing_of(result)["reasons"]]


# ---------------------------------------------------- 1. low complexity


def test_low_complexity_high_confidence_claim_stays_on_the_automated_path(
    run_workflow, submitted_claim
):
    result = run_workflow(submitted_claim)
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.AUTOMATED_PATH_RECOMMENDED.value
    assert routing["reasons"] == []
    assert routing["review_type"] is None
    assert routing["recommended_claim_state"] == "Assessment"
    assert routing["rules_evaluated"] >= 12


def test_the_automated_path_is_never_described_as_an_approval(
    run_workflow, submitted_claim
):
    routing = routing_of(run_workflow(submitted_claim))

    assert routing["is_recommendation_only"] is True
    assert "not an approval" in routing["summary"]
    for word in ("approved", "settled", "paid", "declined"):
        assert word not in routing["summary"].lower().replace("approval", "")


# ---------------------------------------------------- 2. high complexity


def test_high_complexity_claim_goes_to_human_review(run_workflow, claim_factory):
    result = run_workflow(claim_factory(estimate=42_000, items=BIG_DAMAGE))
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-02_HIGH_COMPLEXITY" in codes(result)
    assert routing["recommended_claim_state"] == "Human Review"


# ---------------------------------------------------- 3. low confidence


def test_low_confidence_claim_is_escalated(run_workflow, claim_factory, monkeypatch):
    """Raise the decision boundary so a normally-confident claim falls below it."""
    monkeypatch.setenv("DECISION_THRESHOLD", "0.99")

    from conftest_phase2 import run_graph

    from app.domain.thresholds import Thresholds
    from graph.builder import build_claims_graph
    from llm.stub import StubLLMProvider

    graph = build_claims_graph(llm=StubLLMProvider(), thresholds=Thresholds())
    result = run_graph(graph, claim_factory())["intelligence"]

    assert routing_of(result)["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-01_LOW_CONFIDENCE" in codes(result)

    reason = next(r for r in routing_of(result)["reasons"] if r["code"] == "E-01_LOW_CONFIDENCE")
    assert reason["basis"] == "business_rule"
    assert reason["observed_value"]
    assert reason["threshold_value"]
    assert reason["assumption"] is not None


# ---------------------------------------------------- 4. high value


def test_high_value_claim_is_escalated(run_workflow, claim_factory):
    result = run_workflow(claim_factory(estimate=14_000))

    assert routing_of(result)["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-03_HIGH_VALUE" in codes(result)


def test_above_the_authority_limit_is_escalated_and_names_the_future_invariant(
    run_workflow, claim_factory
):
    result = run_workflow(claim_factory(estimate=42_000, items=BIG_DAMAGE))

    reason = next(
        r for r in routing_of(result)["reasons"] if r["code"] == "E-04_ABOVE_AUTOMATED_AUTHORITY"
    )
    assert reason["priority"] == ReviewPriority.HIGH.value
    assert "INV-02" in reason["rule_reference"]
    assert reason["assumption"] is not None


def test_unknown_value_is_treated_conservatively(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(
            estimate=None,
            items=[{"area": "Roof", "item": "Tiles", "description": "Tiles off", "estimated_value": None}],
        )
    )

    assert routing_of(result)["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-03_VALUE_UNKNOWN" in codes(result)


# ---------------------------------------------------- 5. elevated risk


def test_elevated_risk_goes_to_a_specialist(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20349", loss_address=WELLINGTON)
    )
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert routing["review_type"] == "specialist_review"
    assert "E-10_ELEVATED_RISK" in codes(result)


def test_risk_escalation_language_never_accuses(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20349", loss_address=WELLINGTON)
    )
    blob = str(routing_of(result)).lower()

    for forbidden in ("fraudulent", "fraud detected", "proven", "dishonest", "lying"):
        assert forbidden not in blob
    assert "not findings against the customer" in str(routing_of(result)["reasons"]).lower()


# ---------------------------------------------------- 6. missing information


def test_missing_information_routes_to_information_required(run_workflow, claim_factory):
    result = run_workflow(claim_factory(photos=False))
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.INFORMATION_REQUIRED.value
    assert routing["recommended_claim_state"] == "Information Required"
    assert routing["review_type"] is None
    assert "E-08_MISSING_INFORMATION" in codes(result)


def test_missing_information_does_not_outrank_safety(run_workflow, claim_factory):
    """A customer whose home is unsafe reaches a person even with gaps in the FNOL."""
    result = run_workflow(claim_factory(photos=False, habitable=False))
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert routing["priority"] == ReviewPriority.URGENT.value
    assert codes(result)[0] == "E-11_EMERGENCY"


# ---------------------------------------------------- 7. vulnerable customer


def test_vulnerable_customer_is_escalated(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20233", loss_address=CHRISTCHURCH)
    )

    assert routing_of(result)["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-12_VULNERABLE_CUSTOMER" in codes(result)


def test_vulnerable_customer_reason_records_no_personal_detail(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20233", loss_address=CHRISTCHURCH)
    )
    reason = next(
        r for r in routing_of(result)["reasons"] if r["code"] == "E-12_VULNERABLE_CUSTOMER"
    )

    # Operational only: a support flag and a contact preference. Nothing medical,
    # nothing diagnostic, nothing the POC has any business recording.
    assert reason["basis"] == "business_rule"
    blob = str(reason).lower()
    for forbidden in ("medical", "diagnosis", "condition", "illness", "disability"):
        assert forbidden not in blob


def test_vulnerability_never_becomes_a_risk_indicator(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20233", loss_address=CHRISTCHURCH)
    )
    risk_blob = str(result.get("risk_assessment") or {}).lower()

    for forbidden in ("vulnerab", "accessibility"):
        assert forbidden not in risk_blob


# ---------------------------------------------------- 8. emergency


def test_emergency_claim_is_urgent_and_priority_routed(run_workflow, claim_factory):
    result = run_workflow(claim_factory(habitable=False))
    routing = routing_of(result)

    assert routing["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert routing["priority"] == ReviewPriority.URGENT.value
    assert routing["review_type"] == "priority_review"
    assert routing["primary_reason_code"] == "E-11_EMERGENCY"


@pytest.mark.parametrize(
    "override",
    [{"habitable": False}, {"injured": True}],
)
def test_each_emergency_signal_triggers_the_pathway(run_workflow, claim_factory, override):
    result = run_workflow(claim_factory(**override))
    assert routing_of(result)["priority"] == ReviewPriority.URGENT.value


def test_emergency_is_detected_even_when_the_workflow_short_circuits(
    run_workflow, claim_factory
):
    """No policy, so assessment never runs — the emergency must still be caught."""
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-99999", injured=True)
    )

    assert result["damage_assessment"] is None
    assert routing_of(result)["priority"] == ReviewPriority.URGENT.value
    assert "E-11_EMERGENCY" in codes(result)


# ------------------------------------------- 12. unexpected AI output


def test_degraded_analysis_fails_closed(claim_factory, llm, reference_data, thresholds):
    from conftest_phase2 import run_graph

    from agents.fraud_risk import FraudRiskAgent
    from graph.builder import build_claims_graph
    import graph.builder as builder_module

    class ExplodingRiskAgent(FraudRiskAgent):
        def analyse(self, context):  # noqa: ANN001, ANN201
            raise RuntimeError("simulated agent failure")

    original = builder_module.FraudRiskAgent
    builder_module.FraudRiskAgent = ExplodingRiskAgent
    try:
        graph = build_claims_graph(
            llm=llm, reference_data=reference_data, thresholds=thresholds
        )
        result = run_graph(graph, claim_factory())["intelligence"]
    finally:
        builder_module.FraudRiskAgent = original

    assert routing_of(result)["outcome"] == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value
    assert "E-16_INCOMPLETE_ANALYSIS" in codes(result)


def test_empty_agent_output_never_clears_a_claim(thresholds):
    """The router given nothing must not answer 'automated path'."""
    from routing.router import RiskRouter

    decision = RiskRouter(thresholds).route(
        claim={"claim_id": "CLM-2026-000000", "fnol": {}},
        payloads={},
        agent_results={},
        customer={},
        degraded=False,
    )

    assert decision.outcome is RoutingOutcome.HUMAN_REVIEW_REQUIRED
    assert decision.primary_reason_code == "E-01_NO_CONFIDENCE"


def test_a_rule_that_raises_escalates_rather_than_clearing(thresholds):
    from routing.router import RiskRouter

    def exploding_rule(ctx):  # noqa: ANN001, ANN202
        raise RuntimeError("rule blew up")

    decision = RiskRouter(thresholds, rules=(exploding_rule,)).route(
        claim={"claim_id": "CLM-2026-000000"},
        payloads={},
        agent_results={},
        customer={},
        degraded=False,
    )

    assert decision.outcome is RoutingOutcome.HUMAN_REVIEW_REQUIRED
    assert decision.reasons[0].code == "E-16_ROUTING_RULE_FAILED"


# ------------------------------------------- structure and explainability


def test_every_reason_is_structured_not_generic(run_workflow, claim_factory):
    result = run_workflow(claim_factory(estimate=42_000, items=BIG_DAMAGE))

    for reason in routing_of(result)["reasons"]:
        assert reason["code"]
        assert reason["label"]
        assert len(reason["detail"]) > 20
        assert reason["basis"] in {"ai_finding", "business_rule"}
        assert reason["rule_reference"]
        assert "ai decided" not in reason["detail"].lower()


def test_explanation_names_observation_threshold_and_source(run_workflow, claim_factory):
    result = run_workflow(claim_factory(estimate=14_000))
    explanation = " ".join(routing_of(result)["explanation"])

    assert "Observed:" in explanation
    assert "Compared against:" in explanation
    assert "Source:" in explanation


def test_all_applicable_reasons_are_collected_not_just_the_first(
    run_workflow, claim_factory
):
    result = run_workflow(claim_factory(estimate=42_000, items=BIG_DAMAGE, habitable=False))
    reason_codes = codes(result)

    assert len(reason_codes) >= 3
    assert reason_codes[0] == "E-11_EMERGENCY"
    assert "E-04_ABOVE_AUTOMATED_AUTHORITY" in reason_codes
    assert "E-02_HIGH_COMPLEXITY" in reason_codes


def test_priority_is_the_strongest_across_all_reasons(run_workflow, claim_factory):
    """A standard-priority claim that also has an urgent reason is urgent."""
    result = run_workflow(claim_factory(estimate=14_000, habitable=False))
    assert routing_of(result)["priority"] == ReviewPriority.URGENT.value


def test_routing_decision_is_rule_derived_not_model_derived(run_workflow, submitted_claim):
    routing = routing_of(run_workflow(submitted_claim))
    assert routing["decision_authority"] == "business_rules"


def test_routing_never_recommends_approved_completed(run_workflow, claim_factory):
    """Approved/Completed is reachable only by a reviewer's own action."""
    for claim in (
        claim_factory(),
        claim_factory(photos=False),
        claim_factory(estimate=99_000),
        claim_factory(habitable=False),
        claim_factory(policy_number="POL-HOME-99999"),
    ):
        assert routing_of(run_workflow(claim))["recommended_claim_state"] != "Approved/Completed"


def test_no_governance_constructs_are_fabricated_in_routing(run_workflow, claim_factory):
    routing = routing_of(run_workflow(claim_factory(estimate=42_000, items=BIG_DAMAGE)))

    for fabricated in ("prenode_result", "invariant_result", "terminal_state", "ledger_entry"):
        assert fabricated not in routing
