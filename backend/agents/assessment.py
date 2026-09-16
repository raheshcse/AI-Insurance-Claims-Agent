"""Assessment Agent.

Classifies the claim, estimates complexity, urgency and value, and says how
confident it is.

Every band comes from the Phase 0 decision table, and every finding that rests
on a proposed number carries `assumption=POC_ASSUMPTION_NOTE` so the distinction
between "POC assumption" and "insurer rule" survives all the way into the UI.
That matters more than it sounds: a demo that shows "high value" without saying
whose threshold that is invites a stakeholder to believe a number nobody
approved.

The agent does not approve, decline, settle or route.
"""

from __future__ import annotations

from typing import Any

from agents.base import ClaimsAgent
from agents.contracts import (
    AgentResult,
    AgentStatus,
    AssessmentPayload,
    Finding,
    Severity,
)
from app.domain.thresholds import POC_ASSUMPTION_NOTE, Thresholds

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("roof_damage", ("roof", "tile", "shingle", "ridge", "gutter", "spouting")),
    ("water_ingress", ("water", "ceiling", "leak", "flooded", "damp", "soaked")),
    ("fence_damage", ("fence", "gate", "retaining")),
    ("window_damage", ("window", "glass", "glazing", "skylight")),
    ("cladding_damage", ("cladding", "weatherboard", "siding", "wall")),
    ("tree_damage", ("tree", "branch", "fell", "fallen")),
    ("outbuilding_damage", ("shed", "garage", "carport", "outbuilding")),
    ("contents_damage", ("furniture", "carpet", "contents", "appliance", "tv")),
]


