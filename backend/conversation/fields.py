"""The field catalogue, and the deterministic validation behind it.

This module is the answer to "do not trust LLM extraction blindly". Nothing the
model returns becomes a collected value until a function here accepts it, and
every function here is ordinary Python with no model anywhere near it.

The division of labour:

    the model      reads a sentence and proposes values
    this module    decides whether a proposed value is a value at all
    the catalogue  decides what is still missing, from what was accepted

So the worst a broken, jailbroken or hallucinating model can do is propose
nonsense, which is rejected, or propose nothing, which leaves the field missing
and the assistant asking again. It cannot put a bad value into a claim.

Every field maps onto the FNOL in `app.schemas.claim`, so claim creation is a
projection. See `to_submission()` in `builder.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from conversation.contracts import ConversationStage

# ---------------------------------------------------------------------------
# Validators. Each returns (accepted_value, rejection_reason).
#
# A rejection reason is a sentence a customer could be shown. That is not
# decoration: the assistant repeats it back when asking again, so a vague
# "invalid input" would produce a vague, useless question.
# ---------------------------------------------------------------------------

Validated = tuple[Any, str | None]

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^[+()\d][\d\s()+-]{5,29}$")
_POLICY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{3,39}$")
_POSTCODE = re.compile(r"^\d{4}$")

_MAX_CLAIM_VALUE = 10_000_000.0
_MAX_BACKDATE_DAYS = 365 * 2


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _text(value: Any) -> str:
    return str(value or "").strip()


def validate_full_name(value: Any) -> Validated:
    name = _text(value)
    if len(name) < 2:
        return None, "I need your full name as it appears on the policy."
    if len(name) > 120:
        return None, "That name is longer than our system can accept."
    if not any(ch.isalpha() for ch in name):
        return None, "That does not look like a name."
    return name, None


def validate_email(value: Any) -> Validated:
    email = _text(value)
    if not _EMAIL.match(email):
        return None, "That does not look like an email address."
    return email, None


def validate_phone(value: Any) -> Validated:
    phone = _text(value)
    if not _PHONE.match(phone):
        return None, "That does not look like a contact phone number."
    return phone, None


def validate_policy_number(value: Any) -> Validated:
    """Shape only. Whether the policy EXISTS is the Policy Agent's job.

    Checking existence here would put policy lookup in the conversation layer
    and duplicate Phase 2's agent, which is exactly the duplication the phase
    brief warns about.
    """
    policy = _text(value).upper()
    if not _POLICY.match(policy):
        return None, "A policy number looks like POL-HOME-20117. Could you check yours?"
    return policy, None


def validate_date_of_loss(value: Any) -> Validated:
    """An exact date, or nothing.

    "Last week" is not a date. The model is allowed to normalise a relative
    expression it can resolve unambiguously ("yesterday"), but anything that
    reaches here must already be an ISO date -- and if it is not, we ask rather
    than pick a day, because a wrong date of loss can decide whether a policy
    was in force.
    """
    raw = _text(value)
    if not raw:
        return None, "I need the date the damage happened."
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return None, (
            "I could not pin that down to a specific date. What date did the "
            "damage happen?"
        )
    today = _today()
    if parsed > today:
        return None, "That date is in the future. When did the damage actually happen?"
    if parsed < today - timedelta(days=_MAX_BACKDATE_DAYS):
        return None, "That date is more than two years ago. Could you check it?"
    return parsed.isoformat(), None


def validate_description(value: Any) -> Validated:
    text = _text(value)
    if len(text) < 20:
        return None, (
            "Could you tell me a little more about what happened? A sentence or "
            "two is plenty."
        )
    if len(text) > 5000:
        return None, "That is longer than our system can accept."
    return text, None


def validate_areas(value: Any) -> Validated:
    """A non-empty list of short area names."""
    if isinstance(value, str):
        value = [part.strip() for part in re.split(r",| and ", value) if part.strip()]
    if not isinstance(value, list) or not value:
        return None, "Which parts of the property were damaged?"
    areas = [_text(item).title() for item in value if _text(item)]
    areas = [area for area in areas if 2 <= len(area) <= 60]
    if not areas:
        return None, "Which parts of the property were damaged?"
    return areas[:25], None


def validate_money(value: Any) -> Validated:
    """A number, or nothing. Never a guess.

    Accepts "$7,500" and "7500" because customers write both. Rejects a range
    ("five to ten thousand") rather than picking an end of it -- an estimate the
    customer did not give is a fabricated claim value, and INV-05 exists because
    that is the failure with a real cost attached.
    """
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        raw = _text(value).replace(",", "").replace("$", "").replace("NZD", "").strip()
        if not raw:
            return None, "Roughly what do you think the damage is worth?"
        try:
            amount = float(raw)
        except ValueError:
            return None, (
                "I could not read that as an amount. A rough figure in dollars "
                "is fine -- an estimate, not an exact quote."
            )
    if amount < 0:
        return None, "An estimate cannot be negative."
    if amount > _MAX_CLAIM_VALUE:
        return None, "That is larger than this system can accept."
    return round(amount, 2), None


def validate_address_line(value: Any) -> Validated:
    line = _text(value)
    if len(line) < 3:
        return None, "What is the street address of the damaged property?"
    return line[:200], None


def validate_suburb(value: Any) -> Validated:
    suburb = _text(value)
    if len(suburb) < 2:
        return None, "Which suburb is the property in?"
    return suburb[:200], None


def validate_city(value: Any) -> Validated:
    city = _text(value)
    if len(city) < 2:
        return None, "Which town or city is the property in?"
    return city[:200], None


def validate_postcode(value: Any) -> Validated:
    postcode = _text(value)
    if not _POSTCODE.match(postcode):
        return None, "A New Zealand postcode is four digits, for example 0604."
    return postcode, None


def validate_bool(value: Any) -> Validated:
    """A definite yes or no.

    `None` is not False. "I am not sure whether the house is safe" must not be
    recorded as "the house is safe", which is what a truthiness check would do.
    """
    if isinstance(value, bool):
        return value, None
    text = _text(value).lower()
    if text in {"true", "yes", "y", "yeah", "yep", "safe", "habitable"}:
        return True, None
    if text in {"false", "no", "n", "nope", "not safe", "uninhabitable"}:
        return False, None
    return None, "Sorry -- is that a yes or a no?"


# ---------------------------------------------------------------------------
# The catalogue.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """One piece of information the assistant collects."""

    name: str
    stage: ConversationStage
    question: str
    validate: Callable[[Any], Validated]
    required: bool = True
    label: str = ""

    free_text: bool = False
    """Does a valid answer to this field look like a paragraph?

    Almost nothing does. A name, a postcode, a phone number and a suburb are all
    a handful of words, so a five-sentence paragraph offered as one of them is
    not an answer that failed validation -- it is text that was never an answer
    at all, and the extraction layer should not hand it to a validator hoping
    for the best. `incident_description` is the one field where a paragraph IS
    the right answer.

    This is a ROUTING fact, not a validation rule: it decides which field a
    piece of text could be about. `validate` still decides whether the text is
    acceptable, and neither loosens the other."""

    def display(self) -> str:
        return self.label or self.name.replace("_", " ").capitalize()


FIELDS: tuple[FieldSpec, ...] = (
    # -- who ---------------------------------------------------------------
    FieldSpec(
        "full_name",
        ConversationStage.CUSTOMER_INFORMATION,
        "Could I start with your full name, as it appears on the policy?",
        validate_full_name,
        label="Name",
    ),
    FieldSpec(
        "email",
        ConversationStage.CUSTOMER_INFORMATION,
        "What is the best email address to reach you on?",
        validate_email,
        label="Email",
    ),
    FieldSpec(
        "phone",
        ConversationStage.CUSTOMER_INFORMATION,
        "And a contact phone number?",
        validate_phone,
        label="Phone",
    ),
    # -- policy ------------------------------------------------------------
    FieldSpec(
        "policy_number",
        ConversationStage.POLICY_INFORMATION,
        "What is your policy number? It looks like POL-HOME-20117.",
        validate_policy_number,
        label="Policy number",
    ),
    # -- incident ----------------------------------------------------------
    FieldSpec(
        "date_of_loss",
        ConversationStage.INCIDENT_INFORMATION,
        "What date did the damage happen?",
        validate_date_of_loss,
        label="Date of loss",
    ),
    FieldSpec(
        "incident_description",
        ConversationStage.INCIDENT_INFORMATION,
        "Could you describe what happened, in your own words?",
        validate_description,
        label="What happened",
        free_text=True,
    ),
    FieldSpec(
        "address_line_1",
        ConversationStage.INCIDENT_INFORMATION,
        "What is the street address of the damaged property?",
        validate_address_line,
        label="Address",
    ),
    FieldSpec(
        "suburb",
        ConversationStage.INCIDENT_INFORMATION,
        "Which suburb is that in?",
        validate_suburb,
        label="Suburb",
    ),
    FieldSpec(
        "city",
        ConversationStage.INCIDENT_INFORMATION,
        "And the town or city?",
        validate_city,
        label="City",
    ),
    FieldSpec(
        "postcode",
        ConversationStage.INCIDENT_INFORMATION,
        "What is the postcode there?",
        validate_postcode,
        label="Postcode",
    ),
    # -- damage ------------------------------------------------------------
    FieldSpec(
        "damaged_areas",
        ConversationStage.DAMAGE_INFORMATION,
        "Which parts of the property were damaged?",
        validate_areas,
        label="Damaged areas",
    ),
    FieldSpec(
        "estimated_damage_value",
        ConversationStage.DAMAGE_INFORMATION,
        (
            "Roughly what do you think the damage is worth? A rough figure is "
            "fine -- it does not commit you to anything."
        ),
        validate_money,
        label="Estimated damage",
    ),
    FieldSpec(
        "photos_supplied",
        ConversationStage.DAMAGE_INFORMATION,
        "Do you have photographs of the damage?",
        validate_bool,
        label="Photographs",
    ),
    # -- safety ------------------------------------------------------------
    FieldSpec(
        "property_habitable",
        ConversationStage.SAFETY_CHECK,
        "Is the property still safe to live in?",
        validate_bool,
        label="Safe to live in",
    ),
    FieldSpec(
        "anyone_injured",
        ConversationStage.SAFETY_CHECK,
        "Was anyone hurt?",
        validate_bool,
        label="Anyone hurt",
    ),
    FieldSpec(
        "damage_ongoing",
        ConversationStage.SAFETY_CHECK,
        "Is the damage still getting worse -- water still coming in, anything like that?",
        validate_bool,
        label="Still getting worse",
    ),
    FieldSpec(
        "emergency_repairs_done",
        ConversationStage.SAFETY_CHECK,
        "Have any emergency repairs been done, like a tarpaulin over the roof?",
        validate_bool,
        label="Emergency repairs",
    ),
    FieldSpec(
        "temporary_accommodation_needed",
        ConversationStage.SAFETY_CHECK,
        "Do you need somewhere else to stay?",
        validate_bool,
        label="Needs accommodation",
    ),
)

FIELDS_BY_NAME: dict[str, FieldSpec] = {spec.name: spec for spec in FIELDS}

REQUIRED_FIELDS: tuple[str, ...] = tuple(spec.name for spec in FIELDS if spec.required)

EXTRACTABLE_FIELDS: tuple[str, ...] = tuple(spec.name for spec in FIELDS)
"""What the model is permitted to propose. A field not in this tuple cannot be
set by extraction at all -- `claim_id`, `customer_confirmed` and anything else
the model might helpfully invent simply has no route in."""

STAGE_ORDER: tuple[ConversationStage, ...] = (
    ConversationStage.START,
    ConversationStage.CUSTOMER_INFORMATION,
    ConversationStage.POLICY_INFORMATION,
    ConversationStage.INCIDENT_INFORMATION,
    ConversationStage.DAMAGE_INFORMATION,
    ConversationStage.SAFETY_CHECK,
    ConversationStage.MISSING_INFORMATION,
    ConversationStage.REVIEW,
    ConversationStage.READY_FOR_CONFIRMATION,
    ConversationStage.CUSTOMER_CONFIRMATION,
    ConversationStage.CLAIM_CREATED,
)


def missing_fields(collected: dict[str, Any]) -> list[str]:
    """What is still required. Derived, never stored as an independent fact."""
    return [name for name in REQUIRED_FIELDS if collected.get(name) is None]


def next_field(collected: dict[str, Any]) -> FieldSpec | None:
    """The next thing to ask about, in catalogue order.

    Deterministic on purpose. Letting the model choose the next question makes
    the conversation's progress depend on the model's mood, and makes "why did
    it never ask about the postcode?" unanswerable.
    """
    for name in REQUIRED_FIELDS:
        if collected.get(name) is None:
            return FIELDS_BY_NAME[name]
    return None


def stage_for(collected: dict[str, Any], *, confirmed: bool = False) -> ConversationStage:
    """Which stage the conversation is in, derived from what is known."""
    if confirmed:
        return ConversationStage.CLAIM_CREATED
    pending = next_field(collected)
    if pending is None:
        return ConversationStage.READY_FOR_CONFIRMATION
    if not collected:
        return ConversationStage.START
    return pending.stage


def progress(collected: dict[str, Any]) -> tuple[int, int]:
    """(collected, total) over the required fields, for the progress indicator."""
    total = len(REQUIRED_FIELDS)
    have = sum(1 for name in REQUIRED_FIELDS if collected.get(name) is not None)
    return have, total
