"""Phase 2/3 — the LangGraph workflow.

Covers the workflow exit criteria: it starts, nodes run in order, shared state is
maintained, it completes, and each required scenario produces the right outcome.

Phase 3 added the escalation node, so the expected node order is `NODE_ORDER` (the
five agents plus escalation) rather than `AGENT_ORDER`. Routing-specific behaviour
is tested in `test_routing.py`; this file tests the graph.
"""

from __future__ import annotations

import pytest

from agents.contracts import AgentStatus
from graph.state import AGENT_ORDER, NODE_ORDER, initial_state

# Addresses for the seeded policies, so a claim can be pointed at each one.
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


# ------------------------------------------------------------- mechanics


def test_workflow_starts_and_completes(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)

    assert result["claim_id"] == submitted_claim["claim_id"]
    assert result["analysis_id"].startswith("ANL-")
    assert result["recommended_next_step"]
    assert result["workflow_version"] == "phase-4"


def test_nodes_execute_in_the_expected_order(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)
    assert [entry["agent"] for entry in result["trace"]] == list(NODE_ORDER)


def test_shared_state_accumulates_every_agent_result(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)

    assert set(result["agent_results"]) == set(AGENT_ORDER)
    assert result["policy_assessment"] is not None
    assert result["validation_result"] is not None
    assert result["damage_assessment"] is not None
    assert result["risk_assessment"] is not None


def test_later_agents_see_earlier_results(run_workflow, submitted_claim):
    """The assessment's excess comes from the policy agent, not the claim."""
    result = run_workflow(submitted_claim)
    assert result["damage_assessment"]["net_of_excess_estimate"] == 3200


def test_trace_records_timing_and_status(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)
    for entry in result["trace"]:
        assert entry["status"] in {s.value for s in AgentStatus}
        assert entry["duration_ms"] >= 0
        assert entry["started_at"] and entry["finished_at"]


# --------------------------------------------------------------- scenarios


def test_scenario_normal_low_complexity_claim(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)

    assert result["recommended_next_step"] == "standard_processing_candidate"
    assert result["damage_assessment"]["complexity_band"] == "low"
    assert result["risk_assessment"]["risk_level"] == "low"
    assert result["degraded"] is False
    # Even the best case is not an approval.
    assert "not an approval" in result["recommendation_summary"]


def test_scenario_missing_information(run_workflow, claim_factory):
    result = run_workflow(claim_factory(photos=False))

    assert result["recommended_next_step"] == "information_required"
    assert result["recommended_claim_state"] == "Information Required"
    # Short-circuits before assessment -- decision row D-01 -- but routing still
    # runs. A claim that skipped assessment must still be routed, and from
    # Phase 4 it must still pass the governance gate: a short-circuited claim is
    # exactly the kind that must not slip past governance on its way out.
    assert [e["agent"] for e in result["trace"]] == [
        "intake",
        "policy",
        "validation",
        "escalation",
        "governance_gate",
    ]
    assert result["damage_assessment"] is None


def test_scenario_policy_mismatch_not_found(run_workflow, claim_factory):
    result = run_workflow(claim_factory(policy_number="POL-HOME-99999"))

    assert result["recommended_next_step"] == "manual_review_recommended"
    assert result["policy_assessment"]["interpretation"]["policy_found"] is False
    # Short-circuits after policy -- decision row D-03 -- and still reaches
    # routing and then the governance gate.
    assert [e["agent"] for e in result["trace"]] == [
        "intake",
        "policy",
        "escalation",
        "governance_gate",
    ]


def test_scenario_policy_not_in_force(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20233", loss_address=CHRISTCHURCH)
    )

    assert result["recommended_next_step"] == "manual_review_recommended"
    assert result["routing"]["primary_reason_code"] == "E-05_POLICY_NOT_IN_FORCE"
    assert result["recommended_claim_state"] == "Human Review"


def test_scenario_high_complexity_claim(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(
            estimate=42_000,
            habitable=False,
            items=[
                {"area": "Roof", "item": "Roof", "description": "Roof partly torn off", "estimated_value": 25_000},
                {"area": "Kitchen", "item": "Ceiling", "description": "Ceiling collapsed", "estimated_value": 12_000},
                {"area": "Garden", "item": "Fence", "description": "Fence flattened", "estimated_value": 4_000},
            ],
        )
    )

    assert result["recommended_next_step"] == "manual_review_recommended"
    assert result["damage_assessment"]["complexity_band"] == "high"
    assert result["damage_assessment"]["value_band"] == "above_automated_authority"
    assert result["recommended_claim_state"] == "Human Review"


def test_scenario_elevated_risk_indicators(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(policy_number="POL-HOME-20349", loss_address=WELLINGTON)
    )

    assert result["recommended_next_step"] == "specialist_review_recommended"
    assert result["risk_assessment"]["risk_level"] == "high"
    assert result["risk_assessment"]["indicators"]
    assert result["routing"]["review_type"] == "specialist_review"


def test_scenario_possible_exclusion(run_workflow, claim_factory):
    result = run_workflow(
        claim_factory(
            policy_number="POL-HOME-20455",
            loss_address=TAURANGA,
            description=(
                "The storm lifted tiles from the roof, which was already worn and due "
                "for replacement, and water came in through the ceiling."
            ),
        )
    )

    assert result["recommended_next_step"] == "manual_review_recommended"
    assert result["policy_assessment"]["interpretation"]["exclusions_possibly_engaged"]