class AssessmentAgent(ClaimsAgent):
    name = "assessment"

    def __init__(self, llm, thresholds: Thresholds) -> None:  # noqa: ANN001
        super().__init__(llm)
        self._t = thresholds

    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        claim = context["claim"]
        fnol = claim.get("fnol") or {}
        damage = fnol.get("damage") or {}
        property_details = fnol.get("property") or {}

        intake = context.get("intake_payload") or {}
        policy = context.get("policy_payload") or {}
        interpretation = policy.get("interpretation") or {}
        facts = policy.get("facts") or {}
        validation = context.get("validation_payload") or {}

        findings: list[Finding] = []

        # -- classification -------------------------------------------------
        blob = " ".join(
            [str(damage.get("incident_description") or "")]
            + [
                f"{item.get('area', '')} {item.get('item', '')} {item.get('description', '')}"
                for item in damage.get("damaged_items") or []
            ]
        ).lower()

        category = next(
            (name for name, words in _CATEGORY_KEYWORDS if any(w in blob for w in words)),
            "general_storm_damage",
        )
        findings.append(
            Finding(
                code="CLAIM_CLASSIFIED",
                summary=f"Classified as {category.replace('_', ' ')}.",
                severity=Severity.INFO,
                detail="Keyword classification over the customer's own description.",
                data_reference="claim.fnol.damage",
            )
        )

        # -- value -----------------------------------------------------------
        itemised = intake.get("itemised_estimate_total")
        customer_estimate = intake.get("customer_estimated_value")

        if customer_estimate is not None:
            estimate = float(customer_estimate)
            basis = "The customer's overall estimate."
        elif itemised is not None:
            estimate = float(itemised)
            basis = "The sum of the customer's itemised estimates."
        else:
            estimate = None
            basis = (
                "No estimate was provided. Per the Phase 0 decision table, an unknown "
                "value is treated as above the review threshold -- absence of evidence "
                "never buys automation."
            )

        if estimate is None:
            value_band = "unknown"
            findings.append(
                Finding(
                    code="VALUE_UNKNOWN",
                    summary="No claim value estimate is available.",
                    severity=Severity.ATTENTION,
                    detail="Treated conservatively as above the review threshold.",
                    data_reference="claim.fnol.damage.customer_estimated_value",
                    assumption=POC_ASSUMPTION_NOTE,
                )
            )
        elif estimate > self._t.automated_authority_limit:
            value_band = "above_automated_authority"
            findings.append(
                Finding(
                    code="ABOVE_AUTOMATED_AUTHORITY",
                    summary=(
                        f"The estimate of NZD {estimate:,.0f} is above the proposed "
                        f"automated authority limit of NZD {self._t.automated_authority_limit:,.0f}."
                    ),
                    severity=Severity.CONCERN,
                    detail=(
                        "In Phase 4 this is an Invariant: automated handling stops and a "
                        "human re-enables it. Phase 2 only reports it."
                    ),
                    data_reference="docs/DECISION_TABLE.md 2.4",
                    assumption=POC_ASSUMPTION_NOTE,
                )
            )
        elif estimate > self._t.high_value_review_threshold:
            value_band = "high_value"
            findings.append(
                Finding(
                    code="HIGH_VALUE",
                    summary=(
                        f"The estimate of NZD {estimate:,.0f} is above the proposed "
                        f"high-value review threshold of NZD "
                        f"{self._t.high_value_review_threshold:,.0f}."
                    ),
                    severity=Severity.ATTENTION,
                    data_reference="docs/DECISION_TABLE.md 2.4",
                    assumption=POC_ASSUMPTION_NOTE,
                )
            )
        elif estimate <= self._t.low_value_automation_band:
            value_band = "low_value"
        else:
            value_band = "standard"

        applicable_excess = interpretation.get("applicable_excess")
        net_estimate = (
            round(max(estimate - float(applicable_excess), 0.0), 2)
            if estimate is not None and applicable_excess is not None
            else None
        )

        # -- complexity -------------------------------------------------------
        item_count = int(intake.get("damaged_item_count") or 0)
        complexity_factors: list[str] = []

        if item_count >= self._t.high_complexity_min_items:
            complexity_factors.append(
                f"{item_count} damaged items reported (proposed high-complexity "
                f"threshold is {self._t.high_complexity_min_items})."
            )
        if property_details.get("property_habitable") is False:
            complexity_factors.append("The home is reported as not liveable.")
        if property_details.get("temporary_accommodation_needed"):
            complexity_factors.append("Temporary accommodation is needed.")
        if damage.get("third_party_involved"):
            complexity_factors.append("A third party is involved.")
        if damage.get("anyone_injured"):
            complexity_factors.append("An injury has been reported.")
        if interpretation.get("exclusions_possibly_engaged"):
            complexity_factors.append(
                "A policy exclusion may be relevant: "
                + ", ".join(interpretation["exclusions_possibly_engaged"])
                + "."
            )
        if interpretation.get("cover_certainty") in {"uncertain", "no_cover_basis"}:
            complexity_factors.append("The cover position is not clear-cut.")
        if validation.get("inconsistencies"):
            complexity_factors.append("The claim contains unresolved inconsistencies.")
        if estimate is not None and estimate > self._t.high_complexity_value:
            complexity_factors.append(
                f"The estimate exceeds the proposed high-complexity value of NZD "
                f"{self._t.high_complexity_value:,.0f}."
            )

        if complexity_factors:
            complexity = "high"
        elif (
            estimate is not None
            and estimate <= self._t.low_value_automation_band
            and item_count <= self._t.low_complexity_max_items
        ):
            complexity = "low"
        else:
            complexity = "medium"

        findings.append(
            Finding(
                code=f"COMPLEXITY_{complexity.upper()}",
                summary=f"Assessed complexity: {complexity}.",
                severity=Severity.INFO if complexity == "low" else Severity.ATTENTION,
                detail=(
                    "; ".join(complexity_factors)
                    if complexity_factors
                    else "No high-complexity factors present."
                ),
                data_reference="docs/DECISION_TABLE.md 2.1",
                assumption=POC_ASSUMPTION_NOTE,
            )
        )

        # -- urgency ----------------------------------------------------------
        severity_indicators: list[str] = list(intake.get("urgency_signals") or [])
        if (
            property_details.get("property_habitable") is False
            or damage.get("anyone_injured")
            or damage.get("damage_ongoing")
            or damage.get("utilities_affected")
        ):
            urgency = "emergency"
        elif not damage.get("emergency_repairs_done") and category in {
            "roof_damage",
            "water_ingress",
            "window_damage",
        }:
            urgency = "high"
            severity_indicators.append(
                "Weatherproofing may be compromised and no make-safe work has been done."
            )
        else:
            urgency = "standard"

        if urgency == "emergency":
            findings.append(
                Finding(
                    code="URGENCY_EMERGENCY",
                    summary="The claim shows emergency indicators.",
                    severity=Severity.CONCERN,
                    detail=(
                        "Phase 2 reports this only. The emergency pathway -- priority "
                        "queueing and the customer-facing response -- is Phase 3."
                    ),
                    data_reference="docs/HUMAN_ESCALATION_POLICY.md 4.1",
                    assumption=POC_ASSUMPTION_NOTE,
                )
            )

        # -- confidence -------------------------------------------------------
        confidence_value = 0.9
        if estimate is None:
            confidence_value -= 0.25
        if interpretation.get("cover_certainty") == "uncertain":
            confidence_value -= 0.15
        if interpretation.get("cover_certainty") in {"no_cover_basis", "unknown"}:
            confidence_value -= 0.30
        if validation.get("missing_information"):
            confidence_value -= 0.10
        if validation.get("inconsistencies"):
            confidence_value -= 0.15
        if int(intake.get("description_word_count") or 0) < 15:
            confidence_value -= 0.05

        floor = self._t.effective_confidence_floor

        payload = AssessmentPayload(
            incident_category=category,
            complexity_band=complexity,
            complexity_factors=complexity_factors,
            urgency_band=urgency,
            severity_indicators=severity_indicators,
            estimated_claim_value=estimate,
            estimate_basis=basis,
            value_band=value_band,
            net_of_excess_estimate=net_estimate,
        )

        reasons = [
            f"Classified as {category.replace('_', ' ')}.",
            f"Complexity assessed as {complexity}.",
            f"Urgency assessed as {urgency}.",
            (
                f"Estimated value NZD {estimate:,.0f} ({value_band.replace('_', ' ')})."
                if estimate is not None
                else "No claim value estimate available."
            ),
        ]

        if complexity == "high" or value_band in {"high_value", "above_automated_authority", "unknown"}:
            recommendation = (
                "A claims specialist should handle this claim. It is outside what the "
                "proposed POC thresholds treat as straightforward."
            )
            next_step = "manual_review"
        elif urgency == "emergency":
            recommendation = (
                "A claims specialist should pick this claim up promptly -- the answers "
                "indicate an urgent situation."
            )
            next_step = "manual_review"
        else:
            recommendation = (
                "On the assessment alone, this looks like a straightforward storm claim. "
                "The risk check has not yet been considered."
            )
            next_step = "risk_check"

        narrative, source, narration_governance = self.narrate(
            context=context,
            purpose="damage assessment summary for a claims employee",
            headline=f"{category.replace('_', ' ').title()}, complexity {complexity}",
            points=reasons + complexity_factors,
            caveat=(
                "Thresholds used here are POC proposals pending business approval, not "
                "insurer-approved rules."
            ),
        )

        result = AgentResult(
            agent=self.name,
            status=AgentStatus.COMPLETE,
            findings=findings,
            recommendation=recommendation,
            reasons=reasons,
            confidence=self.confidence(
                confidence_value,
                basis=(
                    "Starts high for a deterministic banding, reduced for each piece of "
                    "missing or uncertain input."
                ),
                floor=floor,
                threshold_note=(
                    f"The Phase 4 PreNode floor implied by the proposed decision boundary "
                    f"of {self._t.decision_threshold:.2f} is {floor:.4f}. Reported only -- "
                    f"nothing gates on it in Phase 2."
                ),
            ),
            data_references=["claim.fnol", "policy agent result", "docs/DECISION_TABLE.md"],
            next_step=next_step,
            narrative=narrative,
            narrative_source=source,
            narration_governance=narration_governance,
        )
        return result, payload.model_dump(mode="json")
