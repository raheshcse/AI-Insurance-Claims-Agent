"""WHAT is governed. Declarations only.

**Import rule, enforced:** this module imports only `vsl_core` and the standard
library. Never FastAPI, never an agent, never an SDK. A rule that needs those
belongs in `gates.py`.

Everything here is the Phase 0 governance policy catalogue made executable. The
PreNode and the three Invariants come from `docs/GOVERNANCE_POLICY_CATALOGUE.md`
and the Phase 3 mapping in `docs/ROUTING_MODEL.md` §9:

    E-01 → PreNode PN-01 `automation-confidence`
    E-05 → Invariant INV-01 `policy-in-force`
    E-04 → Invariant INV-02 `automated-authority-limit`
    E-06 → Invariant INV-03 `no-auto-approval-under-exclusion`

No construct type is invented and no Phase 0 mapping is changed. Four policy
instances have been ADDED by later phases, each flagged at its definition as not
deriving from a Phase 0 escalation rule, because Phase 0 had nothing for them to
govern:

    INV-04  no-customer-data-egress                  the governed LLM call
    PN-02   conversation-extraction-confidence       Phase 5, before Gemini
    INV-05  no-fabricated-claim-values               Phase 5, after Gemini
    INV-06  no-claim-decision-in-assistant-output    Phase 5, after Gemini

All four are `vsl_core.constructs.PreNode` / `Invariant` -- the same constructs,
at different commitment points. There is no "PostNode" here and no invented
interception mechanism: an Invariant evaluated on a model's output before that
output is used is an Invariant, applied where the architecture places it.
"""

from __future__ import annotations

import os
from typing import Any

from vsl_core.constructs import Fallback, Invariant, PreNode, TerminalState
from vsl_core.governance import (
    Binding,
    GovernanceAuthority,
    Proofing,
    Specification,
)
from vsl_core.metrics import (
    ROBUST_GAMMA_DEFAULT_THRESHOLD,
    AssuranceBasis,
    F2Modification,
    GammaEstimate,
)

# ---------------------------------------------------------------------------
# 1. Assurance bases -- the F1/F2 FACTS.
#
# Assurance is DERIVED, never asserted: we supply two facts and VSL computes
# the level. Every gate in this POC is OUTPUT_LAYER and therefore derives LOW.
# That is correct and is stated plainly rather than disguised: LOW means
# output-layer control -- it blocks a bad action but does not change how the
# model decides. The only route to HIGH is a formation-layer change (loss
# function, feature space, training), which this POC does not make.
# ---------------------------------------------------------------------------

OUTPUT_LAYER = AssuranceBasis(
    f1_pre_commitment=True,
    f2_modification=F2Modification.NONE,
)

# ---------------------------------------------------------------------------
# 2. Where automation stops.
# ---------------------------------------------------------------------------

CLAIM_AUTOMATION_SUSPENDED = TerminalState(
    name="claim-automation-suspended",
    description=(
        "Automated claim handling halted. A claims authority must re-enable it. "
        "The claim itself is unaffected -- it is handled by a person."
    ),
    entry_conditions=(
        "policy-in-force violated",
        "automated-authority-limit violated",
        "no-auto-approval-under-exclusion violated",
        "no-customer-data-egress violated",
        "no-fabricated-claim-values violated",
        "no-claim-decision-in-assistant-output violated",
    ),
    requires_human_authorised_transition=True,
)

# ---------------------------------------------------------------------------
# 3. Business thresholds. Policy, read from the environment.
#
# These are the same values Phase 2/3 read through app/domain/thresholds.py.
# docs/GOVERNANCE_POLICY_CATALOGUE.md says they belong here from Phase 4, and
# now they do -- this module is their home and the application reads them from
# here rather than the other way round.
#
# EVERY VALUE IS A POC PROPOSAL AWAITING BUSINESS APPROVAL (docs/DECISION_TABLE.md §7).
# ---------------------------------------------------------------------------


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DECISION_THRESHOLD = _float_env("DECISION_THRESHOLD", 0.80)
"""The probability boundary at which the business considers automated handling
warranted. gates.py imports it from here."""

CALIBRATION_ERROR = _float_env("CONFIDENCE_CALIBRATION_ERROR", 0.10)

AUTOMATED_AUTHORITY_LIMIT_NZD = _float_env("AUTOMATED_AUTHORITY_LIMIT_NZD", 20_000)

POC_ASSUMPTION_NOTE = (
    "POC-proposed threshold pending business approval - not an insurer-approved rule"
)


