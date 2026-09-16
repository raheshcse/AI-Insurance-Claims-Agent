"""Human review service.

Two responsibilities, kept in one place because both are claim-state writes:

1. **Applying a routing decision** — putting a claim into Human Review or
   Information Required and creating its queue entry.
2. **Applying a reviewer's action** — what a person decides afterwards.

=============================================================================
GOVERNANCE — Phase 4. This is the enforcement site.

`apply_routing()` is commitment point **CP-09** (claim-state write) and
**CP-12** (queue placement). The X-Verba/VSL gate runs here, and the write is
handed to it as a callable:

    outcome, _ = await govern_automated_route(candidate, perform=_write)

`_write` is invoked once, on the last line of the gate's proceed path. Every
denial path inside the gate returns before it. So a denied automated route is
not "checked and then skipped" — the code that would take it is unreachable.

Governance can only ever make the outcome MORE conservative:
  PreNode denial      -> Human Review instead of the automated route
  Invariant violation -> Human Review, automation suspended, TerminalState
=============================================================================

What this service will never do: approve a claim for payment, set a reserve,
settle anything, or contact a customer. `complete_review` records that a person
finished looking at a claim. That is all it means.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.domain.claim_state import ClaimState, InternalStatus, is_transition_allowed
from app.errors import (
    ClaimNotFoundError,
    InvalidReviewActionError,
    QueueEntryNotFoundError,
)
from app.repositories.claim_repository import ClaimRepository
from app.repositories.review_queue_repository import ReviewQueueRepository
from app.schemas.review import (
    EMERGENCY_REASON_CODE,
    ROUTING_INTERNAL_STATUS,
    VULNERABLE_REASON_CODE,
    ClaimReviewDetail,
    QueueEntry,
    QueueEntrySummary,
    QueueStatus,
    ReEnablementRequest,
    ReEnablementResponse,
    ReviewAction,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewQueueResponse,
)
from governance.gates import (
    GovernanceOutcome,
    govern_automated_route,
    re_enable_automation,
    suspensions,
)
from governance.policy import AUTOMATION_CONFIDENCE
from routing.contracts import ReviewPriority, RoutingOutcome

logger = logging.getLogger("claims.review")

_PRIORITY_RANK = {
    ReviewPriority.URGENT.value: 0,
    ReviewPriority.HIGH.value: 1,
    ReviewPriority.STANDARD.value: 2,
}

_ACTIONS_BY_QUEUE_STATUS: dict[str, list[ReviewAction]] = {
    QueueStatus.OPEN.value: [
        ReviewAction.START_REVIEW,
        ReviewAction.REQUEST_INFORMATION,
        ReviewAction.REFER_TO_SPECIALIST,
        ReviewAction.COMPLETE_REVIEW,
    ],
    QueueStatus.IN_REVIEW.value: [
        ReviewAction.REQUEST_INFORMATION,
        ReviewAction.REFER_TO_SPECIALIST,
        ReviewAction.COMPLETE_REVIEW,
    ],
    QueueStatus.CLOSED.value: [],
}


# ---------------------------------------------------------------------------
# The governance candidate, and how the outcome is published.
#
# These are module-level on purpose: building the candidate is a pure reading of
# the intelligence result, not a service behaviour, and both the service and the
# tests want it without constructing repositories.
# ---------------------------------------------------------------------------


def _governance_candidate(
    claim: dict[str, Any], intelligence: dict[str, Any]
) -> dict[str, Any]:
    """The facts the VSL policy evaluates. Nothing else reaches the gates.

    Deliberately narrow. A gate that can see the whole claim is a gate whose
    behaviour nobody can predict from reading it; this is the contract in
    `govern_automated_route`'s docstring and no more.

    Where a fact is genuinely unknown it stays `None` rather than being guessed
    in either direction. `policy.py` decides what unknown means for each rule --
    INV-02 treats it as "not a breach", INV-03 treats uncertain cover as one --
    and that reasoning belongs there, not here.
    """
    routing = intelligence.get("routing") or {}
    policy = intelligence.get("policy_assessment") or {}
    interpretation = policy.get("interpretation") or {}
    assessment = intelligence.get("damage_assessment") or {}
    confidence = (intelligence.get("overall_confidence") or {}).get("value")

    return {
        "claim_id": claim.get("claim_id", ""),
        "confidence": float(confidence) if confidence is not None else 0.0,
        # Whether the layer above ATTEMPTED the automated action. It no longer
        # decides whether the Invariants run -- they always do, on the claim's
        # own facts -- only whether a violation is routine (routing and
        # governance agree) or an incident (a bug tried to take a prohibited
        # action, so the claim is suspended).
        "automated_route_proposed": routing.get("outcome")
        == RoutingOutcome.AUTOMATED_PATH_RECOMMENDED.value,
        "policy_in_force_at_loss": interpretation.get("in_force_at_date_of_loss"),
        "peril_covered": interpretation.get("peril_covered"),
        "estimated_claim_value": assessment.get("estimated_claim_value"),
        "exclusions_possibly_engaged": list(
            interpretation.get("exclusions_possibly_engaged") or []
        ),
        "cover_certainty": interpretation.get("cover_certainty"),
    }


def _observed_value(governance: GovernanceOutcome) -> float | None:
    """The claim value INV-02 judged, so the ledger and the UI can show the
    comparison rather than just the verdict."""
    return getattr(governance, "observed_value", None)


def _threshold_value(governance: GovernanceOutcome) -> float | None:
    if governance.invariant_violated == "automated-authority-limit":
        from governance.policy import AUTOMATED_AUTHORITY_LIMIT_NZD

        return AUTOMATED_AUTHORITY_LIMIT_NZD
    return None


def _governance_payload(governance: GovernanceOutcome) -> dict[str, Any]:
    """The governance decision, as the API and the queue publish it.

    Every field a reviewer or an auditor needs to see why automation did or did
    not proceed, including the ledger entries that record it. `assurance_level`
    is reported as VSL derived it -- LOW for an output-layer gate -- and is not
    dressed up.
    """
    return {
        "action": governance.action,
        "permitted": governance.permitted,
        "automated_action_allowed": governance.automated_action_allowed,
        "automated_action_attempted": governance.automated_action_attempted,
        "observed_value": _observed_value(governance),
        "threshold_value": _threshold_value(governance),
        "decision_id": governance.decision_id,
        "claim_id": governance.claim_id,
        "specification": governance.specification,
        "pre_node": AUTOMATION_CONFIDENCE.name,
        "pre_node_denied": governance.pre_node_denied,
        "denial_reason": governance.denial_reason,
        "invariant_violated": governance.invariant_violated,
        "terminal_state": governance.terminal_state,
        "fallback": governance.fallback,
        "assurance_level": governance.assurance_level,
        "gamma_threshold": governance.gamma_threshold,
        "confidence": (
            round(governance.confidence, 4) if governance.confidence is not None else None
        ),
        "confidence_floor": (
            round(governance.confidence_floor, 4)
            if governance.confidence_floor is not None
            else None
        ),
        "ledger_entry_ids": list(governance.ledger_entry_ids),
        "side_effect_performed": governance.side_effect_performed,
        "automation_suspended": governance.action == "suspended",
    }


class ReviewService:
    def __init__(
        self,
        *,
        claims: ClaimRepository,
        queue: ReviewQueueRepository,
    ) -> None:
        self._claims = claims
        self._queue = queue

    # -----------------------------------------------------------------
    # 1. Applying a routing decision
    # -----------------------------------------------------------------

    async def apply_routing(
        self, claim: dict[str, Any], intelligence: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Gate, then move the claim per the routing decision.

        Returns the updated claim record, or None when nothing changed.
        """
        routing = intelligence.get("routing") or {}
        outcome = routing.get("outcome")
        if not outcome:
            return None

        claim_id = claim["claim_id"]

        # ---- CP-09 / CP-12: the governed commitment ----------------------
        governance, _ = await govern_automated_route(
            _governance_candidate(claim, intelligence),
            perform=lambda: self._apply_outcome(claim, intelligence, routing, outcome),
        )
        intelligence["governance"] = _governance_payload(governance)

        if governance.permitted:
            # The write already happened, inside the gate.
            return self._claims.get(claim_id)

        # Denied. The automated route was never taken; fall back, more
        # conservatively than the business rules asked for.
        return self._apply_governance_fallback(claim, intelligence, governance)

    # -- the governed side effect -------------------------------------------

    def _apply_outcome(
        self,
        claim: dict[str, Any],
        intelligence: dict[str, Any],
        routing: dict[str, Any],
        outcome: str,
    ) -> dict[str, Any] | None:
        """The side effect. Reachable only from the gate's proceed path."""
        claim_id = claim["claim_id"]
        previous_state = ClaimState(claim.get("claim_state", ClaimState.SUBMITTED.value))
        target_state = ClaimState(routing["recommended_claim_state"])

        if previous_state is target_state:
            updated = claim
        elif not is_transition_allowed(previous_state, target_state):
            # The state model is authoritative. A routing decision that would
            # need an impossible transition is refused rather than forced.
            logger.warning(
                "routing.transition_refused claim_id=%s from=%s to=%s",
                claim_id,
                previous_state.value,
                target_state.value,
            )
            return None
        else:
            updated = dict(claim)
            updated["claim_state"] = target_state.value
            updated["internal_status"] = ROUTING_INTERNAL_STATUS.get(outcome)
            updated["updated_at"] = datetime.now(timezone.utc).isoformat()

            # --- CP-09 side effect. The Phase 4 gate goes immediately above. ---
            self._claims.save(updated)

            logger.info(
                "claim.state_transition claim_id=%s from=%s to=%s reason=%s source=routing",
                claim_id,
                previous_state.value,
                target_state.value,
                routing.get("primary_reason_code") or "none",
            )

        if outcome == RoutingOutcome.HUMAN_REVIEW_REQUIRED.value:
            self._enqueue(updated, intelligence, routing)
        else:
            # A claim that no longer needs a person should not sit in the queue.
            if self._queue.get(claim_id):
                self._queue.remove(claim_id)
                logger.info("queue.removed claim_id=%s reason=%s", claim_id, outcome)

        return updated

    def _apply_governance_fallback(
        self,
        claim: dict[str, Any],
        intelligence: dict[str, Any],
        governance: GovernanceOutcome,
    ) -> dict[str, Any] | None:
        """Where a governance denial lands: a person, always.

        A PreNode denial is the declared fallback (ROUTE_TO_HUMAN_QUEUE). An
        Invariant violation additionally suspends automation for the claim and
        records the terminal state, so nothing automated runs on it again until
        a claims authority re-enables it.
        """
        claim_id = claim["claim_id"]
        previous_state = ClaimState(claim.get("claim_state", ClaimState.SUBMITTED.value))
        suspended = governance.action == "suspended"

        # Three denial shapes, three internal statuses. Collapsing them would
        # lose the distinction a reviewer acts on: a suspended claim needs a
        # claims authority, a denied automated action just needs a reviewer.
        if suspended:
            internal_status = InternalStatus.AUTOMATION_SUSPENDED.value
        elif governance.action == "action_denied":
            internal_status = InternalStatus.ASSESSMENT_COMPLETE.value
        else:
            internal_status = InternalStatus.GOVERNANCE_DENIED_PRENODE.value

        updated = claim
        if previous_state is not ClaimState.HUMAN_REVIEW and is_transition_allowed(
            previous_state, ClaimState.HUMAN_REVIEW
        ):
            updated = dict(claim)
            updated["claim_state"] = ClaimState.HUMAN_REVIEW.value
            updated["internal_status"] = internal_status
            updated["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._claims.save(updated)
        elif claim.get("internal_status") != internal_status:
            updated = dict(claim)
            updated["internal_status"] = internal_status
            updated["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._claims.save(updated)

        logger.warning(
            "governance.fallback_applied claim_id=%s action=%s internal_status=%s "
            "invariant=%s terminal_state=%s decision_id=%s",
            claim_id,
            governance.action,
            internal_status,
            governance.invariant_violated,
            governance.terminal_state,
            governance.decision_id,
        )

        routing = intelligence.get("routing") or {}
        self._enqueue(updated, intelligence, routing, governance=governance)
        return updated

    def _enqueue(
        self,
        claim: dict[str, Any],
        intelligence: dict[str, Any],
        routing: dict[str, Any],
        governance: GovernanceOutcome | None = None,
    ) -> None:
        claim_id = claim["claim_id"]
        existing = self._queue.get(claim_id)
        now = datetime.now(timezone.utc).isoformat()

        reasons = routing.get("reasons") or []
        codes = {r.get("code") for r in reasons}
        assessment = intelligence.get("damage_assessment") or {}
        risk = intelligence.get("risk_assessment") or {}
        summary = intelligence.get("claim_summary") or {}
        confidence = (intelligence.get("overall_confidence") or {}).get("value")

        entry = {
            "queue_id": (existing or {}).get("queue_id") or f"RQ-{uuid.uuid4().hex[:10].upper()}",
            "claim_id": claim_id,
            "claim_state": claim.get("claim_state"),
            "internal_status": claim.get("internal_status"),
            "queue_status": (existing or {}).get("queue_status") or QueueStatus.OPEN.value,
            "priority": routing.get("priority"),
            "review_type": routing.get("review_type"),
            "primary_reason_code": routing.get("primary_reason_code"),
            "primary_reason_label": reasons[0]["label"] if reasons else None,
            "reason_count": len(reasons),
            "reasons": reasons,
            "explanation": routing.get("explanation") or [],
            "routing_summary": routing.get("summary"),
            "recommended_next_step": intelligence.get("recommended_next_step"),
            "analysis_id": intelligence.get("analysis_id"),
            "customer_name": summary.get("customer_name"),
            "policy_number": summary.get("policy_number"),
            "peril": summary.get("peril"),
            "date_of_loss": str(summary.get("date_of_loss")) if summary.get("date_of_loss") else None,
            "estimated_claim_value": assessment.get("estimated_claim_value"),
            "complexity_band": assessment.get("complexity_band"),
            "risk_level": risk.get("risk_level"),
            "confidence": confidence,
            "vulnerable_customer": VULNERABLE_REASON_CODE in codes,
            "emergency": EMERGENCY_REASON_CODE in codes,
            "created_at": (existing or {}).get("created_at") or now,
            "updated_at": now,
            "assigned_to": (existing or {}).get("assigned_to"),
            "history": (existing or {}).get("history") or [],
            "governance": _governance_payload(governance) if governance else None,
            "automation_suspended": bool(governance and governance.action == "suspended"),
        }

        self._queue.upsert(entry)
        logger.info(
            "queue.%s claim_id=%s priority=%s type=%s reasons=%d vulnerable=%s emergency=%s",
            "updated" if existing else "created",
            claim_id,
            entry["priority"],
            entry["review_type"],
            entry["reason_count"],
            entry["vulnerable_customer"],
            entry["emergency"],
        )

    # -----------------------------------------------------------------
    # 2. Reading the queue
    # -----------------------------------------------------------------

    def list_queue(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
    ) -> ReviewQueueResponse:
        entries = self._queue.list_entries()

        filtered = [
            e
            for e in entries
            if (status is None or e.get("queue_status") == status)
            and (priority is None or e.get("priority") == priority)
        ]

        # Urgent first, then high, then oldest first within a band. A queue that
        # does not surface the emergency claim first is not doing its job.
        filtered.sort(
            key=lambda e: (
                _PRIORITY_RANK.get(e.get("priority", "standard"), 3),
                e.get("created_at") or "",
            )
        )

        return ReviewQueueResponse(
            total=len(filtered),
            open_count=sum(
                1 for e in entries if e.get("queue_status") != QueueStatus.CLOSED.value
            ),
            urgent_count=sum(
                1
                for e in entries
                if e.get("priority") == ReviewPriority.URGENT.value
                and e.get("queue_status") != QueueStatus.CLOSED.value
            ),
            entries=[QueueEntrySummary.model_validate(e) for e in filtered],
        )

    def get_entry(self, claim_id: str) -> QueueEntry:
        entry = self._queue.get(claim_id)
        if entry is None:
            raise QueueEntryNotFoundError()
        return QueueEntry.model_validate(entry)

    def review_detail(
        self, claim_id: str, intelligence: dict[str, Any] | None
    ) -> ClaimReviewDetail:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise ClaimNotFoundError()

        raw_entry = self._queue.get(claim_id)
        entry = QueueEntry.model_validate(raw_entry) if raw_entry else None
        queue_status = (raw_entry or {}).get("queue_status", QueueStatus.CLOSED.value)

        # The registry, not the stored row, is authoritative about a live
        # suspension: a person may have re-enabled automation since the entry
        # was written, and a stale "suspended" badge on a claim that is no
        # longer suspended is the kind of wrong that gets believed.
        suspended = suspensions.get(claim_id) is not None

        return ClaimReviewDetail(
            claim_id=claim_id,
            claim_state=ClaimState(claim.get("claim_state", ClaimState.SUBMITTED.value)),
            internal_status=claim.get("internal_status"),
            queue_entry=entry,
            customer_report=claim.get("fnol") or {},
            intelligence=intelligence,
            available_actions=_ACTIONS_BY_QUEUE_STATUS.get(queue_status, []),
            automation_suspended=suspended,
            governance=(entry.governance if entry else None),
        )

    # -----------------------------------------------------------------
    # 3. Applying a reviewer's action
    # -----------------------------------------------------------------

    def perform_action(
        self, claim_id: str, request: ReviewActionRequest
    ) -> ReviewActionResponse:
        claim = self._claims.get(claim_id)
        if claim is None:
            raise ClaimNotFoundError()

        entry = self._queue.get(claim_id)
        if entry is None:
            raise QueueEntryNotFoundError()

        queue_status = entry.get("queue_status", QueueStatus.OPEN.value)
        allowed = _ACTIONS_BY_QUEUE_STATUS.get(queue_status, [])
        if request.action not in allowed:
            raise InvalidReviewActionError(
                f"'{request.action.value}' is not available while the review is "
                f"'{queue_status}'."
            )

        previous_state = ClaimState(claim.get("claim_state", ClaimState.HUMAN_REVIEW.value))
        now = datetime.now(timezone.utc).isoformat()

        target_state = previous_state
        internal_status = claim.get("internal_status")
        new_queue_status = queue_status

        if request.action is ReviewAction.START_REVIEW:
            new_queue_status = QueueStatus.IN_REVIEW.value

        elif request.action is ReviewAction.REQUEST_INFORMATION:
            target_state = ClaimState.INFORMATION_REQUIRED
            internal_status = InternalStatus.AWAITING_CUSTOMER_RESPONSE.value
            new_queue_status = QueueStatus.CLOSED.value

        elif request.action is ReviewAction.REFER_TO_SPECIALIST:
            internal_status = InternalStatus.SPECIALIST_REFERRAL.value
            new_queue_status = QueueStatus.OPEN.value

        elif request.action is ReviewAction.COMPLETE_REVIEW:
            target_state = ClaimState.APPROVED_COMPLETED
            internal_status = None
            new_queue_status = QueueStatus.CLOSED.value

        if target_state is not previous_state and not is_transition_allowed(
            previous_state, target_state
        ):
            raise InvalidReviewActionError(
                f"A claim in '{previous_state.value}' cannot move to "
                f"'{target_state.value}'."
            )

        if target_state is not previous_state or internal_status != claim.get(
            "internal_status"
        ):
            updated = dict(claim)
            updated["claim_state"] = target_state.value
            updated["internal_status"] = internal_status
            updated["updated_at"] = now

            # --- CP-09 side effect. The Phase 4 gate goes immediately above. ---
            self._claims.save(updated)

            logger.info(
                "claim.state_transition claim_id=%s from=%s to=%s source=human "
                "action=%s reviewer=%s",
                claim_id,
                previous_state.value,
                target_state.value,
                request.action.value,
                request.reviewer,
            )

        history = list(entry.get("history") or [])
        history.append(
            {
                "action": request.action.value,
                "reviewer": request.reviewer,
                "at": now,
                "notes": request.notes,
                "information_requested": request.information_requested,
                "claim_state_before": previous_state.value,
                "claim_state_after": target_state.value,
                "decision_source": "human",
            }
        )

        entry.update(
            {
                "queue_status": new_queue_status,
                "claim_state": target_state.value,
                "internal_status": internal_status,
                "assigned_to": request.reviewer,
                "updated_at": now,
                "history": history,
            }
        )
        if request.action is ReviewAction.REFER_TO_SPECIALIST:
            entry["review_type"] = "specialist_review"

        self._queue.upsert(entry)

        logger.info(
            "review.action claim_id=%s action=%s reviewer=%s queue_status=%s",
            claim_id,
            request.action.value,
            request.reviewer,
            new_queue_status,
        )

        return ReviewActionResponse(
            claim_id=claim_id,
            action=request.action,
            performed_by=request.reviewer,
            performed_at=now,
            previous_claim_state=previous_state,
            claim_state=target_state,
            internal_status=internal_status,
            queue_status=QueueStatus(new_queue_status),
            notes=request.notes,
        )

    # -----------------------------------------------------------------
    # 4. Lifting a TerminalState
    # -----------------------------------------------------------------

    def re_enable_automation(
        self, claim_id: str, request: ReEnablementRequest
    ) -> ReEnablementResponse:
        """The only exit from `claim-automation-suspended`.

        Nothing here recovers automatically, and nothing here is a shortcut: the
        transition is produced by `vsl_core.governance.request_re_enablement`,
        which will not hand back a new Instance without the
        HumanAuthorisedTransition that justifies it. This method only records
        what a person authorised.

        It does not change the claim's state. A claim whose automation was
        suspended stays with its reviewer; re-enabling automation means future
        automated steps are permitted again, not that the claim is resolved.
        """
        claim = self._claims.get(claim_id)
        if claim is None:
            raise ClaimNotFoundError()

        if suspensions.get(claim_id) is None:
            raise InvalidReviewActionError(
                "Automation is not suspended for this claim, so there is nothing "
                "to re-enable."
            )

        try:
            result = re_enable_automation(
                claim_id,
                authorised_by=request.authorised_by,
                root_cause_analysis=request.root_cause_analysis,
                specification_update_proposal=request.specification_update_proposal,
            )
        except ValueError as exc:
            # The framework refused the evidence. Surface it as a review error,
            # not a 500 — the reviewer can fix what they wrote.
            raise InvalidReviewActionError(str(exc)) from exc

        now = datetime.now(timezone.utc).isoformat()
        entry = self._queue.get(claim_id)
        if entry is not None:
            history = list(entry.get("history") or [])
            history.append(
                {
                    "action": "re_enable_automation",
                    "reviewer": request.authorised_by,
                    "at": now,
                    "notes": request.root_cause_analysis,
                    "claim_state_before": claim.get("claim_state"),
                    "claim_state_after": claim.get("claim_state"),
                    "decision_source": "human",
                    "human_authorised_transition_id": result[
                        "human_authorised_transition_id"
                    ],
                }
            )
            entry["history"] = history
            entry["automation_suspended"] = False
            entry["internal_status"] = InternalStatus.ASSESSMENT_COMPLETE.value
            entry["updated_at"] = now
            self._queue.upsert(entry)

        if claim.get("internal_status") == InternalStatus.AUTOMATION_SUSPENDED.value:
            updated = dict(claim)
            updated["internal_status"] = InternalStatus.ASSESSMENT_COMPLETE.value
            updated["updated_at"] = now
            self._claims.save(updated)

        logger.warning(
            "governance.re_enablement_recorded claim_id=%s authorised_by=%s "
            "transition=%s generation=%s",
            claim_id,
            request.authorised_by,
            result["human_authorised_transition_id"],
            result["generation"],
        )

        return ReEnablementResponse(**result)
