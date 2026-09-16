"""Policy Agent.

Retrieves the synthetic policy, states what it says, and offers a reading of it.

The output separates three things deliberately, because conflating them is how
an AI system ends up making cover decisions nobody authorised:

    facts          -- what the policy record says. Copied, not inferred.
    interpretation -- the agent's reading. Flagged as such, with a caveat.
    recommendation -- what a human might do next.

Nothing here decides cover. Where an exclusion might apply, the agent says
"possibly engaged" and points at the wording; deciding is a specialist's job,
and in Phase 4 an Invariant blocks automated approval in exactly this situation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agents.base import ClaimsAgent
from agents.contracts import (
    AgentResult,
    AgentStatus,
    Finding,
    PolicyFacts,
    PolicyInterpretation,
    PolicyPayload,
    Severity,
)
from app.repositories.reference_data import MissingDatasetError, SyntheticReferenceData

# Words in a claim that make a maintenance/wear exclusion worth a human look.
# A keyword screen, not a judgement -- which is exactly what it is labelled as.
_WEAR_LANGUAGE = (
    "old", "older", "aging", "ageing", "worn", "wear", "rust", "rusted", "rotten",
    "rot", "perished", "deteriorated", "leaking for", "overdue", "needed replacing",
    "due for replacement", "patched", "temporary repair", "years old",
)

_UNSECURED_LANGUAGE = ("unsecured", "left open", "door open", "window open", "unlocked")


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


class PolicyAgent(ClaimsAgent):
    name = "policy"

    def __init__(self, llm, reference_data: SyntheticReferenceData) -> None:  # noqa: ANN001
        super().__init__(llm)
        self._data = reference_data

    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        claim = context["claim"]
        fnol = claim.get("fnol") or {}
        customer = fnol.get("customer") or {}
        damage = fnol.get("damage") or {}
        address = (fnol.get("property") or {}).get("loss_address") or {}

        policy_number = str(customer.get("policy_number") or "").strip()

        try:
            policy = self._data.find_policy(policy_number)
        except MissingDatasetError as exc:
            return self._dataset_unavailable(exc), PolicyPayload(
                interpretation=PolicyInterpretation(policy_found=False, cover_certainty="unknown")
            ).model_dump(mode="json")

        if policy is None:
            return self._policy_not_found(policy_number)

        # -- facts --------------------------------------------------------
        inception = _parse_date(policy.get("inception_date"))
        expiry = _parse_date(policy.get("expiry_date"))
        exclusions = policy.get("exclusions") or []
        conditions = policy.get("conditions") or []

        facts = PolicyFacts(
            policy_id=policy["policy_id"],
            policy_status=policy.get("policy_status", "unknown"),
            inception_date=inception or date.min,
            expiry_date=expiry or date.max,
            covered_perils=list(policy.get("covered_perils") or []),
            dwelling_sum_insured=float(policy.get("dwelling_sum_insured") or 0),
            contents_sum_insured=float(policy.get("contents_sum_insured") or 0),
            standard_excess=float(policy.get("standard_excess") or 0),
            storm_excess=(
                float(policy["storm_excess"]) if policy.get("storm_excess") is not None else None
            ),
            exclusion_codes=[e.get("code") for e in exclusions if e.get("code")],
            condition_codes=[c.get("code") for c in conditions if c.get("code")],
            optional_covers=list(policy.get("optional_covers") or []),
            insured_address=(
                f"{policy.get('insured_address_line_1', '')}, {policy.get('insured_suburb', '')}, "
                f"{policy.get('insured_city', '')} {policy.get('insured_postcode', '')}".strip(", ")
            ),
        )

        # -- interpretation ------------------------------------------------
        findings: list[Finding] = []
        reasons: list[str] = []

        loss_date = _parse_date(damage.get("date_of_loss"))
        peril = str(damage.get("peril") or "").lower()

        in_force = None
        if loss_date and inception and expiry:
            in_force = (
                policy.get("policy_status") == "active"
                and inception <= loss_date <= expiry
            )

        if in_force is False:
            findings.append(
                Finding(
                    code="POLICY_NOT_IN_FORCE",
                    summary=(
                        "The policy does not appear to have been in force on the date of loss."
                    ),
                    severity=Severity.CONCERN,
                    detail=(
                        f"Policy status '{policy.get('policy_status')}', cover period "
                        f"{inception} to {expiry}, date of loss {loss_date}."
                    ),
                    data_reference=f"policies.jsonl:{facts.policy_id}",
                )
            )
            reasons.append("No apparent cover basis at the date of loss.")

        peril_covered = peril in {p.lower() for p in facts.covered_perils} if peril else None
        if peril_covered is False:
            findings.append(
                Finding(
                    code="PERIL_NOT_LISTED",
                    summary=f"'{peril}' is not listed among the covered perils on this policy.",
                    severity=Severity.CONCERN,
                    data_reference=f"policies.jsonl:{facts.policy_id}",
                )
            )

        address_matches = None
        if address:
            claim_line = _normalise(str(address.get("address_line_1", "")))
            policy_line = _normalise(str(policy.get("insured_address_line_1", "")))
            claim_pc = str(address.get("postcode", "")).strip()
            policy_pc = str(policy.get("insured_postcode", "")).strip()
            address_matches = bool(claim_line) and claim_line == policy_line and claim_pc == policy_pc
            if not address_matches:
                findings.append(
                    Finding(
                        code="ADDRESS_MISMATCH",
                        summary="The loss address does not match the insured address on the policy.",
                        severity=Severity.CONCERN,
                        detail=f"Claim: {facts.insured_address!r} on policy; loss address differs.",
                        data_reference=f"policies.jsonl:{facts.policy_id}",
                    )
                )

        applicable_excess = (
            facts.storm_excess if (peril == "storm" and facts.storm_excess is not None)
            else facts.standard_excess
        )
        if applicable_excess:
            findings.append(
                Finding(
                    code="EXCESS_APPLIES",
                    summary=f"An excess of NZD {applicable_excess:,.0f} applies to this claim.",
                    severity=Severity.INFO,
                    detail="Deducted from any amount payable.",
                    data_reference="wording 3.1",
                )
            )

        # Exclusion screen -- a keyword match over what the customer wrote, made
        # explicit as such rather than dressed up as an assessment.
        description_blob = _normalise(
            " ".join(
                [str(damage.get("incident_description") or "")]
                + [str(item.get("description", "")) for item in damage.get("damaged_items") or []]
            )
        )
        engaged: list[str] = []
        for exclusion in exclusions:
            code = exclusion.get("code")
            triggers: tuple[str, ...] = ()
            if code in {"EXC-MAINT", "EXC-WEAR"}:
                triggers = _WEAR_LANGUAGE
            elif code == "EXC-UNSECURED":
                triggers = _UNSECURED_LANGUAGE
            hit = next((t for t in triggers if t in description_blob), None)
            if hit:
                engaged.append(code)
                findings.append(
                    Finding(
                        code="EXCLUSION_POSSIBLY_ENGAGED",
                        summary=(
                            f"Exclusion {code} may be relevant: "
                            f"{exclusion.get('summary', '').lower()}."
                        ),
                        severity=Severity.CONCERN,
                        detail=(
                            f"The claim description mentions '{hit}'. This is a keyword "
                            "screen, not a cover determination -- a specialist decides."
                        ),
                        data_reference=f"wording {exclusion.get('wording_ref', '?')}",
                    )
                )

        if in_force is False or peril_covered is False:
            certainty = "no_cover_basis"
        elif engaged or address_matches is False:
            certainty = "uncertain"
        elif in_force and peril_covered:
            certainty = "clear"
        else:
            certainty = "unknown"

        try:
            sections = self._data.wording_sections(
                policy.get("wording_id", ""), peril=peril, exclusion_codes=engaged
            )
        except MissingDatasetError:
            sections = []
        wording_refs = [s["ref"] for s in sections if s.get("ref")]

        interpretation = PolicyInterpretation(
            policy_found=True,
            in_force_at_date_of_loss=in_force,
            peril_covered=peril_covered,
            address_matches_insured_address=address_matches,
            applicable_excess=applicable_excess,
            exclusions_possibly_engaged=engaged,
            cover_certainty=certainty,
            relevant_wording_refs=wording_refs,
        )

        # -- recommendation -------------------------------------------------
        if certainty == "no_cover_basis":
            recommendation = (
                "Do not progress this claim automatically. There is no apparent cover "
                "basis, and a claims specialist should confirm the policy position."
            )
            next_step = "manual_review"
            status = AgentStatus.COMPLETE
        elif certainty == "uncertain":
            recommendation = (
                "A claims specialist should confirm cover before this claim progresses. "
                "The policy is in force, but there is a question over how it applies."
            )
            next_step = "manual_review"
            status = AgentStatus.COMPLETE
        else:
            recommendation = (
                "Cover appears to apply on the face of the policy record. "
                "Proceed to validation."
            )
            next_step = "validation"
            status = AgentStatus.COMPLETE

        reasons.append(
            f"Policy {facts.policy_id} is '{facts.policy_status}', covering "
            f"{', '.join(facts.covered_perils)}."
        )
        if wording_refs:
            reasons.append("Relevant wording: " + ", ".join(wording_refs) + ".")

        confidence_value = {
            "clear": 0.9,
            "uncertain": 0.55,
            "no_cover_basis": 0.85,
            "unknown": 0.4,
        }[certainty]

        narrative, source, narration_governance = self.narrate(
            context=context,
            purpose="policy position summary for a claims employee",
            headline=f"Policy {facts.policy_id} retrieved for a {peril} claim",
            points=reasons + [f.summary for f in findings if f.severity != Severity.INFO],
            caveat=interpretation.caveat,
        )

        result = AgentResult(
            agent=self.name,
            status=status,
            findings=findings,
            recommendation=recommendation,
            reasons=reasons,
            confidence=self.confidence(
                confidence_value,
                basis=(
                    "Policy facts are read directly from the record; the uncertainty is "
                    "in how the wording applies, which is not an AI decision."
                ),
            ),
            data_references=[f"policies.jsonl:{facts.policy_id}"]
            + [f"wording {ref}" for ref in wording_refs],
            next_step=next_step,
            narrative=narrative,
            narrative_source=source,
            narration_governance=narration_governance,
        )
        return result, PolicyPayload(facts=facts, interpretation=interpretation).model_dump(
            mode="json"
        )

    # -- failure shapes ----------------------------------------------------

    def _policy_not_found(self, policy_number: str) -> tuple[AgentResult, dict[str, Any]]:
        finding = Finding(
            code="POLICY_NOT_FOUND",
            summary=f"No policy matching '{policy_number}' was found.",
            severity=Severity.CONCERN,
            detail="The claim cannot be assessed against a policy that cannot be located.",
            data_reference="policies.jsonl",
        )
        result = AgentResult(
            agent=self.name,
            status=AgentStatus.INCOMPLETE,
            findings=[finding],
            recommendation=(
                "A claims specialist should confirm the policy number with the customer. "
                "The claim cannot progress automatically without a policy."
            ),
            reasons=[f"Policy number '{policy_number}' did not match any policy record."],
            confidence=self.confidence(
                0.9, basis="Lookup is exact-match; absence is a reliable finding."
            ),
            data_references=["policies.jsonl"],
            next_step="manual_review",
        )
        payload = PolicyPayload(
            interpretation=PolicyInterpretation(policy_found=False, cover_certainty="no_cover_basis")
        )
        return result, payload.model_dump(mode="json")

    def _dataset_unavailable(self, exc: MissingDatasetError) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status=AgentStatus.DEGRADED,
            recommendation=(
                "Policy information could not be retrieved. A claims specialist should "
                "check the policy manually."
            ),
            reasons=[f"The {exc.dataset} dataset is not available."],
            confidence=None,
            next_step="manual_review",
            error="Policy information is temporarily unavailable.",
        )
