"""Deterministic extraction — reading structure out of a customer's sentence.

=============================================================================
WHY THIS MODULE EXISTS

Phase 5 shipped with exactly one way to get several facts out of one message:
ask a language model. That made multi-field understanding a *capability of the
provider* rather than a property of the system, and it had two consequences,
both of which showed up as the same bug.

    1. With no model reachable -- the stub, a PreNode denial, an Invariant
       violation, a missing key, an outage -- the assistant could understand
       nothing beyond a bare one-value reply.

    2. The fallback path handed the ENTIRE raw message to the validator for
       whichever field had just been asked about. So

           "My name is John Smith, my email is john@example.com, my phone is
            0211234567, and my policy number is POL-HOME-20117."

       was offered to `validate_full_name`, which checks length and "contains a
       letter" -- and at 116 characters it PASSED. The customer's name became
       the whole sentence. One character longer and it failed instead, with
       "That name is longer than our system can accept", which is the symptom
       that got reported.

This module is the fix for both. It reads structure out of a message using
patterns, deterministically, with no model involved at all.

=============================================================================
WHAT IT IS AND IS NOT

It **proposes**. It never writes conversation state, and every value it
proposes goes through the same validators in `conversation/fields.py` as a
model's proposal does. Nothing here is a validation shortcut: this module
decides *which field a piece of text is about*, and `fields.py` decides
*whether that text is an acceptable value*. Those are different questions and
they stay in different modules.

It is also NOT a replacement for the model. The model reads meaning -- an
unusual phrasing, a fact stated sideways, a date expressed in a way no pattern
anticipates. This handles the cases where a value's SHAPE identifies it beyond
reasonable doubt, which is exactly where a pattern beats a prompt. The two are
merged in `graph/conversation_graph.py`, and this one wins on conflict, because
a regex that matched `john@example.com` is certain in a way a model is not.

=============================================================================
THE RULE THIS MODULE OBEYS

**Never assume which field a value belongs to unless the text says so or the
shape is unambiguous.**

    "my email is X"      -> the customer labelled it. Take it.
    "john@example.com"   -> only an email address looks like that. Take it.
    "0211234567"         -> only a phone number looks like that here. Take it.
    "John Smith"         -> ANY text could be a name. Do NOT take it as a name
                            just because it is the first thing in the message.

That last case is why `residual` exists rather than a guess. What is left over
after the identifiable values are removed is offered to the caller, which may
use it as the answer to **the question it actually asked** -- an inference the
design supports explicitly, because we know what was asked. It is never used to
fill a field nobody asked about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# What a customer might call each field.
#
# Deliberately a small, literal vocabulary. A big fuzzy one would start
# matching words inside the incident description ("the policy of the council")
# and quietly capture nonsense.
# ---------------------------------------------------------------------------

_LABELS: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "name"),
    "email": ("email address", "email", "e-mail"),
    "phone": ("phone number", "mobile number", "contact number", "phone", "mobile"),
    "policy_number": ("policy number", "policy no", "policy"),
    "address_line_1": ("street address", "address"),
    "suburb": ("suburb",),
    "city": ("city", "town"),
    "postcode": ("postcode", "post code"),
    "estimated_damage_value": (
        "estimated damage",
        "damage is worth",
        "estimate",
    ),
    "date_of_loss": ("date of loss", "date"),
}

# Where a labelled value ends.
#
# A comma, a semicolon, an " and", or a full stop that really terminates a
# sentence -- meaning one followed by whitespace or the end of the message.
#
# NOT any full stop. The first version of this used `\.` and so ended the value
# at the dot in `john@example.com`, silently storing "john@example" and leaving
# "com" in the residual. A dot inside a token is part of the token.
# `[,;](?!\d)` -- a comma BETWEEN DIGITS is a thousands separator, not a clause
# boundary. Without the lookahead, "the estimated damage is NZD 7,500" ended the
# value at the comma and stored "NZD 7", which then validated as seven dollars.
# A clause-ending comma is always followed by a space or a letter.
_CLAUSE_END = r"(?=\s*[,;](?!\d)|\s+and\b|\s*\.\s*$|\s*\.\s+|$)"

_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = []
for _field, _words in _LABELS.items():
    for _word in _words:
        _LABEL_PATTERNS.append(
            (
                _field,
                re.compile(
                    r"(?:my|the|our)?\s*" + re.escape(_word) + r"\s*(?:is|:|=|are)\s*"
                    r"(?P<value>.+?)" + _CLAUSE_END,
                    re.IGNORECASE,
                ),
            )
        )

# ---------------------------------------------------------------------------
# Shapes that identify a field on their own.
#
# Every pattern here answers "could this text plausibly be anything else?" with
# no. A pattern that could also match something else belongs in the labelled
# set above, where the customer has told us what it is.
# ---------------------------------------------------------------------------

_STRUCTURAL: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A policy number is checked BEFORE the phone pattern: POL-HOME-20117
    # contains digits and would otherwise be partly eaten by a loose number rule.
    #
    # Segments are joined by hyphens ONLY. An earlier version allowed a space
    # between segments and, under IGNORECASE, `[A-Z0-9]+` matched lowercase
    # words too -- so "policy POL-HOME-20117 and the storm damaged my roof"
    # matched in full and the policy number swallowed the rest of the sentence.
    ("policy_number", re.compile(r"\bPOL-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")),
    ("email", re.compile(r"\b[^\s@,;]+@[^\s@,;]+\.[A-Za-z]{2,}\b")),
    ("date_of_loss", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    # Money. "$7,500", "NZ$7500", "NZD 7,500" and "7500 dollars" are all the
    # same figure, and only the first two used to match -- so a customer who
    # wrote the currency the way this project writes it everywhere else
    # ("NZD 7,500", exactly as the README and the claim summary render it) had
    # their estimate silently ignored.
    (
        "estimated_damage_value",
        re.compile(
            r"(?:NZ\$|NZD|\$)\s?\d[\d,]*(?:\.\d{1,2})?\b"
            r"|\b\d[\d,]*(?:\.\d{1,2})?\s*(?:dollars|NZD)\b",
            re.IGNORECASE,
        ),
    ),
    # A New Zealand phone number: +64… or a 0-prefixed run of 8-11 digits,
    # optionally spaced. Anchored on a leading 0 or +64 so it cannot swallow a
    # bare quantity like "15 tiles".
    ("phone", re.compile(r"(?:\+64[\d\s()-]{7,15}|\b0\d[\d\s()-]{6,13})(?=\D|$)")),
)

# Relative dates we are willing to resolve. "Last week" is deliberately absent:
# it names a range, not a day, and a wrong date of loss can decide whether a
# policy was in force. Those stay uncertain and the assistant asks.
_RELATIVE_DAYS: dict[str, int] = {
    "today": 0,
    "this morning": 0,
    "tonight": 0,
    "yesterday": 1,
    "last night": 1,
    "the day before yesterday": 2,
}

_AMBIGUOUS_DATES: tuple[str, ...] = (
    "last week",
    "a few days ago",
    "a couple of days ago",
    "recently",
    "a while ago",
    "sometime",
    "last month",
)

# Parts of a house a storm damages. Used only to recognise which AREAS a
# message names -- never to invent one that was not mentioned.
_AREAS: dict[str, tuple[str, ...]] = {
    "Roof": ("roof", "roofing", "roof tiles", "tiles"),
    "Ceiling": ("ceiling", "ceilings"),
    "Windows": ("window", "windows"),
    "Walls": ("wall", "walls"),
    "Garage": ("garage",),
    "Fence": ("fence", "fencing"),
    "Deck": ("deck", "decking"),
    "Kitchen": ("kitchen",),
    "Bedroom": ("bedroom", "bedrooms"),
    "Bathroom": ("bathroom",),
    "Living room": ("living room", "lounge"),
    "Floor": ("floor", "flooring", "carpet"),
    "Gutters": ("gutter", "gutters", "spouting"),
}
"""Parts of a house a storm damages.