def test_scenario_agent_failure_fails_closed(claim_factory, llm, reference_data, thresholds):
    """A crashing agent must produce a human recommendation, never a clear result."""
    from graph.builder import build_claims_graph
    from agents.fraud_risk import FraudRiskAgent

    class ExplodingRiskAgent(FraudRiskAgent):
        def analyse(self, context):  # noqa: ANN001, ANN201
            raise RuntimeError("simulated agent failure")

    import graph.builder as builder_module

    original = builder_module.FraudRiskAgent
    builder_module.FraudRiskAgent = ExplodingRiskAgent
    try:
        graph = build_claims_graph(
            llm=llm, reference_data=reference_data, thresholds=thresholds
        )
        from conftest_phase2 import run_graph

        result = run_graph(graph, claim_factory())["intelligence"]
    finally:
        builder_module.FraudRiskAgent = original

    assert result["degraded"] is True
    assert result["recommended_next_step"] == "manual_review_recommended"
    assert result["agent_results"]["fraud_risk"]["status"] == "failed"
    assert result["errors"]
    # The workflow still completed -- one agent failing does not break the graph.
    assert len(result["trace"]) == len(NODE_ORDER)
    # And the failure is not dressed up as a clean risk result.
    assert result["risk_assessment"] is None


def test_llm_failure_does_not_change_any_decision(
    claim_factory, reference_data, thresholds, submitted_claim
):
    """Decisions are rule-derived, so a dead model changes prose and nothing else."""
    from conftest_phase2 import run_graph

    from graph.builder import build_claims_graph
    from llm.base import NarrationResult
    from llm.stub import StubLLMProvider

    class BrokenLLM(StubLLMProvider):
        name = "broken"

        def narrate(self, request):  # noqa: ANN001, ANN201
            return NarrationResult(text="", provider="broken", degraded=True)

    healthy = run_graph(
        build_claims_graph(
            llm=StubLLMProvider(), reference_data=reference_data, thresholds=thresholds
        ),
        submitted_claim,
    )["intelligence"]

    broken = run_graph(
        build_claims_graph(
            llm=BrokenLLM(), reference_data=reference_data, thresholds=thresholds
        ),
        submitted_claim,
    )["intelligence"]

    assert healthy["recommended_next_step"] == broken["recommended_next_step"]
    assert healthy["damage_assessment"]["complexity_band"] == broken["damage_assessment"]["complexity_band"]
    assert healthy["risk_assessment"]["risk_level"] == broken["risk_assessment"]["risk_level"]


# ----------------------------------------------------- the safety boundary


@pytest.mark.parametrize(
    "scenario",
    ["normal", "missing_info", "no_policy", "high_value", "elevated_risk"],
)
def test_no_scenario_ever_performs_an_action(run_workflow, claim_factory, scenario):
    claims = {
        "normal": claim_factory(),
        "missing_info": claim_factory(photos=False),
        "no_policy": claim_factory(policy_number="POL-HOME-99999"),
        "high_value": claim_factory(estimate=99_000),
        "elevated_risk": claim_factory(
            policy_number="POL-HOME-20349", loss_address=WELLINGTON
        ),
    }
    result = run_workflow(claims[scenario])

    assert result["is_recommendation_only"] is True
    assert result["action_taken"] == "none"
    # The workflow itself never changes a claim state -- applying the routing
    # decision is the service layer's job, and this is the graph's own output.
    assert result["claim_state_changed"] is False
    assert result["claim_state"] == "Submitted"


def test_recommendations_never_use_decision_language(run_workflow, claim_factory):
    for claim in (
        claim_factory(),
        claim_factory(photos=False),
        claim_factory(estimate=99_000),
    ):
        result = run_workflow(claim)
        step = result["recommended_next_step"]
        assert step in {
            "information_required",
            "manual_review_recommended",
            "specialist_review_recommended",
            "standard_processing_candidate",
        }


def test_the_governance_layer_arrived_in_phase_4_and_is_the_real_framework():
    """The Phase 2 version of this test asserted governance did NOT yet exist.

    Phase 4 built it, so the assertion is inverted rather than deleted --
    deleting it would quietly drop the guarantee it was protecting. What it
    protects now is that governance is the *actual* framework and not a
    look-alike: the constructs must be `vsl_core` types, not local classes
    wearing VSL names.
    """
    from pathlib import Path

    import vsl_core.constructs as vsl_constructs

    from governance.policy import (
        ALL_INVARIANTS,
        AUTOMATION_CONFIDENCE,
        CLAIM_AUTOMATION_SUSPENDED,
    )

    governance_dir = Path(__file__).resolve().parents[2] / "governance"
    for module in ("policy.py", "gates.py", "ledger.py", "audit_cli.py"):
        assert (governance_dir / module).exists(), f"governance/{module} is missing"

    # The decisive check. `type(x) is vsl_core's class` fails for a mock that
    # merely subclasses or duck-types the name.
    assert type(AUTOMATION_CONFIDENCE) is vsl_constructs.PreNode
    assert type(CLAIM_AUTOMATION_SUSPENDED) is vsl_constructs.TerminalState
    assert ALL_INVARIANTS
    for invariant in ALL_INVARIANTS:
        assert type(invariant) is vsl_constructs.Invariant

    # And the classes come from the installed distribution, not from this repo.
    assert "governance" not in vsl_constructs.__file__
    assert vsl_constructs.__name__.startswith("vsl_core")


def test_workflow_output_carries_no_fabricated_governance_verdict(
    run_workflow, submitted_claim
):
    """Explaining a future gate is fine; claiming one ran is not."""
    result = run_workflow(submitted_claim)

    for fabricated in (
        "governance_outcome",
        "prenode_result",
        "invariant_result",
        "terminal_state",
        "decision_id",
        "ledger_entry",
    ):
        assert fabricated not in result


def test_initial_state_is_well_formed(submitted_claim):
    state = initial_state(submitted_claim)
    assert state["results"] == {}
    assert state["payloads"] == {}
    assert state["trace"] == []
    assert state["halt"] is False
