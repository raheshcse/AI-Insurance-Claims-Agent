"""The escalation node.

Phase 3's addition to the workflow. It consumes the five agents' output and
produces the routing decision, then `finalize` assembles the result around it.

It is a node rather than post-processing for two reasons: the decision belongs in
the trace with everything else, and Phase 4's gate for the routing commitment
(CP-11) wraps a node. Wrapping this one with `gated_node` and pairing it with
`route_on_denial` is exactly the shape the VSL spec describes.

**No gate exists here yet.** The node records a routing decision; it performs no
side effect. Applying the decision — writing the claim state, creating the queue
entry — happens in the service layer, which is where the gate goes.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.repositories.reference_data import MissingDatasetError, SyntheticReferenceData
from graph.state import ClaimsWorkflowState
from routing.router import RiskRouter

logger = logging.getLogger("claims.workflow")


def escalation_node(
    router: RiskRouter, reference_data: SyntheticReferenceData
) -> Any:  # noqa: ANN401 - LangGraph node signature
    """Build the escalation node."""

    def node(state: ClaimsWorkflowState) -> dict[str, Any]:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        claim_id = state.get("claim_id", "unknown")

        logger.info("escalation.start claim_id=%s", claim_id)

        results = state.get("results") or {}
        payloads = state.get("payloads") or {}
        degraded = any(
            r.get("status") in {"failed", "degraded"} for r in results.values()
        ) or bool(state.get("errors"))

        customer = _resolve_customer(payloads, reference_data)

        decision = router.route(
            claim=state.get("claim") or {},
            payloads=payloads,
            agent_results=results,
            customer=customer,
            degraded=degraded,
        )

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "escalation.finish claim_id=%s outcome=%s priority=%s reasons=%d duration_ms=%d",
            claim_id,
            decision.outcome.value,
            decision.priority.value,
            len(decision.reasons),
            duration_ms,
        )

        return {
            "routing": decision.model_dump(mode="json"),
            "customer_context": customer,
            "trace": [
                {
                    "agent": "escalation",
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "status": "complete",
                    "next_step": decision.outcome.value,
                    "error": None,
                }
            ],
        }

    node.__name__ = "escalation_node"
    return node


def _resolve_customer(
    payloads: dict[str, Any], reference_data: SyntheticReferenceData
) -> dict[str, Any]:
    """Find the policyholder behind the claim, for the vulnerable-customer rule.

    Only operational fields are carried forward — the support flag, accessibility
    needs and contact preference. Nothing diagnostic or personal beyond that, per
    docs/HUMAN_ESCALATION_POLICY.md §4.2.
    """
    policy_id = ((payloads.get("policy") or {}).get("facts") or {}).get("policy_id")
    if not policy_id:
        return {}

    try:
        policy = reference_data.find_policy(policy_id)
        if not policy:
            return {}
        customer = reference_data.find_customer(policy.get("customer_id", ""))
    except MissingDatasetError:
        return {}

    if not customer:
        return {}

    return {
        "customer_id": customer.get("customer_id"),
        "full_name": customer.get("full_name"),
        "vulnerability_flag": bool(customer.get("vulnerability_flag")),
        "accessibility_needs": customer.get("accessibility_needs"),
        "preferred_contact_method": customer.get("preferred_contact_method"),
        "customer_since": customer.get("customer_since"),
    }