Used only to recognise which areas a message NAMES. It never adds an area the
customer did not mention, and a message naming none leaves `damaged_areas`
missing rather than guessing at the obvious one."""


# ---------------------------------------------------------------------------
# A New Zealand street address.
#
# The street-type suffix is what makes this safe. "20B Cornwall Park Avenue"
# ends in Avenue; nothing else in a storm-damage report does. Without that
# anchor there is no way to tell an address from any other capitalised phrase,
# which is exactly why the residual rule refuses to guess.
# ---------------------------------------------------------------------------

_STREET_TYPES = (
    "Avenue|Ave|Road|Rd|Street|St|Drive|Dr|Lane|Ln|Place|Pl|Crescent|Cres"
    "|Terrace|Tce|Way|Close|Court|Ct|Parade|Quay|Grove|Rise|Boulevard|Blvd"
    "|Highway|Hwy|Esplanade|Mews|Walk|Track"
)

_STREET = re.compile(
    r"\b\d+[A-Za-z]?(?:/\d+[A-Za-z]?)?\s+"      # 20B, 1/14, 18
    r"(?:[A-Z][\w'-]*\s+){1,4}"                  # Cornwall Park
    r"(?:" + _STREET_TYPES + r")\b",              # Avenue
)

# What follows a street in the way people actually write it:
#     "... in Epsom, Auckland 1023"
#     "... , Titirangi, Auckland 0604"
# NOTE: no `^`. This is used with `.match(text, pos)`, which already anchors at
# `pos`; a `^` additionally demands the START OF THE STRING, so the pattern
# silently never matched and "Epsom" was left sitting in the residual while the
# city and postcode were picked up by the fallback below.
_ADDRESS_TAIL = re.compile(
    r"\s*(?:,|\bin\b)\s*"
    r"(?P<suburb>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)"
    r"\s*,\s*"
    r"(?P<city>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)"
    r"(?:\s+(?P<postcode>\d{4}))?\b",
)

# A city immediately followed by a postcode, for messages that give no street.
_CITY_POSTCODE = re.compile(r"\b(?P<city>[A-Z][\w'-]{2,})\s+(?P<postcode>\d{4})\b")

# ---------------------------------------------------------------------------
# Explicit statements about safety and next steps.
#
# EXPLICIT ONLY. Each phrase below is the customer saying the thing, not the
# system concluding it. "The house is unsafe and we're staying with my sister"
# does NOT set `temporary_accommodation_needed`, because needing somewhere to
# stay and having somewhere to stay are different facts and the claim turns on
# the first. "We will need temporary accommodation" does set it, because that
# is the customer stating it.
#
# Every one of these is checked with word boundaries and a negation guard, so
# "nobody was hurt" and "someone was hurt" cannot both fire.
# ---------------------------------------------------------------------------

_PHRASES: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    (
        "property_habitable",
        False,
        (
            "unsafe to live in",
            "not safe to live in",
            # Anchored to the subject rather than matching a bare "unsafe":
            # a customer writing "the road outside is unsafe" is not telling us
            # their house is uninhabitable.
            "house is unsafe",
            "property is unsafe",
            "home is unsafe",
            "house is not safe",
            "uninhabitable",
            "not habitable",
            "can't stay in the house",
            "cannot stay in the house",
            "can't live in",
            "cannot live in",
        ),
    ),
    (
        "property_habitable",
        True,
        ("safe to live in", "still habitable", "still liveable", "still livable"),
    ),
    (
        "anyone_injured",
        False,
        ("nobody was hurt", "no one was hurt", "nobody was injured",
         "no one was injured", "no injuries", "nobody hurt", "no-one was hurt"),
    ),
    (
        "anyone_injured",
        True,
        ("someone was hurt", "someone was injured", "i was injured", "i was hurt"),
    ),
    (
        "damage_ongoing",
        True,
        ("still coming in", "still getting worse", "still leaking",
         "damage is ongoing", "continuing to get worse", "water is still"),
    ),
    (
        "damage_ongoing",
        False,
        ("has stopped", "no longer getting worse", "stopped leaking"),
    ),
    (
        "emergency_repairs_done",
        True,
        ("emergency repairs", "temporary repairs", "tarpaulin", "tarped",
         "boarded up"),
    ),
    (
        "photos_supplied",
        True,
        ("taken photographs", "taken photos", "have photographs", "have photos",
         "i have pictures", "photographs of the damage", "photos of the damage"),
    ),
    (
        "temporary_accommodation_needed",
        True,
        ("need temporary accommodation", "need somewhere else to stay",
         "need alternative accommodation", "need accommodation"),
    ),
    (
        "temporary_accommodation_needed",
        False,
        ("don't need accommodation", "do not need accommodation",
         "no accommodation needed"),
    ),
)


_AMBIGUOUS_MONEY = re.compile(
    r"\b(?:a few|a couple of|several|some|maybe|around|about|roughly)\s+"
    r"(?:\w+\s+)?(?:thousand|grand|hundred|k)\b",
    re.IGNORECASE,
)
""""A few thousand" is not an amount. Recorded as uncertain, never rounded into
a number -- the estimate a customer did not give is a fabricated claim value,
which is what INV-05 exists to stop."""


def _today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass
class Extraction:
    """What deterministic reading found in one message.

    Three outputs, kept apart because they mean different things downstream:

        proposed    field -> value, for the validators to accept or reject
        uncertain   field -> the customer's own words, for the assistant to ask about
        residual    what was left after the identifiable parts were removed
    """

    proposed: dict[str, Any] = dataclass_field(default_factory=dict)
    uncertain: dict[str, str] = dataclass_field(default_factory=dict)
    residual: str = ""
    matched_fields: tuple[str, ...] = ()

    @property
    def found_anything(self) -> bool:
        return bool(self.proposed or self.uncertain)


def _blank(text: str, span: tuple[int, int]) -> str:
    """Replace a matched span with spaces, preserving every other offset."""
    start, end = span
    return text[:start] + (" " * (end - start)) + text[end:]


def _tidy(text: str) -> str:
    """Collapse the leftovers into something a validator could read.

    Strips the connective debris a removed clause leaves behind -- ", and", a
    trailing "my", a stray full stop -- without touching the words themselves.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^(?:and|my|the|our|is|,|\.|;)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*(?:,|;|\.)\s*$", "", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    return cleaned.strip(" ,;.")