# ---------------------------------------------------------------------------
# 4. Gamma mapping. vsl-core ships NO Gamma estimator -- we supply one.
# ---------------------------------------------------------------------------


def confidence_gamma(
    p: float, calibration_error: float = CALIBRATION_ERROR
) -> GammaEstimate:
    """Odds of the prediction relative to the odds at the decision boundary.

    Gamma = 1.0 means "exactly on the boundary" -- no governance signal.

    CRITICAL: divide by the boundary odds. Using the raw p/(1-p) silently
    assumes a boundary of 0.5. Our boundary is 0.80, so that mistake would make
    every claim look far more confident than it is and the PreNode would wave
    through work it should stop. The failure is silent -- no error anywhere.
    """
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    t = min(max(DECISION_THRESHOLD, 1e-6), 1 - 1e-6)
    return GammaEstimate(
        gamma_hat=(p / (1 - p)) / (t / (1 - t)),
        delta_estimation_error=calibration_error,
        energy_gap_estimate=p - t,
    )


def effective_confidence_floor() -> float:
    """The confidence a claim must reach for PN-01 to pass.

    Derived, not asserted: solving gamma >= ROBUST_GAMMA_DEFAULT_THRESHOLD for
    p at boundary t. At t = 0.80 this is 0.8148.
    """
    t = min(max(DECISION_THRESHOLD, 1e-6), 1 - 1e-6)
    required_odds = ROBUST_GAMMA_DEFAULT_THRESHOLD * (t / (1 - t))
    return required_odds / (1 + required_odds)


# ---------------------------------------------------------------------------
# 5. Monitors and rules -- all async, per the VSL contract.
#
# A candidate is a plain mapping describing the action being proposed. Its
# shape is documented in gates.py, which is the only thing that builds one.
# ---------------------------------------------------------------------------


async def _automation_confidence_monitor(candidate: Any) -> GammaEstimate:
    return confidence_gamma(float(candidate["confidence"]))


async def _policy_in_force(candidate: Any) -> bool:
    """INV-01. Automated handling requires a policy in force at the date of loss.

    True = the automated action is acceptable for this claim.

    **Evaluated on the claim's own facts, always.** It used to short-circuit to
    True whenever routing had not proposed the automated route -- which meant
    that for a claim on a lapsed policy the governance layer reported
    "permitted", because it was answering a question nobody had asked. The
    Invariant now answers the question it is named for: may THIS claim be
    handled automatically? For a lapsed policy the answer is no, whatever the
    routing layer decided, and the evidence says so.
    """
    return bool(candidate.get("policy_in_force_at_loss")) and bool(
        candidate.get("peril_covered")
    )


async def _within_automated_authority(candidate: Any) -> bool:
    """INV-02. Automated handling must stay within the authority limit.

    **Evaluated on the claim's own value, always** -- see INV-01 for why. A
    NZD 42,000 claim is above the NZD 20,000 automated authority limit whether
    or not the routing layer already decided to send it to a person. Routing
    answers "where should this go"; this answers "may the system handle it
    without a person", and for 42,000 the answer is no.

    An UNKNOWN value is deliberately NOT a violation. An Invariant means
    "proceeding anyway is always wrong"; with no estimate we do not know that
    proceeding is wrong, we know that we do not know -- which is a review
    matter, and Phase 3's business rules already send it to a person. Treating
    uncertainty as a hard stop would make the Invariant fire on ignorance
    rather than on breach.
    """
    value = candidate.get("estimated_claim_value")
    if value is None:
        return True
    return float(value) <= AUTOMATED_AUTHORITY_LIMIT_NZD


async def _no_auto_approval_under_exclusion(candidate: Any) -> bool:
    """INV-03. Automated handling must not proceed where cover is in question.

    Automatically progressing a claim a policy may not cover is never
    acceptable -- it is a regulatory exposure, not a service-level trade-off.

    **Evaluated on the claim's own cover position, always** -- see INV-01.
    """
    if candidate.get("exclusions_possibly_engaged"):
        return False
    return candidate.get("cover_certainty") not in {"uncertain", "no_cover_basis"}


