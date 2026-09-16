"""The shared claims workflow state.

Design constraints, in the order they mattered:

1. **Each agent reads what it needs and writes only its own slot.** Agents never
   overwrite each other, so a re-run or a reordering cannot silently corrupt an
   earlier result.

2. **Results stay traceable.** `trace` records every node that ran, when, and how
   it went. That is what makes Phase 4's audit possible -- the VerbaLedger will
   record governance decisions, and this records workflow execution. They are
   different things and stay separate.

3. **Governance can be inserted later without redesign.** Gates need a claim
   candidate, a recommendation and a confidence in known places, plus somewhere
   to record a denial. `recommendation`, `confidence` and `halt` exist for that;
   Phase 4 adds gate nodes around the existing ones rather than rewriting them.

4. **Human review can arrive without redesign.** `halt` already stops the run
   with a reason, which is the shape a fallback route needs.

5. **No unnecessary fields.** Every key below is read by something.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict


def _merge_dict(left: dict | None, right: dict | None) -> dict:
    """Reducer: later writes win per key, earlier keys survive."""
    return {**(left or {}), **(right or {})}


def _append(left: list | None, right: list | None) -> list:
    """Reducer: accumulate, never replace."""
    return [*(left or []), *(right or [])]


class TraceEntry(TypedDict, total=False):
    agent: str
    started_at: str
    finished_at: str
    duration_ms: int
    status: str
    next_step: str | None
    error: str | None


class WorkflowError(TypedDict, total=False):
    agent: str
    kind: str
    message: str


class ClaimsWorkflowState(TypedDict, total=False):
    """State passed between LangGraph nodes."""

    # -- inputs (written once, before the graph runs) ---------------------
    claim_id: str
    claim: dict[str, Any]

    # -- per-agent envelopes: agent name -> AgentResult as a dict ----------
    results: Annotated[dict[str, Any], _merge_dict]

    # -- per-agent payloads: agent name -> structured payload -------------
    payloads: Annotated[dict[str, Any], _merge_dict]

    # -- execution record --------------------------------------------------
    trace: Annotated[list[TraceEntry], _append]
    errors: Annotated[list[WorkflowError], _append]

    # -- routing -----------------------------------------------------------
    halt: bool
    halt_reason: str | None

    # -- Phase 3: the escalation node's output ------------------------------
    routing: dict[str, Any]
    """The RoutingDecision. Where a Phase 4 gate reads the recommendation from."""

    customer_context: dict[str, Any]
    """Operational policyholder fields only — support flag, accessibility, contact."""

    # -- Phase 4: the workflow-level VSL gate --------------------------------
    governance_gate: dict[str, Any]
    """PN-01's decision at the graph's own commitment point (CP-11). The
    authoritative, ledger-writing gate is at the side effect in ReviewService."""

    # -- final output (written by the finalize node) -----------------------
    intelligence: dict[str, Any]


AgentName = Literal["intake", "policy", "validation", "assessment", "fraud_risk"]

AGENT_ORDER: tuple[str, ...] = (
    "intake",
    "policy",
    "validation",
    "assessment",
    "fraud_risk",
)

NODE_ORDER: tuple[str, ...] = (*AGENT_ORDER, "escalation", "governance_gate")
"""Every node that appears in the trace. Neither `escalation` nor
`governance_gate` is an agent: the first evaluates business rules over what the
agents produced, the second is the VSL PreNode gating the workflow's commitment
to the automated branch."""


def initial_state(claim: dict[str, Any]) -> ClaimsWorkflowState:
    return {
        "claim_id": claim.get("claim_id", ""),
        "claim": claim,
        "results": {},
        "payloads": {},
        "trace": [],
        "errors": [],
        "halt": False,
        "halt_reason": None,
    }


def agent_context(state: ClaimsWorkflowState) -> dict[str, Any]:
    """What a node hands its agent: the claim plus every prior payload."""
    payloads = state.get("payloads") or {}
    return {
        "claim_id": state.get("claim_id"),
        "claim": state.get("claim") or {},
        "intake_payload": payloads.get("intake"),
        "policy_payload": payloads.get("policy"),
        "validation_payload": payloads.get("validation"),
        "assessment_payload": payloads.get("assessment"),
        "risk_payload": payloads.get("fraud_risk"),
    }
