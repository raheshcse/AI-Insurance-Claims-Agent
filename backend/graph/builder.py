"""The claims intelligence StateGraph.

    START -> intake -> policy -> validation -> assessment -> fraud_risk
                                  |            |                    |
                                  +------------+--------------------+
                                               v
                                         escalation -> governance_gate -> finalize -> END
                                        (Phase 3 routing)   |  (PN-01)        ^
                                                            +-> governance_fallback

Conditional routing is used **only** where the Phase 0 decision framework calls
for it -- the brief asks for justified branches, not clever ones. There are
exactly two, and each maps to a documented decision row:

  * **After policy** -- if the policy could not be found, or there is no cover
    basis at the date of loss, validating and assessing against a policy that
    does not respond is meaningless work that produces misleading confidence.
    Row D-03. Skip ahead.

  * **After validation** -- if required information is outstanding, the claim
    goes back to the customer rather than being assessed. Row D-01. Skip ahead.

Both short-circuits now land on **escalation**, not on finalize. That is the
Phase 3 change and it matters: a claim that skipped assessment still has to be
routed, and a customer whose home is unsafe must reach a person whether or not
their policy was found. Routing always runs.

Everything else runs straight through. In particular the workflow does **not**
branch on risk or complexity: those shape the recommendation, and routing on
them is Phase 3's job.

**Phase 4: governance is on the path.** `governance_gate` is VSL's `gated_node`
wrapping PN-01, and `route_on_denial` sends a denial to `governance_fallback`
instead of the authorised branch. The gate carries its own `denial_key`; two
gates sharing one would make the second router read the first gate's denial.

The ledger-writing, Invariant-enforcing gate lives at the irreversible write, in
`ReviewService.apply_routing`, where the side effect is passed into the gate as a
callable so no denial path can reach it. See `graph/governed.py` for why there
are two commitment points and what each protects.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.assessment import AssessmentAgent
from agents.fraud_risk import FraudRiskAgent
from agents.intake import IntakeAgent
from agents.policy import PolicyAgent
from agents.validation import ValidationAgent
from app.domain.thresholds import Thresholds, get_thresholds
from app.repositories.reference_data import SyntheticReferenceData, get_reference_data
from graph.escalation import escalation_node
from graph.finalize import finalize_node
from graph.governed import (
    build_governance_node,
    build_governance_router,
    governance_fallback_node,
)
from graph.nodes import agent_node
from graph.state import ClaimsWorkflowState
from llm.base import LLMProvider
from llm.factory import get_llm_provider
from routing.router import RiskRouter

logger = logging.getLogger("claims.workflow")

_NO_COVER_BASIS = {"no_cover_basis"}


def _after_policy(state: ClaimsWorkflowState) -> str:
    """Decision row D-03: no policy, or no cover at the date of loss."""
    interpretation = ((state.get("payloads") or {}).get("policy") or {}).get(
        "interpretation"
    ) or {}

    if interpretation.get("policy_found") is False:
        logger.info(
            "workflow.short_circuit claim_id=%s reason=policy_not_found target=escalation",
            state.get("claim_id"),
        )
        return "escalation"

    if interpretation.get("cover_certainty") in _NO_COVER_BASIS:
        logger.info(
            "workflow.short_circuit claim_id=%s reason=no_cover_basis target=escalation",
            state.get("claim_id"),
        )
        return "escalation"

    return "validation"


def _after_validation(state: ClaimsWorkflowState) -> str:
    """Decision row D-01: required information outstanding."""
    validation = (state.get("payloads") or {}).get("validation") or {}

    if validation.get("validation_status") == "information_required":
        logger.info(
            "workflow.short_circuit claim_id=%s reason=information_required target=escalation",
            state.get("claim_id"),
        )
        return "escalation"

    return "assessment"


def build_claims_graph(
    *,
    llm: LLMProvider | None = None,
    reference_data: SyntheticReferenceData | None = None,
    thresholds: Thresholds | None = None,
) -> Any:
    """Compile the Phase 2 claims intelligence graph."""
    provider = llm or get_llm_provider()
    data = reference_data or get_reference_data()
    limits = thresholds or get_thresholds()

    graph = StateGraph(ClaimsWorkflowState)

    graph.add_node("intake", agent_node(IntakeAgent(provider)))
    graph.add_node("policy", agent_node(PolicyAgent(provider, data)))
    graph.add_node("validation", agent_node(ValidationAgent(provider)))
    graph.add_node("assessment", agent_node(AssessmentAgent(provider, limits)))
    graph.add_node("fraud_risk", agent_node(FraudRiskAgent(provider, data, limits)))
    graph.add_node("escalation", escalation_node(RiskRouter(limits), data))
    graph.add_node("governance_gate", build_governance_node())
    graph.add_node("governance_fallback", governance_fallback_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "policy")

    graph.add_conditional_edges(
        "policy",
        _after_policy,
        {"validation": "validation", "escalation": "escalation"},
    )
    graph.add_conditional_edges(
        "validation",
        _after_validation,
        {"assessment": "assessment", "escalation": "escalation"},
    )

    graph.add_edge("assessment", "fraud_risk")
    graph.add_edge("fraud_risk", "escalation")

    # Phase 4: PN-01 gates the workflow's commitment to the automated branch.
    # `gated_node` calls the gate immediately before the wrapped node and, on
    # denial, returns a state update instead of raising -- so the conditional
    # edge routes the run rather than crashing the graph.
    graph.add_edge("escalation", "governance_gate")
    graph.add_conditional_edges(
        "governance_gate",
        build_governance_router(),
        {"governance_fallback": "governance_fallback", "finalize": "finalize"},
    )
    graph.add_edge("governance_fallback", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