async def _no_customer_data_egress(candidate: Any) -> bool:
    """INV-04. Identifiable policyholder data must not leave for a third-party model.

    The X-Verba spec names an **LLM call** as a commitment point in its own
    right -- something the code cannot take back. For an insurer the thing that
    cannot be taken back is not the spend or the latency, it is the egress: once
    a policyholder's name, email, phone or street address has been sent to a
    third party, no amount of downstream handling retrieves it.

    So this is an Invariant, not a PreNode. There is no legitimate business
    reason to proceed anyway -- "we needed nicer prose" is not one -- which is
    exactly the test the spec gives for choosing between the two.

    The rule is deliberately literal: does any known identifier for THIS claim
    appear verbatim in the payload about to be sent? It does not attempt general
    PII detection, because a rule that guesses would either fire on ordinary
    traffic (and be switched off) or miss the real case (and be theatre). The
    agents compose narration facts from derived values, so on correct traffic
    this never fires -- like INV-01/02/03, it exists to catch the layer above
    being wrong.
    """
    identifiers = candidate.get("personal_identifiers") or ()
    payload = str(candidate.get("payload_text") or "")
    if not payload:
        return True
    lowered = payload.lower()
    return not any(
        value and str(value).strip().lower() in lowered for value in identifiers
    )


# ---------------------------------------------------------------------------
# 5b. Phase 5 -- rules evaluated on GENERATED OUTPUT.
#
# The approved baseline architecture places a VSL Invariant AFTER the Gemini
# call and BEFORE the generated output is used downstream:
#
#     PreNode + Monitor -> Gamma -> ALLOW -> Gemini -> Generated Output
#         -> VSL Invariant -> PASS -> Business Rules / Action Router
#
# These are the rules that stage evaluates. They are ordinary `vsl_core`
# Invariants -- the same construct as INV-01..04 -- evaluated at a different
# commitment point. No new VSL construct is introduced and nothing is called a
# "PostNode": an Invariant applied to a model's output before that output is
# used is still an Invariant.
#
# The candidate at this stage carries what the model produced, not what the
# claim says:
#     source_text          what the customer actually wrote, this turn
#     extracted            the structured values the model returned
#     assistant_message    the customer-facing sentence the model produced
# ---------------------------------------------------------------------------

_GROUNDED_FIELDS: tuple[str, ...] = (
    "policy_number",
    "estimated_damage_value",
)
"""Fields whose value must appear in the customer's own words.

Deliberately NOT every field. A date normalised from "yesterday", or a damage
area recognised from "the roof came off", is interpretation -- which is what the
model is for. A policy number or a dollar figure is a transcription: if it is
not in the message, the model produced it from nothing, and a fabricated policy
number or claim value is the failure mode with a real cost attached."""


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


async def _no_fabricated_claim_values(candidate: Any) -> bool:
    """INV-05. A transcribed value must exist in the customer's own message.

    This is the Invariant that makes "do not trust LLM extraction blindly"
    enforceable rather than aspirational. It runs on the model's OUTPUT, before
    any of that output reaches conversation state, so a hallucinated policy
    number cannot become a field the customer is later asked to confirm.

    The check is deliberately literal -- digits of the value against digits of
    the message -- for the same reason INV-04 is literal. A rule that tries to
    judge plausibility either fires on ordinary traffic and gets switched off,
    or misses the real case and is theatre.
    """
    extracted = candidate.get("extracted") or {}
    if not isinstance(extracted, dict):
        return False

    source = _digits(candidate.get("source_text") or "")
    for field_name in _GROUNDED_FIELDS:
        value = extracted.get(field_name)
        if value in (None, ""):
            continue
        needle = _digits(value)
        if not needle:
            # A non-numeric value for a field that should carry digits is not a
            # transcription of anything the customer said.
            return False
        if needle not in source:
            return False
    return True


_DECISION_LANGUAGE: tuple[str, ...] = (
    "approved",
    "approve your claim",
    "declined",
    "decline your claim",
    "denied",
    "rejected",
    "we will pay",
    "we'll pay",
    "payout",
    "settled",
    "settlement of",
    "covered under your policy",
    "not covered",
    "your claim is valid",
    "fraudulent",
)
"""Phrases that would make the assistant sound like it decided the claim.

POC-proposed and deliberately narrow. The assistant collects information; the
decision belongs to a person, and a customer who is told "your claim is
approved" by a chatbot has been told something the system has no authority to
say."""


async def _no_claim_decision_in_assistant_output(candidate: Any) -> bool:
    """INV-06. The assistant's words must not decide the claim.

    Evaluated on the generated message before it reaches the customer. The
    architecture separates AI intelligence from the insurance decision; this is
    that separation made non-bypassable at the point where the model could most
    easily break it -- by simply saying so.
    """
    message = str(candidate.get("assistant_message") or "").lower()
    if not message:
        return True
    return not any(phrase in message for phrase in _DECISION_LANGUAGE)


# ---------------------------------------------------------------------------
# 6. The constructs.
# ---------------------------------------------------------------------------