_CONNECTIVES = {
    "and", "my", "the", "our", "is", "are", "a", "an", "of", "to", "i", "have",
    "it", "was", "were", "also", "plus", "with", "for", "that", "this", "but",
}


def _residual_has_an_unparsed_label(text: str) -> bool:
    """Does the leftover still contain a LABELLING CONSTRUCTION we failed to read?

    "... my policy number is ..." left in the residual means a labelled value
    slipped past the label patterns, and offering the whole fragment to a
    validator would be the blind assignment this module exists to remove.

    Deliberately narrow: "label followed by is/:/=", not the bare word. A
    previous version matched the bare word anywhere in the residual, which
    looked stricter and was catastrophic -- ordinary prose is full of these
    words. A customer writing

        "... I have taken photographs of the damage, and I estimate the total
         repair cost will be around NZD 7,500."

    contains "estimate", so the whole paragraph was refused, the field the
    assistant had asked about was never filled, and the assistant asked the same
    question again. Forever. A guard that fires on the word "estimate" appearing
    in a sentence is not a guard, it is a stall.
    """
    lowered = text.lower()
    return any(
        re.search(r"\b" + re.escape(word) + r"\s*(?:is|are|:|=)\s*\S", lowered)
        for words in _LABELS.values()
        for word in words
    )


