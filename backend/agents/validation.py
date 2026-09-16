"""Validation Agent.

Checks the claim against itself and against the policy context the Policy Agent
retrieved. Phase 1 already enforced field-level validity at the API boundary;
this agent does the part that needs context:

    * Is anything required actually absent?
    * Does the claim contradict the policy record?
    * Does the claim contradict itself?

It never rejects or approves. `validation_status` describes the information,
not the claim's fate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agents.base import ClaimsAgent
from agents.contracts import (
    AgentResult,
    AgentStatus,
    Finding,
    Severity,
    ValidationPayload,
)

_CHECKS = [
    "Required FNOL fields present",
    "Date of loss within the policy period",
    "Peril listed on the policy",
    "Loss address matches the insured address",
    "Damaged items described",
    "Estimate consistent with itemised values",
    "Supporting evidence noted",
]


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


class ValidationAgent(ClaimsAgent):
    name = "validation"

    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        claim = context["claim"]
        fnol = claim.get("fnol") or {}
        damage = fnol.get("damage") or {}

        intake = context.get("intake_payload") or {}
        policy = context.get("policy_payload") or {}
        interpretation = policy.get("interpretation") or {}
        facts = policy.get("facts") or {}

        findings: list[Finding] = []
        missing: list[str] = list(intake.get("missing_information") or [])
        inconsistencies: list[str] = []

        # -- consistency with the policy ----------------------------------
        if interpretation.get("policy_found") is False:
            inconsistencies.append(
                "The claim references a policy that could not be found."
            )
            findings.append(
                Finding(
                    code="NO_POLICY_CONTEXT",
                    summary="Validation against the policy was not possible.",
                    severity=Severity.CONCERN,
                    data_reference="policy agent",
                )
            )

        if interpretation.get("in_force_at_date_of_loss") is False:
            inconsistencies.append(
                "The date of loss falls outside the policy period, or the policy is not active."
            )
            findings.append(
                Finding(
                    code="LOSS_OUTSIDE_POLICY_PERIOD",
                    summary="The date of loss is not covered by the policy period on record.",
                    severity=Severity.CONCERN,
                    data_reference=f"policies.jsonl:{facts.get('policy_id', 'unknown')}",
                )
            )

        if interpretation.get("peril_covered") is False:
            inconsistencies.append("The claimed peril is not listed on the policy.")

        if interpretation.get("address_matches_insured_address") is False:
            inconsistencies.append(
                "The loss address does not match the insured address on the policy."
            )
            findings.append(
                Finding(
                    code="ADDRESS_INCONSISTENT",
                    summary="The address claimed against does not match the policy record.",
                    severity=Severity.CONCERN,
                    detail="Could be a second property, a data error, or the wrong policy.",
                    data_reference=f"policies.jsonl:{facts.get('policy_id', 'unknown')}",
                )
            )

        # -- internal consistency ------------------------------------------
        loss_date = _parse_date(damage.get("date_of_loss"))
        if loss_date and loss_date > date.today():
            inconsistencies.append("The date of loss is in the future.")

        itemised = intake.get("itemised_estimate_total")
        overall = intake.get("customer_estimated_value")
        if itemised is not None and overall is not None and overall < itemised:
            inconsistencies.append(
                f"The overall estimate (NZD {overall:,.0f}) is below the sum of the "
                f"itemised estimates (NZD {itemised:,.0f})."
            )
            findings.append(
                Finding(
                    code="ESTIMATE_INCONSISTENT",
                    summary="The overall estimate is lower than the itemised estimates add up to.",
                    severity=Severity.ATTENTION,
                    detail="Probably a customer arithmetic slip rather than anything more.",
                    data_reference="claim.fnol.damage",
                )
            )

        sum_insured = facts.get("dwelling_sum_insured")
        if overall is not None and sum_insured and overall > float(sum_insured):
            inconsistencies.append(
                "The estimated value exceeds the dwelling sum insured on the policy."
            )
            findings.append(
                Finding(
                    code="ESTIMATE_ABOVE_SUM_INSURED",
                    summary="The customer's estimate is above the dwelling sum insured.",
                    severity=Severity.CONCERN,
                    data_reference=f"policies.jsonl:{facts.get('policy_id', 'unknown')}",
                )
            )

        # -- evidence -------------------------------------------------------
        if not damage.get("photos_supplied"):
            findings.append(
                Finding(
                    code="NO_PHOTOGRAPHS",
                    summary="No photographs of the damage were provided.",
                    severity=Severity.ATTENTION,
                    detail="Photographs are normally needed to assess storm damage.",
                    data_reference="claim.fnol.damage.photos_supplied",
                )
            )
            if "photographs of the damage" not in missing:
                missing.append("photographs of the damage")

        # -- status ----------------------------------------------------------
        blocking = [m for m in missing if m in {
            "the date the damage happened",
            "a description of what happened",
            "at least one damaged item",
            "photographs of the damage",
        }]

        if inconsistencies:
            status_value = "inconsistent"
            recommendation = (
                "A claims specialist should resolve the inconsistencies below before "
                "the claim progresses. Nothing here decides the claim either way."
            )
            next_step = "manual_review"
        elif blocking:
            status_value = "information_required"
            recommendation = (
                "Ask the customer for the outstanding information before assessing "
                "this claim."
            )
            next_step = "information_required"
        else:
            status_value = "complete"
            recommendation = "The claim has the information needed to be assessed."
            next_step = "assessment"

        payload = ValidationPayload(
            validation_status=status_value,
            missing_information=missing,
            inconsistencies=inconsistencies,
            checks_performed=_CHECKS,
        )

        reasons = [f"{len(_CHECKS)} checks performed."]
        if missing:
            reasons.append(f"{len(missing)} item(s) of information outstanding.")
        if inconsistencies:
            reasons.append(f"{len(inconsistencies)} inconsistency/ies found.")
        if not missing and not inconsistencies:
            reasons.append("No missing information or inconsistencies found.")

        confidence_value = 0.9 if not inconsistencies else 0.7
        if interpretation.get("policy_found") is False:
            confidence_value = 0.5

        narrative, source, narration_governance = self.narrate(
            context=context,
            purpose="validation summary for a claims employee",
            headline=f"Validation result: {status_value.replace('_', ' ')}",
            points=reasons + inconsistencies,
            caveat=(
                "Outstanding: " + "; ".join(missing) + "." if missing else None
            ),
        )

        result = AgentResult(
            agent=self.name,
            status=(
                AgentStatus.COMPLETE if status_value == "complete" else AgentStatus.INCOMPLETE
            ),
            findings=findings,
            recommendation=recommendation,
            reasons=reasons,
            confidence=self.confidence(
                confidence_value,
                basis="Checks are deterministic; confidence reflects how much policy "
                "context was available to check against.",
            ),
            data_references=["claim.fnol", "policy agent result"],
            next_step=next_step,
            narrative=narrative,
            narrative_source=source,
            narration_governance=narration_governance,
        )
        return result, payload.model_dump(mode="json")