AUTOMATION_CONFIDENCE = PreNode(
    name="automation-confidence",
    description=(
        "Confidence must clear the robust Gamma threshold before a claim is "
        "handled automatically. Denial reroutes to human review -- a normal, "
        "expected outcome, not a governance failure."
    ),
    monitor=_automation_confidence_monitor,
    assurance_basis=OUTPUT_LAYER,
    gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
    fallback=Fallback(on_failure="ROUTE_TO_HUMAN_QUEUE", max_retries=0),
)
"""PN-01. Maps from Phase 3 escalation rule E-01 (docs/ROUTING_MODEL.md §9)."""

CONVERSATION_EXTRACTION_CONFIDENCE = PreNode(
    name="conversation-extraction-confidence",
    description=(
        "Confidence must clear the robust Gamma threshold before a customer "
        "message is sent to a language model for interpretation. Denial means "
        "the message is handled by the deterministic path and, where it "
        "matters, by a person -- a normal outcome, not a failure."
    ),
    monitor=_automation_confidence_monitor,
    assurance_basis=OUTPUT_LAYER,
    gamma_threshold=ROBUST_GAMMA_DEFAULT_THRESHOLD,
    fallback=Fallback(on_failure="ROUTE_TO_HUMAN_QUEUE", max_retries=0),
)
"""PN-02. **NEW in Phase 5**, and not a Phase 0 escalation rule -- Phase 0 had no
conversational interface to govern.

It is a separate PreNode from PN-01 because it asks a separate question. PN-01
asks "is the system confident enough to handle this CLAIM automatically". PN-02
asks "is the system confident enough to let a model interpret THIS MESSAGE".
Sharing one PreNode between them would mean a low-confidence claim silently
disabled the assistant's ability to read a sentence, which is not a governance
position anyone would defend on purpose."""

