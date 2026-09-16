"""The escalation rule catalogue.

Every rule here is one of the E-xx triggers in docs/HUMAN_ESCALATION_POLICY.md §2,
evaluated against the Phase 2 agent payloads. Nothing is invented: each rule cites
the Phase 0 row it implements, and each rule that rests on a proposed number
carries the POC assumption marker so it can never be read as an insurer rule.

Rules are listed in **precedence order** (docs/HUMAN_ESCALATION_POLICY.md §5).
Every applicable rule fires — a claim that is both high-value and risky says so —
but the outcome and priority come from the first match.

One Phase 3 difference from that policy: E-14 (suspension) is absent. Suspension
is what an Invariant violation produces, and Invariants are Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.domain.thresholds import POC_ASSUMPTION_NOTE, Thresholds
from routing.contracts import (
    EscalationReason,
    ReasonBasis,
    ReviewPriority,
    RoutingOutcome,
)


@dataclass(frozen=True)
class EvaluationContext:
    """Everything the rules read. Assembled once, passed to every rule."""

    claim: dict[str, Any]
    intake: dict[str, Any]
    policy: dict[str, Any]
    validation: dict[str, Any]
    assessment: dict[str, Any]
    risk: dict[str, Any]
    customer: dict[str, Any]
    agent_results: dict[str, Any]
    degraded: bool
    thresholds: Thresholds

    @property
    def interpretation(self) -> dict[str, Any]:
        return self.policy.get("interpretation") or {}

    @property
    def policy_facts(self) -> dict[str, Any]:
        return self.policy.get("facts") or {}

    def confidence(self) -> float | None:
        values = [
            r["confidence"]["value"]
            for r in self.agent_results.values()
            if r.get("confidence")
        ]
        return min(values) if values else None


Rule = Callable[[EvaluationContext], EscalationReason | None]


def _money(value: float) -> str:
    return f"NZD {value:,.0f}"


# ---------------------------------------------------------------------------
# 1. Emergency  (E-11, decision row D-13) — safety before process
# ---------------------------------------------------------------------------


def emergency(ctx: EvaluationContext) -> EscalationReason | None:
    """Read from the FNOL, not only from the assessment.

    A claim that short-circuits before the Assessment Agent runs -- missing
    information, no policy -- still has to be caught if someone is unsafe. So the
    signals are read from what the customer actually said, and the assessment's
    band is treated as confirmation rather than as the source of truth.
    """
    damage = (ctx.claim.get("fnol") or {}).get("damage") or {}
    property_details = (ctx.claim.get("fnol") or {}).get("property") or {}

    signals: list[str] = []
    if property_details.get("property_habitable") is False:
        signals.append("the home is reported as not liveable")
    if damage.get("anyone_injured"):
        signals.append("someone was hurt")
    if damage.get("damage_ongoing"):
        signals.append("the damage is ongoing")
    if damage.get("utilities_affected"):
        signals.append("utilities affected: " + ", ".join(damage["utilities_affected"]))

    if not signals and ctx.assessment.get("urgency_band") != "emergency":
        return None

    return EscalationReason(
        code="E-11_EMERGENCY",
        label="Emergency situation",
        detail=(
            "The claim shows emergency indicators — "
            + ("; ".join(signals) if signals else "urgency assessed as emergency")
            + ". Treat as a priority and contact the customer before routine handling."
        ),
        basis=ReasonBasis.AI_FINDING,
        priority=ReviewPriority.URGENT,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/HUMAN_ESCALATION_POLICY.md §4.1 · decision row D-13",
        observed_value="; ".join(signals) if signals else "emergency",
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="intake/assessment",
    )


# ---------------------------------------------------------------------------
# 2. Analysis did not complete  (E-16) — fail closed
# ---------------------------------------------------------------------------


def incomplete_analysis(ctx: EvaluationContext) -> EscalationReason | None:
    if not ctx.degraded:
        return None
    failed = sorted(
        name
        for name, result in ctx.agent_results.items()
        if result.get("status") in {"failed", "degraded"}
    )
    return EscalationReason(
        code="E-16_INCOMPLETE_ANALYSIS",
        label="Automated analysis incomplete",
        detail=(
            "Part of the automated analysis did not complete, so the absence of "
            "findings means unknown rather than clear. A specialist should review."
        ),
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.HIGH,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/HUMAN_ESCALATION_POLICY.md §2 E-16 (fail closed)",
        observed_value=", ".join(failed) if failed else "workflow degraded",
        source_agent=", ".join(failed) if failed else None,
    )


# ---------------------------------------------------------------------------
# 3. No cover basis  (E-05, D-03)
# ---------------------------------------------------------------------------


def no_cover_basis(ctx: EvaluationContext) -> EscalationReason | None:
    interpretation = ctx.interpretation
    if interpretation.get("policy_found") is False:
        return EscalationReason(
            code="E-05_POLICY_NOT_FOUND",
            label="Policy not found",
            detail=(
                "No policy matching the number given could be located, so the claim "
                "cannot be assessed against cover."
            ),
            basis=ReasonBasis.AI_FINDING,
            priority=ReviewPriority.HIGH,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/DECISION_TABLE.md D-03",
            observed_value=str(
                ((ctx.claim.get("fnol") or {}).get("customer") or {}).get("policy_number")
            ),
            source_agent="policy",
        )

    if interpretation.get("in_force_at_date_of_loss") is False:
        facts = ctx.policy_facts
        return EscalationReason(
            code="E-05_POLICY_NOT_IN_FORCE",
            label="No cover basis at the date of loss",
            detail=(
                "The policy does not appear to have been in force when the damage "
                "happened. A specialist must confirm the policy position."
            ),
            basis=ReasonBasis.AI_FINDING,
            priority=ReviewPriority.HIGH,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/DECISION_TABLE.md D-03",
            observed_value=(
                f"status {facts.get('policy_status')}, cover "
                f"{facts.get('inception_date')} to {facts.get('expiry_date')}"
            ),
            threshold_value=f"date of loss {ctx.intake.get('date_of_loss')}",
            source_agent="policy",
        )

    if interpretation.get("peril_covered") is False:
        return EscalationReason(
            code="E-05_PERIL_NOT_COVERED",
            label="Peril not listed on the policy",
            detail="The claimed peril is not among the covered perils on this policy.",
            basis=ReasonBasis.AI_FINDING,
            priority=ReviewPriority.HIGH,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/DECISION_TABLE.md D-03",
            observed_value=str(ctx.intake.get("peril")),
            threshold_value=", ".join(ctx.policy_facts.get("covered_perils") or []),
            source_agent="policy",
        )

    return None


# ---------------------------------------------------------------------------
# 4. Vulnerable customer  (E-12, D-14)
# ---------------------------------------------------------------------------


def vulnerable_customer(ctx: EvaluationContext) -> EscalationReason | None:
    if not ctx.customer:
        return None

    flagged = bool(ctx.customer.get("vulnerability_flag"))
    accessibility = ctx.customer.get("accessibility_needs")
    if not flagged and not accessibility:
        return None

    # Deliberately operational, never diagnostic. The POC records that support is
    # needed and how the customer wants to be contacted -- nothing more.
    observed = []
    if flagged:
        observed.append("support flag on the customer record")
    if accessibility:
        observed.append(f"accessibility need recorded: {accessibility}")

    return EscalationReason(
        code="E-12_VULNERABLE_CUSTOMER",
        label="Vulnerable customer support",
        detail=(
            "This customer's record indicates they need supported handling. Contact "
            "them by their recorded preference and do not send automated chase-ups."
        ),
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.HIGH,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/HUMAN_ESCALATION_POLICY.md §4.2 · decision row D-14",
        observed_value="; ".join(observed),
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="customer record",
    )


# ---------------------------------------------------------------------------
# 5. Policy uncertainty  (E-06, D-09)
# ---------------------------------------------------------------------------


def policy_uncertainty(ctx: EvaluationContext) -> EscalationReason | None:
    interpretation = ctx.interpretation
    engaged = interpretation.get("exclusions_possibly_engaged") or []
    if not engaged and interpretation.get("cover_certainty") != "uncertain":
        return None

    return EscalationReason(
        code="E-06_POLICY_UNCERTAINTY",
        label="Policy exception may apply",
        detail=(
            "A policy exclusion or condition may be relevant to this claim. Deciding "
            "cover is a specialist's judgement, not an automated one."
        ),
        basis=ReasonBasis.AI_FINDING,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-09",
        observed_value=", ".join(engaged) if engaged else "cover certainty uncertain",
        threshold_value="; ".join(interpretation.get("relevant_wording_refs") or []) or None,
        source_agent="policy",
    )


# ---------------------------------------------------------------------------
# 6. Conflicting information  (E-07, D-12)
# ---------------------------------------------------------------------------


def conflicting_information(ctx: EvaluationContext) -> EscalationReason | None:
    inconsistencies = ctx.validation.get("inconsistencies") or []
    if not inconsistencies:
        return None

    return EscalationReason(
        code="E-07_CONFLICTING_INFORMATION",
        label="Conflicting information",
        detail="The claim contains inconsistencies that need a person to resolve.",
        basis=ReasonBasis.AI_FINDING,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-12",
        observed_value="; ".join(inconsistencies),
        source_agent="validation",
    )


# ---------------------------------------------------------------------------
# 7 & 8. Risk indicators  (E-10 / E-09, D-11 / D-10)
# ---------------------------------------------------------------------------


def risk_indicators(ctx: EvaluationContext) -> EscalationReason | None:
    level = ctx.risk.get("risk_level")
    indicators = ctx.risk.get("indicators") or []
    if level not in {"medium", "high"}:
        return None

    names = [i["name"] for i in indicators]
    high = level == "high"

    return EscalationReason(
        code="E-10_ELEVATED_RISK" if high else "E-09_RISK_INDICATOR",
        label="Elevated risk indicators" if high else "Risk indicator present",
        detail=(
            (
                "Several risk indicators warrant a specialist reviewer. "
                if high
                else "A risk indicator is present and warrants a closer look. "
            )
            + "Indicators are prompts to investigate, not findings against the customer."
        ),
        basis=ReasonBasis.AI_FINDING,
        priority=ReviewPriority.HIGH if high else ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md " + ("D-11" if high else "D-10"),
        observed_value=f"{len(indicators)} indicator(s): " + ", ".join(names),
        threshold_value=(
            f"{ctx.thresholds.risk_high_indicator_count}+ or one severe = high; "
            f"{ctx.thresholds.risk_medium_indicator_count} = medium"
        ),
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="fraud_risk",
    )


# ---------------------------------------------------------------------------
# 9. Above automated authority  (E-04, D-08)
# ---------------------------------------------------------------------------


def above_automated_authority(ctx: EvaluationContext) -> EscalationReason | None:
    if ctx.assessment.get("value_band") != "above_automated_authority":
        return None

    value = ctx.assessment.get("estimated_claim_value")
    return EscalationReason(
        code="E-04_ABOVE_AUTOMATED_AUTHORITY",
        label="Above automated authority limit",
        detail=(
            "The estimated value is above the limit the POC rules allow automated "
            "handling for. In Phase 4 this becomes a hard stop rather than a routing "
            "decision."
        ),
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.HIGH,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-08 · Invariant INV-02 in Phase 4",
        observed_value=_money(value) if value is not None else "unknown",
        threshold_value=_money(ctx.thresholds.automated_authority_limit),
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="assessment",
    )


# ---------------------------------------------------------------------------
# 10. High value  (E-03, D-07)
# ---------------------------------------------------------------------------


def high_value(ctx: EvaluationContext) -> EscalationReason | None:
    band = ctx.assessment.get("value_band")
    if band not in {"high_value", "unknown"}:
        return None

    if band == "unknown":
        return EscalationReason(
            code="E-03_VALUE_UNKNOWN",
            label="Claim value unknown",
            detail=(
                "No value estimate is available. The POC rules treat an unknown value "
                "as above the review threshold -- absence of evidence never buys "
                "automation."
            ),
            basis=ReasonBasis.BUSINESS_RULE,
            priority=ReviewPriority.STANDARD,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/DECISION_TABLE.md §2.4",
            observed_value="no estimate provided",
            threshold_value=_money(ctx.thresholds.high_value_review_threshold),
            assumption=POC_ASSUMPTION_NOTE,
            source_agent="assessment",
        )

    value = ctx.assessment.get("estimated_claim_value")
    return EscalationReason(
        code="E-03_HIGH_VALUE",
        label="High-value claim",
        detail="The estimated value is above the proposed high-value review threshold.",
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-07",
        observed_value=_money(value) if value is not None else "unknown",
        threshold_value=_money(ctx.thresholds.high_value_review_threshold),
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="assessment",
    )


# ---------------------------------------------------------------------------
# 11. High complexity  (E-02, D-06)
# ---------------------------------------------------------------------------


def high_complexity(ctx: EvaluationContext) -> EscalationReason | None:
    if ctx.assessment.get("complexity_band") != "high":
        return None

    factors = ctx.assessment.get("complexity_factors") or []
    return EscalationReason(
        code="E-02_HIGH_COMPLEXITY",
        label="High complexity",
        detail=(
            "The claim carries high-complexity factors. Automation is never the route "
            "for a high-complexity claim in this POC."
        ),
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-06 · §2.1",
        observed_value="; ".join(factors) if factors else "high",
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="assessment",
    )


# ---------------------------------------------------------------------------
# 12. Missing information  (E-08 / D-01) — the one INFORMATION_REQUIRED rule
# ---------------------------------------------------------------------------


def missing_information(ctx: EvaluationContext) -> EscalationReason | None:
    if ctx.validation.get("validation_status") != "information_required":
        return None

    missing = ctx.validation.get("missing_information") or []
    return EscalationReason(
        code="E-08_MISSING_INFORMATION",
        label="Information outstanding",
        detail=(
            "The claim cannot safely be assessed until the customer supplies the "
            "outstanding items."
        ),
        basis=ReasonBasis.AI_FINDING,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.INFORMATION_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-01",
        observed_value="; ".join(missing) if missing else "information outstanding",
        source_agent="validation",
    )


# ---------------------------------------------------------------------------
# 13. Low confidence  (E-01, D-05)
# ---------------------------------------------------------------------------


def low_confidence(ctx: EvaluationContext) -> EscalationReason | None:
    confidence = ctx.confidence()
    if confidence is None:
        return EscalationReason(
            code="E-01_NO_CONFIDENCE",
            label="No confidence measure",
            detail="No agent produced a confidence measure, so automation is not justified.",
            basis=ReasonBasis.BUSINESS_RULE,
            priority=ReviewPriority.STANDARD,
            outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
            rule_reference="docs/DECISION_TABLE.md D-05",
            observed_value="none",
            source_agent=None,
        )

    floor = ctx.thresholds.effective_confidence_floor
    if confidence >= floor:
        return None

    return EscalationReason(
        code="E-01_LOW_CONFIDENCE",
        label="Confidence below the POC threshold",
        detail=(
            "The workflow's confidence is below the floor the POC rules require for "
            "automated handling. In Phase 4 this becomes a PreNode denial with a "
            "fallback to human review."
        ),
        basis=ReasonBasis.BUSINESS_RULE,
        priority=ReviewPriority.STANDARD,
        outcome=RoutingOutcome.HUMAN_REVIEW_REQUIRED,
        rule_reference="docs/DECISION_TABLE.md D-05 · PreNode PN-01 in Phase 4",
        observed_value=f"{confidence:.3f}",
        threshold_value=(
            f"{floor:.4f} (derived from decision boundary "
            f"{ctx.thresholds.decision_threshold:.2f} and Gamma 1.1)"
        ),
        assumption=POC_ASSUMPTION_NOTE,
        source_agent="workflow",
    )


# ---------------------------------------------------------------------------
# Precedence order — docs/HUMAN_ESCALATION_POLICY.md §5
# ---------------------------------------------------------------------------

ESCALATION_RULES: tuple[Rule, ...] = (
    emergency,
    incomplete_analysis,
    no_cover_basis,
    vulnerable_customer,
    policy_uncertainty,
    conflicting_information,
    risk_indicators,
    above_automated_authority,
    high_value,
    high_complexity,
    missing_information,
    low_confidence,
)
