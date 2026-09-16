"""Claims intelligence service.

Runs the LangGraph workflow for a claim and stores the result.

Two boundaries this service keeps, deliberately:

1. **It does not touch the claim record.** The analysis is written to its own
   store. Changing `claim_state` is commitment point CP-09, a governed write --
   Phase 2 recommends a state, it does not set one.

2. **A failure never looks like success.** If the graph itself falls over, the
   service raises a handled application error; it does not return a partial
   result that a caller might read as "analysed, nothing found".

**Phase 3 changed one of those.** The analysis still does not decide a claim, but
it now *applies the routing decision*: a claim needing a person moves to Human
Review and appears in the queue, and a claim needing information moves to
Information Required. That is the point of Phase 3 — human review is a real
workflow state, not a label. Those writes are commitment points CP-09 and CP-12,
and they happen in `ReviewService`, which is where the Phase 4 gate goes.

What still never happens here: approving, declining or settling a claim, or
contacting a customer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.errors import ClaimAnalysisError, ClaimNotFoundError
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.claim_repository import ClaimRepository
from app.schemas.intelligence import ClaimIntelligenceResult
from app.services.review_service import ReviewService
from graph.state import initial_state

logger = logging.getLogger("claims.workflow")


def _llm_governance_summary(intelligence: dict[str, Any]) -> dict[str, Any]:
    """Roll up the CP-13 gate decisions the agents recorded.

    `blocked` is the number of LLM calls the gate stopped BEFORE the provider
    was reached. It is not "calls whose answer we ignored" -- there is no such
    category, because a denial returns before the provider call exists.
    """
    results = (intelligence.get("agent_results") or {}).values()
    decisions = [r.get("narration_governance") for r in results if r.get("narration_governance")]

    permitted = [d for d in decisions if d.get("llm_called")]
    blocked = [d for d in decisions if not d.get("llm_called")]

    return {
        "gate": "llm-narration",
        "commitment_point": "CP-13",
        "governed_calls": len(decisions),
        "permitted": len(permitted),
        "blocked": len(blocked),
        "llm_calls_made": len(permitted),
        "invariants_violated": sorted(
            {d["invariant_violated"] for d in blocked if d.get("invariant_violated")}
        ),
        "terminal_states": sorted(
            {d["terminal_state"] for d in blocked if d.get("terminal_state")}
        ),
        "blocked_reasons": sorted({d["reason"] for d in blocked if d.get("reason")}),
        "ledger_entry_ids": [e for d in decisions for e in (d.get("ledger_entry_ids") or [])],
        "note": (
            "The gate runs before the provider call. A blocked call was never "
            "made: no request was built and no key was read."
        ),
    }


def _any_narration_degraded(intelligence: dict[str, Any]) -> bool:
    """True when any agent's narrative came from the fallback, not the model.

    Read from `narrative_source`, which the agents already record as
    e.g. "gemini (degraded)". Deriving it here rather than adding a field to
    `AgentResult` keeps the Phase 2 agent contract untouched.
    """
    results = intelligence.get("agent_results") or {}
    return any(
        "(degraded)" in (r.get("narrative_source") or "") for r in results.values()
    )


class ClaimIntelligenceService:
    def __init__(
        self,
        *,
        claims: ClaimRepository,
        analyses: AnalysisRepository,
        graph: Any,
        reviews: ReviewService | None = None,
        llm_name: str = "stub",
        llm_model: str | None = None,
    ) -> None:
        self._claims = claims
        self._analyses = analyses
        self._graph = graph
        self._reviews = reviews
        self._llm_name = llm_name
        self._llm_model = llm_model

    async def analyse(
        self, claim_id: str, *, force: bool = False
    ) -> ClaimIntelligenceResult:
        """Run the workflow and apply its routing decision.

        **Async from Phase 4.** The VSL gates are `async` — that is the
        framework's contract, and PreNode monitors and Invariant rules are
        awaited. Running them on a side thread would let a synchronous caller
        return before the gate resolved, which is precisely the pre-commitment
        property F1 asserts. So the call chain is awaited end to end instead.
        """
        claim = self._claims.get(claim_id)
        if claim is None:
            raise ClaimNotFoundError()

        if not force:
            existing = self._analyses.latest_for_claim(claim_id)
            if existing is not None:
                logger.info("workflow.cached claim_id=%s", claim_id)
                return ClaimIntelligenceResult.model_validate(existing)

        logger.info(
            "workflow.start claim_id=%s claim_state=%s llm=%s",
            claim_id,
            claim.get("claim_state"),
            self._llm_name,
        )

        try:
            final_state = await self._graph.ainvoke(initial_state(claim))
        except Exception as exc:  # noqa: BLE001 - surfaces as a handled error
            logger.exception("workflow.failed claim_id=%s", claim_id, exc_info=exc)
            raise ClaimAnalysisError() from exc

        intelligence = final_state.get("intelligence")
        if not intelligence:
            logger.error("workflow.no_result claim_id=%s", claim_id)
            raise ClaimAnalysisError()

        # Provider metadata, so a reader can tell what actually produced the
        # prose. `llm_degraded` is the honest one: it is True when the provider
        # was configured but could not be reached, and the deterministic
        # fallback wrote the narrative instead.
        intelligence["llm_provider"] = self._llm_name
        intelligence["llm_model"] = self._llm_model
        intelligence["llm_degraded"] = _any_narration_degraded(intelligence)
        intelligence["llm_governance"] = _llm_governance_summary(intelligence)

        # Apply the routing decision: claim-state transition (CP-09) and queue
        # placement (CP-12). Both live in ReviewService, behind one call, so
        # Phase 4 has a single site to gate.
        if self._reviews is not None:
            updated_claim = await self._reviews.apply_routing(claim, intelligence)
            if updated_claim is not None:
                intelligence["claim_state"] = updated_claim.get("claim_state")
                intelligence["claim_state_changed"] = (
                    updated_claim.get("claim_state") != claim.get("claim_state")
                )
                intelligence["routing_applied"] = True

        result = ClaimIntelligenceResult.model_validate(intelligence)

        # Storing the analysis writes to its own store; it never mutates a claim.
        self._analyses.save(result.model_dump(mode="json"))

        logger.info(
            "workflow.complete claim_id=%s analysis_id=%s next_step=%s degraded=%s agents=%d",
            claim_id,
            result.analysis_id,
            result.recommended_next_step.value,
            result.degraded,
            len(result.agent_results),
        )
        return result

    def latest(self, claim_id: str) -> ClaimIntelligenceResult | None:
        if self._claims.get(claim_id) is None:
            raise ClaimNotFoundError()
        stored = self._analyses.latest_for_claim(claim_id)
        return ClaimIntelligenceResult.model_validate(stored) if stored else None
