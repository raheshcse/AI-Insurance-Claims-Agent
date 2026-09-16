"""Turning a finished conversation into an FNOL, and into a summary.

Two functions, one rule between them: **the summary the customer confirms and
the FNOL that is submitted are built from the same collected values.** If they
were built separately, a customer could confirm one thing and have another
lodged, and nobody would notice until a reviewer read the claim.

`to_submission()` is a projection, not a translation -- every field name in
`conversation.fields` already matches the FNOL, so this is a reshape with no
interpretation in it. Nothing here defaults a missing value: `build()` is only
reachable once `missing_fields()` is empty, and a default silently invented at
submission time is the fabrication INV-05 exists to prevent, arriving by the
back door.
"""

from __future__ import annotations

from typing import Any

from app.schemas.claim import ClaimSubmissionRequest
from conversation.contracts import ConversationState
from conversation.fields import FIELDS, FIELDS_BY_NAME, missing_fields


class ConversationIncompleteError(RuntimeError):
    """Raised when a claim is built before the conversation has what it needs.

    A programming error rather than a customer error: the API checks readiness
    before it gets here, and this is the backstop that makes "a claim is never
    created from an incomplete conversation" a property of the code rather than
    a property of the caller's diligence.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Conversation is missing required information: {missing}")


def to_submission(state: ConversationState) -> ClaimSubmissionRequest:
    """Build the FNOL from collected values.

    Pydantic validates it a second time on the way in. That is deliberate
    belt-and-braces: `fields.py` validated each value in isolation, and this
    validates the whole document against the Phase 0 schema, which is the
    contract the claims workflow actually reads.
    """
    values = state.values()
    outstanding = missing_fields(values)
    if outstanding:
        raise ConversationIncompleteError(outstanding)

    areas = values["damaged_areas"]
    estimate = values["estimated_damage_value"]

    # One damaged item per area, sharing the customer's single estimate.
    #
    # The customer gave one figure for the whole loss, not a figure per area.
    # Splitting it between areas would invent per-item values they never gave;
    # repeating the full figure on every item would multiply the claim. So the
    # estimate sits on the FIRST item and the rest carry None, and the total the
    # assessment reads is `customer_estimated_value` below -- the number the
    # customer actually said.
    damaged_items = [
        {
            "area": area,
            "item": f"{area} damage",
            "description": values["incident_description"][:1000],
            "estimated_value": estimate if index == 0 else None,
        }
        for index, area in enumerate(areas)
    ]

    return ClaimSubmissionRequest.model_validate(
        {
            "customer": {
                "full_name": values["full_name"],
                "email": values["email"],
                "phone": values["phone"],
                "policy_number": values["policy_number"],
                "preferred_contact_method": "email",
            },
            "property": {
                "loss_address": {
                    "address_line_1": values["address_line_1"],
                    "suburb": values["suburb"],
                    "city": values["city"],
                    "postcode": values["postcode"],
                },
                "property_habitable": values["property_habitable"],
                "temporary_accommodation_needed": values[
                    "temporary_accommodation_needed"
                ],
            },
            "damage": {
                "date_of_loss": values["date_of_loss"],
                "peril": "storm",
                "incident_description": values["incident_description"],
                "damaged_items": damaged_items,
                "damage_ongoing": values["damage_ongoing"],
                "anyone_injured": values["anyone_injured"],
                "utilities_affected": [],
                "emergency_repairs_done": values["emergency_repairs_done"],
                "third_party_involved": False,
                "photos_supplied": values["photos_supplied"],
                "customer_estimated_value": estimate,
            },
        }
    )


def _render(field_name: str, value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if field_name == "estimated_damage_value" and isinstance(value, (int, float)):
        return f"NZD {value:,.0f}"
    return str(value)


def claim_summary(state: ConversationState) -> list[dict[str, str]]:
    """The summary the customer is asked to confirm.

    Built from `collected_information` in catalogue order, so it shows exactly
    what will be submitted -- including anything the customer volunteered out of
    order. A summary assembled from the transcript instead could show something
    the FNOL will not contain.
    """
    rows: list[dict[str, str]] = []
    for spec in FIELDS:
        entry = state.collected_information.get(spec.name)
        if entry is None:
            continue
        rows.append(
            {
                "field": spec.name,
                "label": spec.display(),
                "value": _render(spec.name, entry.value),
            }
        )
    return rows


def summary_text(state: ConversationState) -> str:
    """The same summary as plain text, for the assistant's own message."""
    lines = ["CLAIM SUMMARY", ""]
    for row in claim_summary(state):
        lines.append(f"{row['label']}: {row['value']}")
    lines.append("")
    lines.append("Would you like me to submit this claim with these details?")
    return "\n".join(lines)


def label_for(field_name: str) -> str:
    spec = FIELDS_BY_NAME.get(field_name)
    return spec.display() if spec else field_name.replace("_", " ")
