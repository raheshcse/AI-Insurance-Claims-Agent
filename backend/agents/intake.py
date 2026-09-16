"""Intake Agent.

Receives the submitted claim, interprets the FNOL and structures it for the
agents downstream. It also notes obvious gaps -- "obvious" meaning a field that
is absent or empty, not a judgement about sufficiency. Judgement belongs to the
Validation Agent.

It does not approve, settle, communicate or change anything.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agents.base import ClaimsAgent
from agents.contracts import (
    AgentResult,
    AgentStatus,
    Finding,
    IntakePayload,
    Severity,
)

# Fields an FNOL must carry to be worth analysing at all
# (docs/SYNTHETIC_DATA_SPEC.md section 4.2).
_REQUIRED_FNOL_FIELDS: dict[str, str] = {
    "date_of_loss": "the date the damage happened",
    "incident_description": "a description of what happened",
    "damaged_items": "at least one damaged item",
}

_SUPPORTING_INFORMATION: dict[str, str] = {
    "photos_supplied": "photographs of the damage",
    "customer_estimated_value": "an estimate of the claim value",
}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


class IntakeAgent(ClaimsAgent):
    name = "intake"

    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        claim = context["claim"]
        fnol = claim.get("fnol") or {}
        damage = fnol.get("damage") or {}
        property_details = fnol.get("property") or {}
        address = property_details.get("loss_address") or {}

        findings: list[Finding] = []
        missing: list[str] = []

        # -- obvious gaps -------------------------------------------------
        for field, label in _REQUIRED_FNOL_FIELDS.items():
            value = damage.get(field)
            if value in (None, "", [], {}):
                missing.append(label)
                findings.append(
                    Finding(
                        code="FNOL_FIELD_MISSING",
                        summary=f"The FNOL does not include {label}.",
                        severity=Severity.ATTENTION,
                        data_reference=f"claim.fnol.damage.{field}",
                    )
                )

        for field, label in _SUPPORTING_INFORMATION.items():
            value = damage.get(field)
            if value in (None, "", False):
                missing.append(label)
                findings.append(
                    Finding(
                        code="SUPPORTING_INFORMATION_ABSENT",
                        summary=f"No {label} was provided.",
                        severity=Severity.INFO,
                        detail="Supporting information, not a blocker on its own.",
                        data_reference=f"claim.fnol.damage.{field}",
                    )
                )

        # -- structure ----------------------------------------------------
        loss_date = _parse_date(damage.get("date_of_loss"))
        days_since_loss = (date.today() - loss_date).days if loss_date else -1

        items = damage.get("damaged_items") or []
        areas = sorted({str(item.get("area", "")).strip() for item in items if item.get("area")})

        itemised_total: float | None = None
        values = [
            float(item["estimated_value"])
            for item in items
            if item.get("estimated_value") not in (None, "")
        ]
        if values:
            itemised_total = round(sum(values), 2)

        description = str(damage.get("incident_description") or "")
        word_count = len(description.split())

        # -- urgency signals: observed only, never routed on in Phase 2 ----
        urgency_signals: list[str] = []
        if property_details.get("property_habitable") is False:
            urgency_signals.append("The customer reports the home is not liveable.")
        if damage.get("anyone_injured"):
            urgency_signals.append("The customer reports someone was hurt.")
        if damage.get("damage_ongoing"):
            urgency_signals.append("The customer reports the damage is ongoing.")
        if damage.get("utilities_affected"):
            urgency_signals.append(
                "Utilities affected: " + ", ".join(damage["utilities_affected"]) + "."
            )
        if property_details.get("temporary_accommodation_needed"):
            urgency_signals.append("The customer has asked about temporary accommodation.")

        for signal in urgency_signals:
            findings.append(
                Finding(
                    code="URGENCY_SIGNAL",
                    summary=signal,
                    severity=Severity.CONCERN,
                    detail=(
                        "Recorded for the reviewer. Phase 2 does not act on urgency "
                        "signals; the emergency pathway is Phase 3."
                    ),
                    data_reference="claim.fnol",
                )
            )

        payload = IntakePayload(
            peril=str(damage.get("peril") or "unknown"),
            date_of_loss=loss_date or date.today(),
            days_since_loss=days_since_loss,
            loss_address=(
                f"{address.get('address_line_1', '')}, {address.get('suburb', '')}, "
                f"{address.get('city', '')} {address.get('postcode', '')}".strip(", ")
            ),
            damaged_item_count=len(items),
            damage_areas=areas,
            itemised_estimate_total=itemised_total,
            customer_estimated_value=(
                float(damage["customer_estimated_value"])
                if damage.get("customer_estimated_value") not in (None, "")
                else None
            ),
            description_word_count=word_count,
            missing_information=missing,
            urgency_signals=urgency_signals,
        )

        blocking_gaps = [
            label for field, label in _REQUIRED_FNOL_FIELDS.items()
            if damage.get(field) in (None, "", [], {})
        ]
        status = AgentStatus.INCOMPLETE if blocking_gaps else AgentStatus.COMPLETE

        recommendation = (
            "The FNOL is structured and ready for policy retrieval."
            if not blocking_gaps
            else "The FNOL is missing information needed before the claim can be assessed."
        )

        reasons = [
            f"{len(items)} damaged item(s) reported across {len(areas)} area(s).",
            f"Incident described in {word_count} words.",
        ]
        if loss_date:
            reasons.append(f"Loss reported {days_since_loss} day(s) after it occurred.")

        narrative, source, narration_governance = self.narrate(
            context=context,
            purpose="claim intake summary for a claims employee",
            headline=(
                f"Storm damage claim covering {', '.join(areas) if areas else 'unspecified areas'}"
            ),
            points=reasons + urgency_signals,
            caveat=(
                "Missing: " + "; ".join(missing) + "." if missing else None
            ),
        )

        result = AgentResult(
            agent=self.name,
            status=status,
            findings=findings,
            recommendation=recommendation,
            reasons=reasons,
            confidence=self.confidence(
                0.95 if not blocking_gaps else 0.6,
                basis="Structuring an already-validated FNOL is deterministic; "
                "confidence reflects whether required fields are present.",
            ),
            data_references=[f"claim:{claim.get('claim_id')}"],
            next_step="policy_retrieval" if not blocking_gaps else "information_required",
            narrative=narrative,
            narrative_source=source,
            narration_governance=narration_governance,
        )
        return result, payload.model_dump(mode="json")