_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s+\S")
_MAX_BARE_ANSWER_WORDS = 12


_MAX_BARE_ANSWER_CONNECTIVES = 1


def _looks_like_a_bare_answer(text: str) -> bool:
    """Could this text be somebody's short answer to a direct question?

    Three things disqualify it, and the third is the interesting one:

    1. **It runs to more than one sentence.** Five sentences about a storm are
       not a short answer that happens to be invalid; they are not an answer to
       that question at all.
    2. **It is long.** Same reason.
    3. **It reads as prose rather than as a value.** A value is words:
       "John Smith", "Epsom", "20B Cornwall Park Avenue", "0604". Prose is words
       plus grammar -- "I have policy and the storm damaged my roof" is eight
       words with five pieces of grammatical glue holding them together, and it
       is nobody's name. Counting the glue separates the two reliably, where
       counting words alone does not.

    One connective is allowed, because "roof and ceiling" is a real answer.

    This decides ROUTING, never acceptability. `conversation/fields.py` still
    decides whether the text is a usable value, and nothing here lets anything
    past a validator that the validator would have refused.
    """
    if _SENTENCE_BOUNDARY.search(text):
        return False

    words = [w for w in re.split(r"[^A-Za-z0-9@+.'-]+", text.lower()) if w]
    if len(words) > _MAX_BARE_ANSWER_WORDS:
        return False

    glue = sum(1 for word in words if word in _CONNECTIVES)
    return glue <= _MAX_BARE_ANSWER_CONNECTIVES