POLICY_IN_FORCE = Invariant(
    name="policy-in-force",
    description=(
        "A claim must not be handled automatically unless the policy was in "
        "force at the date of loss and the peril is covered."
    ),
    rule=_policy_in_force,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-01. Maps from E-05."""

AUTOMATED_AUTHORITY_LIMIT = Invariant(
    name="automated-authority-limit",
    description=(
        "Automated claim handling must stay within the automated authority "
        "limit. An authority limit that confidence can override is not a limit."
    ),
    rule=_within_automated_authority,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-02. Maps from E-04."""

NO_AUTO_APPROVAL_UNDER_EXCLUSION = Invariant(
    name="no-auto-approval-under-exclusion",
    description=(
        "A claim must not be handled automatically where a policy exclusion may "
        "be engaged or the cover position is not clear."
    ),
    rule=_no_auto_approval_under_exclusion,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-03. Maps from E-06."""

NO_CUSTOMER_DATA_EGRESS = Invariant(
    name="no-customer-data-egress",
    description=(
        "Identifiable policyholder data must not be sent to a third-party "
        "language model. Narration is composed from derived values only."
    ),
    rule=_no_customer_data_egress,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-04. Governs the LLM call, which the X-Verba spec names as a commitment
point in its own right (§1: "an LLM call, a payment, a database write...").

NEW in the governance refactor. It is not a Phase 0 escalation rule, because
Phase 0 had no LLM commitment to govern -- Phase 2 introduced the model and
Phase 4A made it a real network call. It derives from the standing project
constraint that no real customer data enters this system and none leaves it."""

NO_FABRICATED_CLAIM_VALUES = Invariant(
    name="no-fabricated-claim-values",
    description=(
        "A transcribed claim value produced by the model -- a policy number, a "
        "damage figure -- must appear in the customer's own message. The model "
        "may interpret; it may not supply facts the customer never gave."
    ),
    rule=_no_fabricated_claim_values,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-05. **NEW in Phase 5.** Evaluated on the model's OUTPUT, after the Gemini
call and before that output reaches conversation state."""

NO_CLAIM_DECISION_IN_ASSISTANT_OUTPUT = Invariant(
    name="no-claim-decision-in-assistant-output",
    description=(
        "The assistant must not tell a customer that a claim is approved, "
        "declined, covered, settled or fraudulent. It collects information; the "
        "decision belongs to a person."
    ),
    rule=_no_claim_decision_in_assistant_output,
    assurance_basis=OUTPUT_LAYER,
    on_violation=CLAIM_AUTOMATION_SUSPENDED,
)
"""INV-06. **NEW in Phase 5.** Evaluated on the generated message before it
reaches the customer."""

ALL_PRE_NODES: tuple[PreNode, ...] = (
    AUTOMATION_CONFIDENCE,
    CONVERSATION_EXTRACTION_CONFIDENCE,
)

AUTOMATED_ROUTE_INVARIANTS: tuple[Invariant, ...] = (
    POLICY_IN_FORCE,
    AUTOMATED_AUTHORITY_LIMIT,
    NO_AUTO_APPROVAL_UNDER_EXCLUSION,
)
"""Checked at the claim-state commitment (CP-09/CP-12). All three ask about the
automated ROUTE, so they are scoped to it and skip when it is not proposed."""

LLM_EGRESS_INVARIANTS: tuple[Invariant, ...] = (NO_CUSTOMER_DATA_EGRESS,)
"""Checked immediately before the LLM call (CP-13). A different commitment, so a
different rule set -- running the route Invariants here would ask the authority
limit about a narration payload, which is meaningless."""

GENERATED_OUTPUT_INVARIANTS: tuple[Invariant, ...] = (
    NO_FABRICATED_CLAIM_VALUES,
    NO_CLAIM_DECISION_IN_ASSISTANT_OUTPUT,
)
"""Phase 5. Evaluated AFTER the Gemini call and BEFORE the generated output is
used downstream -- the Invariant stage of the approved baseline architecture.

They could not be checked before the call: neither the extracted values nor the
assistant's sentence exists until the model has answered. That is the whole
reason this stage is where it is."""

ALL_INVARIANTS: tuple[Invariant, ...] = (
    *AUTOMATED_ROUTE_INVARIANTS,
    *LLM_EGRESS_INVARIANTS,
    *GENERATED_OUTPUT_INVARIANTS,
)
ALL_TERMINAL_STATES: tuple[TerminalState, ...] = (CLAIM_AUTOMATION_SUSPENDED,)

# Each gate needs its own denial_key. Two gates sharing one makes the second
# router read the first gate's denial -- with four gates, exactly the conditions
# for that bug.
DENIAL_KEYS: dict[str, str] = {
    AUTOMATION_CONFIDENCE.name: "vsl_denial__automation_confidence",
    CONVERSATION_EXTRACTION_CONFIDENCE.name: "vsl_denial__conversation_extraction_confidence",
    NO_FABRICATED_CLAIM_VALUES.name: "vsl_denial__no_fabricated_claim_values",
    NO_CLAIM_DECISION_IN_ASSISTANT_OUTPUT.name: "vsl_denial__no_claim_decision_in_assistant_output",
    POLICY_IN_FORCE.name: "vsl_denial__policy_in_force",
    AUTOMATED_AUTHORITY_LIMIT.name: "vsl_denial__automated_authority_limit",
    NO_AUTO_APPROVAL_UNDER_EXCLUSION.name: "vsl_denial__no_auto_approval_under_exclusion",
    NO_CUSTOMER_DATA_EGRESS.name: "vsl_denial__no_customer_data_egress",
}

# ---------------------------------------------------------------------------
# 7. The Specification -- the versioned, approved bundle.
#
# `activate()` refuses without a Binding, and a Binding refuses to exist
# without verified Proofing. That is the framework structurally enforcing
# "new versions require proofing and approval before activation", and it is
# why this is built rather than asserted.
#
# The authority below is a POC placeholder. A real deployment names a real
# governance authority with a real escalation contact.
# ---------------------------------------------------------------------------

CLAIMS_GOVERNANCE_AUTHORITY = GovernanceAuthority(
    name="Claims Governance Board (POC placeholder)",
    escalation_contact="claims-governance@example.invalid",
    response_time_sla_seconds=None,
)

_PROOFING = Proofing(
    verified=True,
    verified_against=(
        "docs/GOVERNANCE_POLICY_CATALOGUE.md and docs/ROUTING_MODEL.md §9 "
        "(POC: reviewed against the documented Phase 0 catalogue, not an "
        "independent formal proof)"
    ),
)

CLAIMS_SPECIFICATION: Specification = (
    Specification(
        name="home-storm-claims-automation",
        version="0.4.0-poc",
        approved_by=CLAIMS_GOVERNANCE_AUTHORITY,
        pre_nodes=ALL_PRE_NODES,
        invariants=ALL_INVARIANTS,
        terminal_states=ALL_TERMINAL_STATES,
    )
    .with_binding(
        Binding(proofing=_PROOFING, escalation_path="ROUTE_TO_HUMAN_QUEUE")
    )
    .activate()
)
"""The active governance specification for this POC.

Marked `-poc` deliberately: the thresholds it binds are proposals awaiting
business approval, so this is not an insurer-approved specification and should
not be presented as one.
"""
