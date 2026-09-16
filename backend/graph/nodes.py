"""Graph nodes.

Each specialist agent is wrapped in a node that records the trace entry and
guarantees that a failure degrades the run rather than breaking it.

**Where the governance gates go in Phase 4.** `agent_node` is the seam. VSL's
`gated_node` wraps a node and, on denial, returns a state update instead of
raising, so a conditional edge can route the run. That composes with this
wrapper without changing any agent. Phase 2 adds no gate, no PreNode, no
Invariant and no ledger write -- a placeholder that always passed would be a
false claim of governance, which docs/GOVERNANCE_POLICY_CATALOGUE.md rules out.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from agents.base import ClaimsAgent
from agents.contracts import AgentStatus
from graph.state import ClaimsWorkflowState, agent_context

logger = logging.getLogger("claims.workflow")


def agent_node(agent: ClaimsAgent) -> Callable[[ClaimsWorkflowState], dict[str, Any]]:
    """Turn an agent into a LangGraph node."""

    def node(state: ClaimsWorkflowState) -> dict[str, Any]:
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        claim_id = state.get("claim_id", "unknown")

        logger.info("agent.start agent=%s claim_id=%s", agent.name, claim_id)

        result, payload = agent.run(agent_context(state))

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "agent.finish agent=%s claim_id=%s status=%s next_step=%s duration_ms=%d",
            agent.name,
            claim_id,
            result.status.value,
            result.next_step,
            duration_ms,
        )

        update: dict[str, Any] = {
            "results": {agent.name: result.model_dump(mode="json")},
            "payloads": {agent.name: payload} if payload is not None else {},
            "trace": [
                {
                    "agent": agent.name,
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "status": result.status.value,
                    "next_step": result.next_step,
                    "error": result.error,
                }
            ],
        }

        if result.status is AgentStatus.FAILED:
            update["errors"] = [
                {
                    "agent": agent.name,
                    "kind": "agent_failure",
                    "message": result.error or "The agent did not complete.",
                }
            ]

        return update

    node.__name__ = f"{agent.name}_node"
    return node
