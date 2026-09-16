"""The risk router.

Evaluates every escalation rule against the Phase 2 agent output and produces one
`RoutingDecision`.

How it decides:

  * **All** applicable rules fire, so a claim that is both high-value and risky
    says both. "Why was this escalated?" gets a list, not a guess.
  * The **outcome** comes from the first rule that fired, in the Phase 0
    precedence order. Safety first, then cover basis, then everything else.
  * The **priority** is the strongest across every reason, so a standard-priority
    claim that also has an urgent reason is urgent.
  * `AUTOMATED_PATH_RECOMMENDED` is what is left when no rule fires. It is never
    a default and never a decision — Phase 4's PreNode and Invariants decide
    whether such a claim may actually be handled without a person.

The router does not read the model. Every input is a rule-derived value from the
Phase 2 payloads, so routing is deterministic and reproducible.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.domain.claim_state import ClaimState
from app.domain.thresholds import Thresholds, get_thresholds
from routing.contracts import (
    EscalationReason,
    ReviewPriority,
    ReviewType,
    RoutingDecision,
    RoutingOutcome,
)
from routing.rules import ESCALATION_RULES, EvaluationContext, Rule

logger = logging.getLogger("claims.routing")

_PRIORITY_ORDER = {
    ReviewPriority.STANDARD: 0,
    ReviewPriority.HIGH: 1,
    ReviewPriority.URGENT: 2,
}

_SPECIALIST_CODES = {"E-10_ELEVATED_RISK"}

_AUTOMATED_SUMMARY = (
    "No escalation rule fired, so the claim continues on the automated path. This "
    "is a routing outcome, not an approval — the claim has not been assessed for "
    "payment and no cover decision has been made."
)


class RiskRouter:
    """Turns claims intelligence into a routing decision."""

    def __init__(
        self,
        thresholds: Thresholds | None = None,
        rules: tuple[Rule, ...] | None = None,
    ) -> None:
        self._thresholds = thresholds or get_thresholds()
        # Injected rather than imported at call time so a test can substitute a
        # rule set, and so the rule catalogue is an explicit dependency rather
        # than a module-level import nobody notices.
        self._rules = rules if rules is not None else ESCALATION_RULES

    def route(
        self,
        *,
        claim: dict[str, Any],
        payloads: dict[str, Any],
        agent_results: dict[str, Any],
        customer: dict[str, Any] | None = None,
        degraded: bool = False,
    ) -> RoutingDecision:
        context = EvaluationContext(
            claim=claim or {},
            intake=payloads.get("intake") or {},
            policy=payloads.get("policy") or {},
            validation=payloads.get("validation") or {},
            assessment=payloads.get("assessment") or {},
            risk=payloads.get("fraud_risk") or {},
            customer=customer or {},
            agent_results=agent_results or {},
            degraded=degraded,
            thresholds=self._thresholds,
        )

        reasons: list[EscalationReason] = []
        for rule in self._rules:
            try:
                reason = rule(context)
            except Exception as exc:  # noqa: BLE001 - a broken rule must not clear a claim
                logger.exception("Routing rule %s failed", rule.__name__, exc_info=exc)
                reasons.append(self._rule_failure(rule.__name__))
                continue
            if reason is not None:
                reasons.append(reason)

        decision = self._decide(reasons, len(self._rules))

        logger.info(
            "routing.decision claim_id=%s outcome=%s priority=%s reasons=%s "
            "recommended_state=%s",
            claim.get("claim_id"),
            decision.outcome.value,
            decision.priority.value,
            ",".join(r.code for r in decision.reasons) or "none",
            decision.recommended_claim_state.value,
        )
        return decision

    # -- internals ---------------------------------------------------------

    def _decide(
        self, reasons: list[EscalationReason], rules_evaluated: int
    ) -> RoutingDecision:
        now = datetime.now(timezone.utc).isoformat()

        if not reasons:
            return RoutingDecision(
                outcome=RoutingOutcome.AUTOMATED_PATH_RECOMMENDED,
                priority=ReviewPriority.STANDARD,
                review_type=None,
                reasons=[],
                primary_reason_code=None,
                summary=_AUTOMATED_SUMMARY,
                explanation=[
                    "No escalation rule fired across "
                    f"{rules_evaluated} rules from the Phase 0 decision framework."
                ],
                recommended_claim_state=ClaimState.ASSESSMENT,
                decided_at=now,
                rules_evaluated=rules_evaluated,
            )

        primary = reasons[0]
        outcome = primary.outcome
        priority = max(reasons, key=lambda r: _PRIORITY_ORDER[r.priority]).priority

        if outcome is RoutingOutcome.INFORMATION_REQUIRED:
            recommended_state = ClaimState.INFORMATION_REQUIRED
            review_type = None
            summary = (
                "The claim needs information from the customer before it can be "
                "assessed. It has not been declined or delayed for any other reason."
            )
        else:
            recommended_state = ClaimState.HUMAN_REVIEW
            if priority is ReviewPriority.URGENT:
                review_type = ReviewType.PRIORITY
            elif any(r.code in _SPECIALIST_CODES for r in reasons):
                review_type = ReviewType.SPECIALIST
            else:
                review_type = ReviewType.STANDARD
            summary = (
                f"Human review required — {primary.label.lower()}. "
                f"{len(reasons)} escalation reason(s) recorded."
            )

        return RoutingDecision(
            outcome=outcome,
            priority=priority,
            review_type=review_type,
            reasons=reasons,
            primary_reason_code=primary.code,
            summary=summary,
            explanation=[self._explain(reason) for reason in reasons],
            recommended_claim_state=recommended_state,
            decided_at=now,
            rules_evaluated=rules_evaluated,
        )

    @staticmethod
    def _explain(reason: EscalationReason) -> str:
        """One reader-facing line per reason, naming rule, observation and threshold."""
        parts = [f"{reason.label}: {reason.detail}"]
        if reason.observed_value:
            parts.append(f"Observed: {reason.observed_value}.")
        if reason.threshold_value:
            parts.append(f"Compared against: {reason.threshold_value}.")
        parts.append(
            "Source: "
            + ("an AI finding" if reason.basis.value == "ai_finding" else "a business rule")
            + f" ({reason.rule_reference})."
        )
        if reason.assumption:
            parts.append(f"[{reason.assumption}]")
        return " ".join(parts)

    @staticmethod
    def _rule_failure(rule_name: str) -> EscalationReason:
        """A rule that raises escalates. It never silently clears a claim."""
        from routing.contracts import ReasonBasis

        return EscalationReason(
            code="E-16_ROUTING_RULE_FAILED",
            label="Routing rule could not be evaluated",
            detail=(
                "An escalation rule could not be evaluated, so the claim is routed to "
                "a person rather than treated as clear."
            ),
            basis=ReasonBasis.BUSINESS_RULE,
            priority=ReviewPriority.HIGH,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/HUMAN_ESCALATION_POLICY.md §2 E-16 (fail closed)",
            observed_value=rule_name,
        )
