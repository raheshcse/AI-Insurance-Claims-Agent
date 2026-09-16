"""VSL-LangGraph integration — the workflow-level gate.

This is `gated_node` and `route_on_denial` from `vsl_langgraph`, wiring the same
compiled PreNode object that `governance/gates.py` uses into the StateGraph.
`policy.py` does not change when the wiring does; only this module knows about
graphs.

**Two governed commitment points, and what each one does.**

| Point | Where | What it protects | Mechanism |
| --- | --- | --- | --- |
| CP-11 | here, in the graph | the workflow committing to the automated branch | `gated_node` + `route_on_denial` |
| CP-09 / CP-12 | `ReviewService.apply_routing` | the claim-state write and queue placement | `govern_automated_route(perform=...)` |

The one that carries the ledger and the Invariants is the second — it guards the
irreversible write, and the side effect is passed into the gate as a callable so
no denial path can reach it. This module is the workflow's own soft gate: it
routes the graph away from the automated branch on denial, so the run never even
reaches the code that would propose automation. Its decision is recorded in the
workflow state and appears in the trace.

`gated_node` calls the gate immediately before the wrapped node and, on denial,
returns a state update instead of raising — so a conditional edge routes the run
rather than crashing the graph.

Each gate carries its **own** `denial_key` (from `governance.policy.DENIAL_KEYS`).
Two gates sharing a key makes the second router read the first gate's denial.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from vsl_langgraph import gated_node, route_on_denial

from governance.gates import confidence_gate
from governance.policy import AUTOMATION_CONFIDENCE, DENIAL_KEYS, effective_confidence_floor
from graph.state import ClaimsWorkflowState

logger = logging.getLogger("claims.governance")

PN01_DENIAL_KEY = DENIAL_KEYS[AUTOMATION_CONFIDENCE.name]


def _confidence_of(state: ClaimsWorkflowState) -> float:
    """The workflow's confidence: the lowest any agent reported.

    The same value the routing rules use, so the graph gate and the service gate
    cannot disagree about what they are judging.
    """
    results = state.get("results") or {}
    values = [
        r["confidence"]["value"] for r in results.values() if r.get("confidence")
    ]
    return min(values) if values else 0.0


def _candidate_input(state: dict[str, Any]) -> dict[str, Any]:
    """What the PreNode's monitor sees. Nothing else reaches the gate."""
    return {"confidence": _confidence_of(state)}  # type: ignore[arg-type]


def _authorise_automated_branch(state: ClaimsWorkflowState) -> dict[str, Any]:
    """Runs only when PN-01 passed. Records the workflow-level authorisation.

    It performs no side effect of its own — the irreversible write is gated
    separately, at the point it actually happens.
    """
    confidence = _confidence_of(state)
    logger.info(
        "governance.graph_gate_passed claim_id=%s confidence=%.4f",
        state.get("claim_id"),
        confidence,
    )
    return {
        "governance_gate": {
            "gate": AUTOMATION_CONFIDENCE.name,
            "denial_key": PN01_DENIAL_KEY,
            "outcome": "authorised",
            "confidence": round(confidence, 4),
            "confidence_floor": round(effective_confidence_floor(), 4),
            "assurance_level": AUTOMATION_CONFIDENCE.assurance_level.value,
            "gamma_threshold": AUTOMATION_CONFIDENCE.gamma_threshold,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
        "trace": [
            {
                "agent": "governance_gate",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0,
                "status": "complete",
                "next_step": "authorised",
                "error": None,
            }
        ],
    }


def governance_fallback_node(state: ClaimsWorkflowState) -> dict[str, Any]:
    """Where a PN-01 denial lands inside the graph.

    The fallback declared on the PreNode is `ROUTE_TO_HUMAN_QUEUE`, and this is
    it. `Fallback`'s own fields are declarative only — no adapter consumes them —
    so the behaviour is implemented here and in `gates.py`, as the VSL guidance
    instructs.
    """
    denial = state.get(PN01_DENIAL_KEY)
    confidence = _confidence_of(state)

    logger.info(
        "governance.graph_gate_denied claim_id=%s gate=%s fallback=%s confidence=%.4f",
        state.get("claim_id"),
        AUTOMATION_CONFIDENCE.name,
        AUTOMATION_CONFIDENCE.fallback.on_failure,
        confidence,
    )

    return {
        "governance_gate": {
            "gate": AUTOMATION_CONFIDENCE.name,
            "denial_key": PN01_DENIAL_KEY,
            "outcome": "denied",
            "fallback": AUTOMATION_CONFIDENCE.fallback.on_failure,
            "reason": getattr(denial, "reason", None) or str(denial or "denied"),
            "confidence": round(confidence, 4),
            "confidence_floor": round(effective_confidence_floor(), 4),
            "assurance_level": AUTOMATION_CONFIDENCE.assurance_level.value,
            "gamma_threshold": AUTOMATION_CONFIDENCE.gamma_threshold,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        },
        "trace": [
            {
                "agent": "governance_gate",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0,
                "status": "complete",
                "next_step": "human_queue_fallback",
                "error": None,
            }
        ],
    }


def build_governance_node():  # noqa: ANN201 - LangGraph node type is internal
    """The gated node: PN-01, then the authorisation, never the other way round."""
    return gated_node(
        confidence_gate,
        _authorise_automated_branch,
        candidate_input_fn=_candidate_input,
        denial_key=PN01_DENIAL_KEY,
    )


def build_governance_router():  # noqa: ANN201
    """`route_on_denial`: denial → fallback node, otherwise → finalize."""
    return route_on_denial(
        "governance_fallback",
        "finalize",
        denial_key=PN01_DENIAL_KEY,
    )