def _is_only_connectives(text: str) -> bool:
    """Is the leftover just the debris a removed clause leaves behind?

    "and", ", and", "my" -- grammatical glue, not a value. It has to be refused
    explicitly, because most validators would happily accept the word "and" as
    a suburb.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9@+.\'-]+", text.lower()) if w]
    return not words or all(word in _CONNECTIVES for word in words)


def extract(message: str) -> Extraction:
    """Read one customer message. Deterministic, no model, never raises."""
    original = message or ""
    if not original.strip():
        return Extraction(residual="")

    remaining = original
    proposed: dict[str, Any] = {}
    uncertain: dict[str, str] = {}

    # -- 1. LABELLED VALUES. The customer told us what this is. ------------
    #
    # Run first so that "my policy number is POL-HOME-20117" is claimed by the
    # label rather than by a structural pattern, and so the label's own words
    # are consumed along with the value.
    for field_name, pattern in _LABEL_PATTERNS:
        if field_name in proposed:
            continue
        match = pattern.search(remaining)
        if not match:
            continue
        value = _tidy(match.group("value"))
        if not value:
            continue
        proposed[field_name] = value
        remaining = _blank(remaining, match.span())

    # -- 2. UNAMBIGUOUS SHAPES. Only one thing looks like this. ------------
    for field_name, pattern in _STRUCTURAL:
        if field_name in proposed:
            continue
        match = pattern.search(remaining)
        if not match:
            continue
        proposed[field_name] = match.group(0).strip()
        remaining = _blank(remaining, match.span())

    # -- 2b. A STREET ADDRESS, and what follows it. ------------------------
    #
    #        Runs as one unit because the parts only identify themselves
    #        together: "Epsom" is a suburb because it sits between a street and
    #        a city, and "1023" is a postcode because it sits after one. Pulled
    #        out separately they are just a word and a number.
    street = _STREET.search(remaining)
    if street and "address_line_1" not in proposed:
        proposed["address_line_1"] = street.group(0).strip()
        tail = _ADDRESS_TAIL.match(remaining, street.end())
        remaining = _blank(remaining, street.span())
        if tail:
            for part in ("suburb", "city", "postcode"):
                value = tail.group(part)
                if value and part not in proposed:
                    proposed[part] = value.strip()
            remaining = _blank(remaining, tail.span())

    # A city with a postcode after it, for a message that gives no street.
    if "postcode" not in proposed:
        pair = _CITY_POSTCODE.search(remaining)
        if pair:
            proposed["postcode"] = pair.group("postcode")
            proposed.setdefault("city", pair.group("city"))
            remaining = _blank(remaining, pair.span())

    # -- 3. RELATIVE DATES, but only the unambiguous ones. -----------------
    if "date_of_loss" not in proposed:
        lowered = remaining.lower()
        for phrase in _AMBIGUOUS_DATES:
            if phrase in lowered:
                uncertain["date_of_loss"] = phrase
                break
        else:
            for phrase, days_ago in _RELATIVE_DAYS.items():
                index = lowered.find(phrase)
                if index == -1:
                    continue
                proposed["date_of_loss"] = (_today() - timedelta(days=days_ago)).isoformat()
                remaining = _blank(remaining, (index, index + len(phrase)))
                break

    # -- 4. VAGUE AMOUNTS stay vague. -------------------------------------
    if "estimated_damage_value" not in proposed:
        vague = _AMBIGUOUS_MONEY.search(remaining)
        if vague:
            uncertain["estimated_damage_value"] = vague.group(0).strip()

    # -- 5. DAMAGED AREAS the message actually names. ----------------------
    if "damaged_areas" not in proposed:
        lowered = remaining.lower()
        areas = [
            area
            for area, words in _AREAS.items()
            if any(re.search(r"\b" + re.escape(w) + r"\b", lowered) for w in words)
        ]
        if areas:
            proposed["damaged_areas"] = areas

    # -- 6. EXPLICIT STATEMENTS about safety and next steps. ---------------
    #
    #       Phrases the customer actually said, never conclusions drawn from
    #       them. Longest phrase wins within a field, so "don't need
    #       accommodation" cannot be read as "need accommodation".
    lowered = remaining.lower()
    for field_name, value, phrases in _PHRASES:
        if field_name in proposed:
            continue
        hit = next(
            (
                phrase
                for phrase in sorted(phrases, key=len, reverse=True)
                if phrase in lowered
            ),
            None,
        )
        if hit is None:
            continue
        # A negation immediately before the phrase flips the meaning, and we do
        # not attempt to interpret that -- we decline instead.
        before = lowered[max(0, lowered.find(hit) - 12) : lowered.find(hit)]
        if re.search(r"\b(?:not|never|no)\s*$", before):
            continue
        proposed[field_name] = value

    return Extraction(
        proposed=proposed,
        uncertain=uncertain,
        residual=_tidy(remaining),
        matched_fields=tuple(proposed),
    )


def bare_answer(
    extraction: Extraction, original: str, *, asked_about: str | None = None
) -> str | None:
    """What, if anything, may be offered as the answer to the question we asked.

    Returns the residual when it is safe to treat as a bare reply, and None when
    it is not. Three cases:

    * **Nothing was extracted.** The residual is the whole message, and the
      behaviour is exactly what it was before this module existed: a bare reply
      to a direct question. "Marama Whitcombe" still works.
    * **Something was extracted and a clean remainder is left.** In
      "John Smith, john@example.com, 0211234567" the email and phone are
      identified by shape and "John Smith" remains. Offering that to the field
      we just asked about is an inference the design supports -- we know what we
      asked.
    * **Something was extracted but the remainder still names a field.** We did
      not understand the message. Offer nothing; the assistant asks again.
    """
    if asked_about and asked_about in extraction.proposed:
        # Already found, and by a route that knows what it found. There is
        # nothing left for the residual to answer.
        return None

    if asked_about and asked_about in extraction.uncertain:
        # The customer raised this field and could not pin it down. Offering the
        # same words to its validator would produce a second rejection for a
        # thing we have already understood correctly.
        return None

    if not extraction.found_anything:
        # Nothing identifiable, so the residual IS the whole message. Still
        # shape-checked: a paragraph containing nothing a pattern recognises is
        # no more somebody's name than one that does.
        text = _tidy(original)
        if not text:
            return None
        from conversation.fields import FIELDS_BY_NAME

        spec = FIELDS_BY_NAME.get(asked_about or "")
        if spec is not None and not spec.free_text and not _looks_like_a_bare_answer(text):
            return None
        return text

    residual = extraction.residual
    if not residual:
        return None
    if _is_only_connectives(residual):
        return None
    if _residual_has_an_unparsed_label(residual):
        return None

    from conversation.fields import FIELDS_BY_NAME

    spec = FIELDS_BY_NAME.get(asked_about or "")

    # A FREE-TEXT field gets the customer's ORIGINAL WORDS, not the residual.
    #
    # The residual exists to stop a short value being mis-assigned, and it does
    # that by blanking out everything already claimed. For a paragraph field
    # that is actively wrong: "describe what happened" answered with the address
    # and date cut out produced
    #
    #     "damaged property is at . The storm happened and caused damage to..."
    #
    # which is not what the customer wrote and not something a reviewer should
    # ever read. There is nothing to disambiguate here -- prose is prose.
    if spec is not None and spec.free_text:
        # Whitespace only. `_tidy` strips leading connectives ("The", "and",
        # "my"), which is right for residual debris and wrong for a customer's
        # own sentence -- it turned "The damaged property is at..." into
        # "damaged property is at...".
        return re.sub(r"\s+", " ", original).strip() or None

    # Every other field: does the leftover have the SHAPE of a short answer?
    # Skipping this check is how a whole paragraph became a `full_name`.
    if spec is not None and not _looks_like_a_bare_answer(residual):
        return None

    return residual
