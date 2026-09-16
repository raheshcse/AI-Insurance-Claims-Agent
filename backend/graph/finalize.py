"""The finalize node.

Assembles one claims intelligence result from the five agent results and the
escalation node's routing decision.

**Phase 3 changed this node's job.** In Phase 2 it both decided the recommendation
and assembled the result; the precedence logic lived here. Phase 3 moved that
logic into `routing/rules.py` and `routing/router.py`, where it is a catalogue of
named, testable rules traceable to Phase 0 rows. Finalize now *consumes* the
decision. Two copies of a precedence order is exactly the kind of duplication that
drifts, and the one that drifts silently is the one that decides whether a claim
reaches a person.

So `recommended_next_step` here is a presentation of `RoutingOutcome`, not a
second opinion about it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from agents.contracts import Confidence
from app.domain.claim_state import ClaimState
from app.schemas.intelligence import RecommendedNextStep
from graph.state import ClaimsWorkflowState

_DEGRADED_STATUSES = {"failed", "degraded"}


def _overall_confidence(results: dict[str, Any], degraded: bool) -> Confidence | None:
    """The most conservative agent confidence.

    Minimum, not mean: an average lets a confident intake paper over an
    unconfident policy read, which is exactly the claim you want a person on.
    """
    values = [
        (name, r["confidence"]["value"])
        for name, r in results.items()
        if r.get("confidence")
    ]
    if not values:
        return None

    name, lowest = min(values, key=lambda pair: pair[1])
    if degraded:
        lowest = min(lowest, 0.5)

    from app.domain.thresholds import get_thresholds

    floor = get_thresholds().effective_confidence_floor
    return Confidence(
        value=round(lowest, 3),
        basis=(
            f"The lowest agent confidence ({name}), taken as the workflow's. "
            + ("Capped because part of the workflow degraded." if degraded else "")
        ).strip(),
        clears_poc_threshold=lowest >= floor,
        threshold_note=(
            f"Compared against the POC-proposed confidence floor of {floor:.4f}. "
            "Reported only -- no gate acts on it until Phase 4."
        ),
    )


def _next_step(routing: dict[str, Any]) -> RecommendedNextStep:
    """Present the routing outcome. Not a second decision."""
    outcome = routing.get("outcome")

    if outcome == "INFORMATION_REQUIRED":
        return RecommendedNextStep.INFORMATION_REQUIRED
    if outcome == "AUTOMATED_PATH_RECOMMENDED":
        return RecommendedNextStep.STANDARD_PROCESSING_CANDIDATE
    if routing.get("review_type") == "specialist_review":
        return RecommendedNextStep.SPECIALIST_REVIEW_RECOMMENDED
    return RecommendedNextStep.MANUAL_REVIEW_RECOMMENDED


def finalize_node(state: ClaimsWorkflowState) -> dict[str, Any]:
    results: dict[str, Any] = state.get("results") or {}
    payloads: dict[str, Any] = state.get("payloads") or {}
    claim: dict[str, Any] = state.get("claim") or {}
    routing: dict[str, Any] = state.get("routing") or {}

    policy = payloads.get("policy") or {}
    validation = payloads.get("validation") or {}
    assessment = payloads.get("assessment") or {}
    risk = payloads.get("fraud_risk") or {}
    intake = payloads.get("intake") or {}

    degraded = any(
        r.get("status") in _DEGRADED_STATUSES for r in results.values()
    ) or bool(state.get("errors"))

    confidence = _overall_confidence(results, degraded)

    reasons = list(routing.get("explanation") or [])
    if state.get("halt_reason"):
        reasons.append(f"Workflow stopped early: {state['halt_reason']}")

    recommended_state = routing.get("recommended_claim_state")

    intelligence = {
        "claim_id": state.get("claim_id", ""),
        "analysis_id": f"ANL-{uuid.uuid4().hex[:12].upper()}",
        "analysed_at": datetime.now(timezone.utc).isoformat(),
        "workflow_version": "phase-4",
        # The recommendation/action boundary is asserted here, in the workflow,
        # not only in the API schema. A caller reading the graph's own output
        # gets the same guarantee as one reading the HTTP response.
        "is_recommendation_only": True,
        "action_taken": "none",
        "claim_state_changed": False,
        "boundary_note": (
            "This is analysis and routing, not a claim decision. No claim has been "
            "approved, declined or settled, and no customer has been contacted. "
            "Routing may move a claim towards a person; it never decides it."
        ),
        "claim_state": claim.get("claim_state", ClaimState.SUBMITTED.value),
        "claim_summary": {
            "policy_number": ((claim.get("fnol") or {}).get("customer") or {}).get(
                "policy_number"
            ),
            "customer_name": ((claim.get("fnol") or {}).get("customer") or {}).get(
                "full_name"
            ),
            "peril": intake.get("peril"),
            "date_of_loss": intake.get("date_of_loss"),
            "loss_address": intake.get("loss_address"),
            "damaged_item_count": intake.get("damaged_item_count"),
            "damage_areas": intake.get("damage_areas"),
        },
        "agent_results": results,
        "policy_assessment": policy or None,
        "validation_result": validation or None,
        "damage_assessment": assessment or None,
        "risk_assessment": risk or None,
        # -- Phase 3 --------------------------------------------------------
        "routing": routing or None,
        "customer_context": state.get("customer_context") or None,
        "governance_gate": state.get("governance_gate") or None,
        # -- presentation of the routing decision ---------------------------
        "recommended_next_step": _next_step(routing).value,
        "recommendation_summary": routing.get("summary", ""),
        "recommendation_reasons": [r for r in reasons if r],
        "overall_confidence": confidence.model_dump(mode="json") if confidence else None,
        "recommended_claim_state": recommended_state,
        "trace": state.get("trace") or [],
        "errors": state.get("errors") or [],
        "degraded": degraded,
    }

    return {"intelligence": intelligence}
