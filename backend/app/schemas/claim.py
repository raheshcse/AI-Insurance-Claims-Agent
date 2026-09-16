"""Request and response models for the claims API.

Field names and mandatory/optional status follow docs/SYNTHETIC_DATA_SPEC.md
section 4.2, which is the Phase 0 definition of a complete FNOL.

Phase 1 scope: Home Insurance / Storm Damage only. `peril` is constrained to
"storm" deliberately -- widening it is a later-phase decision, not an oversight.
"""

from __future__ import annotations

import re
from datetime import date, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.claim_state import ClaimState

# --------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------

ContactMethod = Literal["email", "phone", "portal"]

# A deliberately simple email check rather than pydantic's EmailStr.
#
# EmailStr (via email-validator) rejects reserved TLDs, including the
# `.invalid` domain the Phase 0 synthetic data spec mandates for test
# addresses. A POC that cannot accept its own synthetic data is not a POC.
# This pattern matches the frontend rule in src/claim/validation.js.
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

NonEmptyStr = Annotated[str, Field(min_length=1, max_length=200)]


class Address(BaseModel):
    """The loss address. Matched against the insured address in Phase 2."""

    model_config = ConfigDict(extra="forbid")

    address_line_1: NonEmptyStr
    suburb: NonEmptyStr
    city: NonEmptyStr
    postcode: Annotated[str, Field(min_length=3, max_length=10)]


class DamagedItem(BaseModel):
    """One damaged element of the property.

    `estimated_value` is what the customer thinks it is worth. It is NOT an
    assessed value -- assessment is Phase 2.
    """

    model_config = ConfigDict(extra="forbid")

    area: NonEmptyStr
    item: NonEmptyStr
    description: Annotated[str, Field(min_length=1, max_length=1000)]
    estimated_value: Annotated[float, Field(ge=0, le=10_000_000)] | None = None


class CustomerDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: NonEmptyStr
    email: Annotated[str, Field(min_length=3, max_length=254)]
    phone: Annotated[str, Field(min_length=6, max_length=30)]
    policy_number: Annotated[str, Field(min_length=4, max_length=40)]
    preferred_contact_method: ContactMethod = "email"

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        if not _EMAIL_PATTERN.match(value.strip()):
            raise ValueError("Please enter a valid email address.")
        return value.strip()


class PropertyDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loss_address: Address
    property_habitable: bool
    temporary_accommodation_needed: bool


class DamageDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_of_loss: date
    time_of_loss: time | None = None
    peril: Literal["storm"] = "storm"
    incident_description: Annotated[str, Field(min_length=20, max_length=5000)]
    damaged_items: Annotated[list[DamagedItem], Field(min_length=1, max_length=25)]
    damage_ongoing: bool
    anyone_injured: bool
    utilities_affected: list[str] = Field(default_factory=list)
    emergency_repairs_done: bool
    third_party_involved: bool
    photos_supplied: bool
    customer_estimated_value: Annotated[float, Field(ge=0, le=10_000_000)] | None = None

    @field_validator("date_of_loss")
    @classmethod
    def _loss_cannot_be_in_the_future(cls, value: date) -> date:
        from datetime import datetime, timezone

        if value > datetime.now(timezone.utc).date():
            raise ValueError("The date of loss cannot be in the future.")
        return value


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------


class ClaimSubmissionRequest(BaseModel):
    """A complete storm-damage FNOL as submitted from the customer portal."""

    model_config = ConfigDict(extra="forbid")

    customer: CustomerDetails
    property: PropertyDetails
    damage: DamageDetails


# --------------------------------------------------------------------------
# Response
# --------------------------------------------------------------------------


class ClaimSummary(BaseModel):
    """The short summary shown on the confirmation screen."""

    model_config = ConfigDict(extra="forbid")

    policy_number: str
    customer_name: str
    peril: str
    date_of_loss: date
    loss_address: str
    damaged_item_count: int
    customer_estimated_value: float | None = None


class ClaimResponse(BaseModel):
    """What the API returns once a claim record exists."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(description="Customer-facing claim reference, e.g. CLM-2026-004217")
    claim_state: ClaimState = Field(description="Official business claim state")
    internal_status: str | None = Field(
        default=None,
        description="Internal workflow status. Null in Phase 1 -- nothing has processed the claim yet.",
    )
    submitted_at: str
    next_step: str = Field(description="Plain-language next step shown to the customer")
    summary: ClaimSummary


class ErrorDetail(BaseModel):
    """Customer-safe error payload. Never carries an exception or a stack trace."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Plain-language message safe to show a customer")
    fields: dict[str, str] | None = Field(
        default=None, description="Per-field validation messages, keyed by field path"
    )
