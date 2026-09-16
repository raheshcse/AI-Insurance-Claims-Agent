"""HOW it is enforced. The single call site.

Gates compile once at import. A `CompiledGate` is simply `async (candidate) -> None`,
raising on denial — that is the whole protocol.

=============================================================================
THE ENFORCEMENT PROPERTY

`govern_automated_route()` takes the side effect as a callable and invokes it
**once, at the end, only on the proceed path**. Every denial path returns before
that line. So a denied action is not "checked and then skipped" — it is
unreachable, because the only reference to it lives after every gate.

That is what makes F1 (pre-commitment) true rather than asserted: the gates are
awaited before the commitment, and no denial branch can reach it.
=============================================================================

Ledger entries are written in causal order with `caused_by` set on every one:

    MONITOR ──caused_by──> PRE_NODE ──caused_by──> VERIFICATION
                                                        │
                                        (INSUFFICIENT)  ├──> TERMINAL ──> HUMAN_AUTHORISED_TRANSITION
                                                        └──> SPECIFICATION_UPDATE

Without `caused_by`, `audit()` falls back to a "same identity, later timestamp"
heuristic that can match an unrelated PRE_NODE under concurrency and report a
false pass. A claims queue is exactly that concurrency.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypeVar

from vsl_core.exceptions import AutomationDeniedException, InvariantViolation
from vsl_core.governance import Evidence, request_re_enablement
from vsl_core.identity import IdentityKey, Instance
from vsl_core.ledger import LedgerEntryType, VerificationResult
from vsl_langgraph import LangGraphAdapter

from governance.ledger import ledger as default_ledger
from governance.policy import (
    ALL_INVARIANTS,
    AUTOMATED_AUTHORITY_LIMIT_NZD,
    AUTOMATED_ROUTE_INVARIANTS,
    CONVERSATION_EXTRACTION_CONFIDENCE,
    GENERATED_OUTPUT_INVARIANTS,
    LLM_EGRESS_INVARIANTS,
    AUTOMATION_CONFIDENCE,
    CLAIMS_GOVERNANCE_AUTHORITY,
    CLAIMS_SPECIFICATION,
    DENIAL_KEYS,
    effective_confidence_floor,
)

logger = logging.getLogger("claims.governance")

T = TypeVar("T")

IDENTITY = "home-storm-claims-automation"

# Gates compile once, at import. The LangGraph adapter compiles the SAME
# PreNode and Invariant objects the plain-Python adapter would -- policy.py
# does not change when the wiring does.
_adapter = LangGraphAdapter()
confidence_gate = _adapter.compile_pre_node(AUTOMATION_CONFIDENCE)
invariant_gates = {
    invariant.name: _adapter.compile_invariant(invariant) for invariant in ALL_INVARIANTS
}

GovernedAction = Literal["proceed", "human_queue", "action_denied", "suspended"]


@dataclass
class GovernanceOutcome:
    """What the gate decided, and the evidence trail it left."""

    action: GovernedAction
    decision_id: str
    claim_id: str
    pre_node_denied: bool = False
    denial_reason: str | None = None
    invariant_violated: str | None = None
    terminal_state: str | None = None
    fallback: str | None = None
    assurance_level: str | None = None
    gamma_threshold: float | None = None
    confidence: float | None = None
    confidence_floor: float | None = None
    ledger_entry_ids: list[str] = field(default_factory=list)
    side_effect_performed: bool = False
    observed_value: float | None = None
    """The claim value the Invariants judged. Recorded so the evidence can show
    the comparison -- "42,000 against a 20,000 limit" -- not just the verdict."""
    specification: str = f"{CLAIMS_SPECIFICATION.name} v{CLAIMS_SPECIFICATION.version}"

    automated_action_attempted: bool = False
    """Did the layer above actually try to take the automated action?

    This is what separates a routine denial from an incident. A NZD 42,000 claim
    that routing correctly sent to a person, denied by INV-02, is the system
    working: nothing is stuck and no one needs to un-stick it. The same denial
    when routing DID propose automation means a bug just tried to take a
    prohibited action -- that is what a TerminalState is for."""

    @property
    def permitted(self) -> bool:
        return self.action == "proceed"

    @property
    def automated_action_allowed(self) -> bool:
        """The question a reader actually wants answered.

        False for every outcome except `proceed`. Distinct from `permitted` so
        that no caller can read "the gate returned" as "the automated action was
        approved"."""
        return self.action == "proceed"


# ---------------------------------------------------------------------------
# Suspension registry.
#
# KNOWN LIMITATION, stated rather than papered over: this lives in process
# memory. It does not survive a restart and is not shared across workers. The
# production direction is Redis (or equivalent), with state re-derived at
# startup by scanning the ledger for a TERMINAL with no later
# HUMAN_AUTHORISED_TRANSITION. `rebuild_suspensions_from_ledger()` below is
# that re-derivation, implemented and tested, so the production move is a
# storage swap rather than a redesign.
# ---------------------------------------------------------------------------


@dataclass
class _Suspension:
    claim_id: str
    terminal_state: str
    invariant: str
    terminal_entry_id: str
    decision_id: str


class _SuspensionRegistry:
    def __init__(self) -> None:
        self._items: dict[str, _Suspension] = {}
        self._instances: dict[str, Instance] = {}
        self._lock = threading.Lock()

    def instance_for(self, claim_id: str) -> Instance:
        with self._lock:
            instance = self._instances.get(claim_id)
            if instance is None:
                instance = Instance.new(IdentityKey(value=IDENTITY))
                self._instances[claim_id] = instance
            return instance

    def replace_instance(self, claim_id: str, instance: Instance) -> None:
        with self._lock:
            self._instances[claim_id] = instance

    def get(self, claim_id: str) -> _Suspension | None:
        with self._lock:
            return self._items.get(claim_id)

    def suspend(self, suspension: _Suspension) -> None:
        with self._lock:
            self._items[suspension.claim_id] = suspension

    def clear(self, claim_id: str) -> _Suspension | None:
        with self._lock:
            return self._items.pop(claim_id, None)

    def all(self) -> dict[str, _Suspension]:
        with self._lock:
            return dict(self._items)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._instances.clear()


suspensions = _SuspensionRegistry()


# ---------------------------------------------------------------------------
# The governed call site.
# ---------------------------------------------------------------------------


async def govern_automated_route(
    candidate: dict[str, Any],
    *,
    perform: Callable[[], T],
    ledger: Any | None = None,
) -> tuple[GovernanceOutcome, T | None]:
    """CP-14. Gate the AUTOMATED CLAIM ACTION, then perform it.

    The commitment this protects is "handle this claim without a person" -- in
    this POC, moving it to Assessment with `assessment_complete` and taking it
    off the review queue. Nothing is paid or settled; that is stated rather than
    implied.

    **The Invariants are evaluated on the claim's own facts, always.** Routing
    decides where a claim should go; this decides whether the system is
    permitted to handle it automatically at all. They are separate questions and
    the evidence records both answers.

    `automated_route_proposed` no longer gates whether the rules RUN. It records
    whether the layer above actually attempted the action, which decides only
    whether a violation also enters the TerminalState.

    `candidate` carries the facts the policy evaluates:
        claim_id, confidence, automated_route_proposed,
        policy_in_force_at_loss, peril_covered, estimated_claim_value,
        exclusions_possibly_engaged, cover_certainty

    `perform` is the governed side effect. It is called exactly once, on the
    last line of the proceed path, and is unreachable from every denial path.
    """
    book = ledger or default_ledger
    claim_id = str(candidate.get("claim_id", "unknown"))
    decision_id = str(uuid.uuid4())
    instance = suspensions.instance_for(claim_id)
    identity = instance.identity_key.value
    entries: list[str] = []

    confidence = float(candidate.get("confidence") or 0.0)
    floor = effective_confidence_floor()

    outcome = GovernanceOutcome(
        action="suspended",
        decision_id=decision_id,
        claim_id=claim_id,
        assurance_level=AUTOMATION_CONFIDENCE.assurance_level.value,
        gamma_threshold=AUTOMATION_CONFIDENCE.gamma_threshold,
        confidence=confidence,
        confidence_floor=floor,
        ledger_entry_ids=entries,
    )

    # -- (a) MONITOR, for EVERY request, so audit check 1 has continuous
    #        evidence rather than only-on-incident evidence.
    monitor = book.write_monitor(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        drift_detected=confidence < floor,
        extra_payload={
            "claim_id": claim_id,
            "confidence": round(confidence, 4),
            "confidence_floor": round(floor, 4),
            "specification": outcome.specification,
        },
    )
    entries.append(monitor.entry_id)

    # -- (b) Already suspended? Nothing proceeds until a human re-enables.
    existing = suspensions.get(claim_id)
    if existing is not None:
        outcome.action = "suspended"
        outcome.terminal_state = existing.terminal_state
        outcome.invariant_violated = existing.invariant
        logger.warning(
            "governance.blocked_by_suspension claim_id=%s terminal_state=%s decision_id=%s",
            claim_id,
            existing.terminal_state,
            decision_id,
        )
        return outcome, None

    # -- (c) PRE-NODE. Soft. Denial reroutes; it never silently drops.
    denied: AutomationDeniedException | None = None
    try:
        await confidence_gate({"confidence": confidence})
    except AutomationDeniedException as exc:
        denied = exc

    pre_node = book.write(
        LedgerEntryType.PRE_NODE,
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        caused_by=monitor.entry_id,
        payload={
            "claim_id": claim_id,
            "pre_node": AUTOMATION_CONFIDENCE.name,
            "denied": denied is not None,
            "assurance_level": AUTOMATION_CONFIDENCE.assurance_level.value,
            "gamma_threshold": AUTOMATION_CONFIDENCE.gamma_threshold,
            "denial_key": DENIAL_KEYS[AUTOMATION_CONFIDENCE.name],
        },
    )
    entries.append(pre_node.entry_id)

    if denied is not None:
        # Governance WORKED. SUFFICIENT, not INSUFFICIENT -- writing
        # INSUFFICIENT here would make audit check 4 demand a
        # SPECIFICATION_UPDATE for every ordinary low-confidence claim, and
        # the audit would fail permanently on routine traffic.
        verification = book.write_verification(
            identity_key=identity,
            instance_id=instance.instance_id,
            decision_id=decision_id,
            caused_by=pre_node.entry_id,
            result=VerificationResult.SUFFICIENT,
            extra_payload={
                "claim_id": claim_id,
                "outcome": "routed_to_human_queue",
                "fallback": AUTOMATION_CONFIDENCE.fallback.on_failure,
                "reason": denied.reason,
            },
        )
        entries.append(verification.entry_id)

        outcome.action = "human_queue"
        outcome.pre_node_denied = True
        outcome.denial_reason = denied.reason
        outcome.fallback = AUTOMATION_CONFIDENCE.fallback.on_failure
        logger.info(
            "governance.pre_node_denied claim_id=%s pre_node=%s fallback=%s "
            "confidence=%.4f floor=%.4f decision_id=%s",
            claim_id,
            AUTOMATION_CONFIDENCE.name,
            outcome.fallback,
            confidence,
            floor,
            decision_id,
        )
        return outcome, None

    # -- (d) INVARIANTS. Non-bypassable. Only the ones that ask about the
    #        automated ROUTE -- the LLM-egress Invariant governs a different
    #        commitment and is checked by `govern_llm_narration` instead.
    attempted = bool(candidate.get("automated_route_proposed"))
    outcome.automated_action_attempted = attempted
    raw_value = candidate.get("estimated_claim_value")
    outcome.observed_value = float(raw_value) if raw_value is not None else None

    for invariant in AUTOMATED_ROUTE_INVARIANTS:
        try:
            await invariant_gates[invariant.name](candidate)
        except InvariantViolation as exc:
            # The automated action is denied either way. What differs is whether
            # the claim is SUSPENDED as well.
            #
            #   not attempted -> routing and governance agree. The action was
            #                    never going to be taken, nothing is stuck, and
            #                    no human re-enablement is owed. Recorded as
            #                    SUFFICIENT: governance worked, exactly like a
            #                    PreNode denial. Writing INSUFFICIENT here would
            #                    demand a SPECIFICATION_UPDATE for every large
            #                    claim and the audit would fail permanently on
            #                    routine traffic -- the trap the spec names.
            #
            #   attempted     -> the layer above tried to do the prohibited
            #                    thing. That IS an incident: INSUFFICIENT,
            #                    TerminalState, and no automated way out.
            if not attempted:
                verification = book.write_verification(
                    identity_key=identity,
                    instance_id=instance.instance_id,
                    decision_id=decision_id,
                    caused_by=pre_node.entry_id,
                    result=VerificationResult.SUFFICIENT,
                    extra_payload={
                        "claim_id": claim_id,
                        "commitment": "automated_claim_action",
                        "outcome": "automated_action_denied",
                        "invariant": exc.invariant_name,
                        "denial_key": DENIAL_KEYS[invariant.name],
                        "reason": exc.reason,
                        "observed_value": candidate.get("estimated_claim_value"),
                        "threshold_value": AUTOMATED_AUTHORITY_LIMIT_NZD
                        if invariant.name == "automated-authority-limit"
                        else None,
                        "assurance_level": invariant.assurance_level.value,
                        "automated_action_attempted": False,
                        "detail": (
                            "The automated claim action is not permitted for this "
                            "claim. Routing had already selected a non-automated "
                            "path, so nothing is suspended -- the claim proceeds "
                            "to a person."
                        ),
                    },
                )
                entries.append(verification.entry_id)

                outcome.action = "action_denied"
                outcome.invariant_violated = exc.invariant_name
                outcome.fallback = "ROUTE_TO_HUMAN_QUEUE"
                outcome.denial_reason = exc.reason
                logger.info(
                    "governance.automated_action_denied claim_id=%s invariant=%s "
                    "attempted=False decision_id=%s",
                    claim_id,
                    exc.invariant_name,
                    decision_id,
                )
                return outcome, None

            verification = book.write_verification(
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=pre_node.entry_id,
                result=VerificationResult.INSUFFICIENT,  # governance FAILED
                extra_payload={
                    "claim_id": claim_id,
                    "commitment": "automated_claim_action",
                    "invariant": exc.invariant_name,
                    "denial_key": DENIAL_KEYS[invariant.name],
                    "reason": exc.reason,
                    "observed_value": candidate.get("estimated_claim_value"),
                    "threshold_value": AUTOMATED_AUTHORITY_LIMIT_NZD
                    if invariant.name == "automated-authority-limit"
                    else None,
                    "assurance_level": invariant.assurance_level.value,
                    "automated_action_attempted": True,
                },
            )
            entries.append(verification.entry_id)

            terminal = book.write(
                LedgerEntryType.TERMINAL,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "terminal_state": exc.terminal_state_name,
                    "invariant": exc.invariant_name,
                    "reason": exc.reason,
                },
            )
            entries.append(terminal.entry_id)

            # Audit check 4: every INSUFFICIENT VERIFICATION needs a
            # SPECIFICATION_UPDATE caused_by it. The violation is registered
            # against the active specification for review -- this is the
            # record that governance failed and the policy must be looked at,
            # not a rubber stamp.
            spec_update = book.write(
                LedgerEntryType.SPECIFICATION_UPDATE,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "specification": outcome.specification,
                    "invariant": exc.invariant_name,
                    "status": "review_required",
                    "detail": (
                        "An Invariant was violated on live traffic. The active "
                        "specification is registered for governance review; no "
                        "change has been made to it automatically."
                    ),
                },
            )
            entries.append(spec_update.entry_id)

            suspensions.suspend(
                _Suspension(
                    claim_id=claim_id,
                    terminal_state=exc.terminal_state_name or "",
                    invariant=exc.invariant_name or invariant.name,
                    terminal_entry_id=terminal.entry_id,
                    decision_id=decision_id,
                )
            )

            outcome.action = "suspended"
            outcome.invariant_violated = exc.invariant_name
            outcome.terminal_state = exc.terminal_state_name
            logger.warning(
                "governance.invariant_violated claim_id=%s invariant=%s "
                "terminal_state=%s decision_id=%s",
                claim_id,
                exc.invariant_name,
                exc.terminal_state_name,
                decision_id,
            )
            return outcome, None

    # -- (e) All gates passed.
    verification = book.write_verification(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        caused_by=pre_node.entry_id,
        result=VerificationResult.SUFFICIENT,
        extra_payload={"claim_id": claim_id, "outcome": "approved"},
    )
    entries.append(verification.entry_id)
    outcome.action = "proceed"

    # -- (f) ONLY NOW may the side effect fire. Every denial path returned
    #        above; this line is unreachable from any of them.
    result = perform()
    outcome.side_effect_performed = True

    logger.info(
        "governance.permitted claim_id=%s decision_id=%s confidence=%.4f",
        claim_id,
        decision_id,
        confidence,
    )
    return outcome, result


# ---------------------------------------------------------------------------
# The only way out of a TerminalState.
# ---------------------------------------------------------------------------


def re_enable_automation(
    claim_id: str,
    *,
    authorised_by: str,
    root_cause_analysis: str,
    specification_update_proposal: str,
    ledger: Any | None = None,
) -> dict[str, Any]:
    """Human re-enablement. The sanctioned exit from a terminal state.

    Routed through `vsl_core.governance.request_re_enablement`, which produces
    the new Instance and the HumanAuthorisedTransition *together* so a caller
    cannot obtain one without the other. Evidence is required and validated by
    the framework — an empty root cause is refused at construction.

    Writing the HUMAN_AUTHORISED_TRANSITION caused_by the TERMINAL entry is
    what satisfies audit check 5. Until a human does this, the audit correctly
    reports an open terminal state.
    """
    book = ledger or default_ledger
    suspension = suspensions.get(claim_id)
    if suspension is None:
        raise ValueError(f"Claim {claim_id} is not suspended.")

    instance = suspensions.instance_for(claim_id)
    evidence = Evidence(
        root_cause_analysis=root_cause_analysis,
        specification_update_proposal=specification_update_proposal,
    )
    new_instance, transition = request_re_enablement(
        instance,
        CLAIMS_GOVERNANCE_AUTHORITY,
        authorised_by=authorised_by,
        evidence=evidence,
    )

    hat = book.write(
        LedgerEntryType.HUMAN_AUTHORISED_TRANSITION,
        identity_key=instance.identity_key.value,
        instance_id=instance.instance_id,
        decision_id=suspension.decision_id,
        caused_by=suspension.terminal_entry_id,
        payload={
            "claim_id": claim_id,
            "terminal_state": suspension.terminal_state,
            "invariant": suspension.invariant,
            "authorised_by": authorised_by,
            "authority": transition.authority.name,
            "evidence_hash": transition.authorisation_evidence_hash,
            "root_cause_analysis": root_cause_analysis,
            "specification_update_proposal": specification_update_proposal,
        },
    )

    re_enablement = book.write(
        LedgerEntryType.RE_ENABLEMENT,
        identity_key=new_instance.identity_key.value,
        instance_id=new_instance.instance_id,
        decision_id=suspension.decision_id,
        caused_by=hat.entry_id,
        payload={
            "claim_id": claim_id,
            "predecessor_instance_id": new_instance.predecessor_instance_id,
            "generation": new_instance.generation,
        },
    )

    suspensions.clear(claim_id)
    suspensions.replace_instance(claim_id, new_instance)

    logger.warning(
        "governance.re_enabled claim_id=%s terminal_state=%s authorised_by=%s "
        "new_instance=%s generation=%d",
        claim_id,
        suspension.terminal_state,
        authorised_by,
        new_instance.instance_id,
        new_instance.generation,
    )

    return {
        "claim_id": claim_id,
        "terminal_state": suspension.terminal_state,
        "invariant": suspension.invariant,
        "authorised_by": authorised_by,
        "authority": transition.authority.name,
        "human_authorised_transition_id": hat.entry_id,
        "re_enablement_entry_id": re_enablement.entry_id,
        "new_instance_id": new_instance.instance_id,
        "generation": new_instance.generation,
    }


def rebuild_suspensions_from_ledger(ledger: Any | None = None) -> int:
    """Re-derive open suspensions by scanning the ledger.

    The production answer to in-process state, implemented here so the move to
    Redis is a storage swap rather than a redesign: a TERMINAL with no later
    HUMAN_AUTHORISED_TRANSITION for the same claim is an open suspension.
    """
    book = ledger or default_ledger
    entries = list(book.store.all_entries())

    terminals: dict[str, Any] = {}
    re_enabled: set[str] = set()

    for entry in sorted(entries, key=lambda e: e.sequence):
        claim_id = entry.payload.get("claim_id")
        if not claim_id:
            continue
        if entry.entry_type is LedgerEntryType.TERMINAL:
            terminals[claim_id] = entry
            re_enabled.discard(claim_id)
        elif entry.entry_type is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION:
            re_enabled.add(claim_id)

    restored = 0
    for claim_id, entry in terminals.items():
        if claim_id in re_enabled:
            continue
        suspensions.suspend(
            _Suspension(
                claim_id=claim_id,
                terminal_state=entry.payload.get("terminal_state", ""),
                invariant=entry.payload.get("invariant", ""),
                terminal_entry_id=entry.entry_id,
                decision_id=entry.decision_id or "",
            )
        )
        restored += 1

    logger.info("governance.suspensions_rebuilt count=%d", restored)
    return restored


# ---------------------------------------------------------------------------
# CP-13 -- the LLM call.
#
# The X-Verba spec, S1: "Use it whenever code commits to something it cannot
# take back: an LLM call, a payment, a database write, an outbound message, a
# deployment, a handover to another agent."
#
# An LLM call is therefore a commitment point in its own right, and before this
# refactor it was ungoverned: all five agents narrated during the agent nodes,
# which run BEFORE `governance_gate` in the graph. VSL ran after the model, not
# before it.
#
# This gate closes that. Same construction as `govern_automated_route`: the call
# is passed IN as a callable and invoked once, on the last line of the proceed
# path. Every denial path returns above it, so on a denial the provider is never
# reached -- no request is built, no socket is opened, no key is read.
#
# It lives here, in gates.py, and NOT inside the Gemini provider. A provider
# that gated itself would be a provider that could stop gating itself, and the
# ordering would be invisible at the call site. `agents/base.py` shows the real
# shape: agent -> gate -> provider.
# ---------------------------------------------------------------------------

llm_egress_gates = {
    invariant.name: _adapter.compile_invariant(invariant)
    for invariant in LLM_EGRESS_INVARIANTS
}
invariant_gates.update(llm_egress_gates)


@dataclass
class LLMGovernanceOutcome:
    """What the gate decided about one narration call."""

    action: Literal["proceed", "blocked"]
    decision_id: str
    claim_id: str
    agent: str
    gate: str = "llm-narration"
    llm_called: bool = False
    invariant_violated: str | None = None
    terminal_state: str | None = None
    reason: str | None = None
    ledger_entry_ids: list[str] = field(default_factory=list)
    specification: str = f"{CLAIMS_SPECIFICATION.name} v{CLAIMS_SPECIFICATION.version}"

    @property
    def permitted(self) -> bool:
        return self.action == "proceed"


async def govern_llm_narration(
    candidate: dict[str, Any],
    *,
    perform: Callable[[], T],
    ledger: Any | None = None,
) -> tuple[LLMGovernanceOutcome, T | None]:
    """Gate one LLM call, then make it.

    `candidate` carries what the policy evaluates:
        claim_id, agent, payload_text, personal_identifiers

    `perform` is the provider call. It is invoked exactly once, on the last line
    of the proceed path, and is unreachable from every denial path.

    Two ways this denies, both using existing policy:

    1. **The claim's automation is suspended.** A TerminalState means no
       automated step runs on that claim -- and an LLM call is an automated
       step. Spending money and sending data on a claim whose automation has
       been halted would make "no automated way out" a slogan.
    2. **INV-04, no-customer-data-egress.** Identifiable policyholder data in
       the outbound payload. Never acceptable, so an Invariant.
    """
    book = ledger or default_ledger
    claim_id = str(candidate.get("claim_id") or "unknown")
    agent = str(candidate.get("agent") or "unknown")
    decision_id = str(uuid.uuid4())
    instance = suspensions.instance_for(claim_id)
    identity = instance.identity_key.value
    entries: list[str] = []

    outcome = LLMGovernanceOutcome(
        action="blocked",
        decision_id=decision_id,
        claim_id=claim_id,
        agent=agent,
        ledger_entry_ids=entries,
    )

    # -- (a) MONITOR, for every governed call. `drift_detected` is False: this
    #        gate has no drift signal of its own, and flagging drift we did not
    #        observe would put a false positive into audit check 2.
    monitor = book.write_monitor(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        drift_detected=False,
        extra_payload={
            "claim_id": claim_id,
            "commitment": "llm_narration",
            "agent": agent,
            "specification": outcome.specification,
        },
    )
    entries.append(monitor.entry_id)

    # -- (b) Suspended? Then no automated step runs, including this one.
    existing = suspensions.get(claim_id)
    if existing is not None:
        outcome.terminal_state = existing.terminal_state
        outcome.invariant_violated = existing.invariant
        outcome.reason = (
            "Automation is suspended for this claim; no automated step may run "
            "until a claims authority re-enables it."
        )
        logger.warning(
            "governance.llm_blocked_by_suspension claim_id=%s agent=%s "
            "terminal_state=%s decision_id=%s",
            claim_id,
            agent,
            existing.terminal_state,
            decision_id,
        )
        return outcome, None

    # -- (c) INVARIANTS for this commitment. Non-bypassable.
    for invariant in LLM_EGRESS_INVARIANTS:
        try:
            await llm_egress_gates[invariant.name](candidate)
        except InvariantViolation as exc:
            verification = book.write_verification(
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=monitor.entry_id,
                result=VerificationResult.INSUFFICIENT,  # governance FAILED
                extra_payload={
                    "claim_id": claim_id,
                    "agent": agent,
                    "commitment": "llm_narration",
                    "invariant": exc.invariant_name,
                    "denial_key": DENIAL_KEYS[invariant.name],
                },
            )
            entries.append(verification.entry_id)

            terminal = book.write(
                LedgerEntryType.TERMINAL,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "agent": agent,
                    "terminal_state": exc.terminal_state_name,
                    "invariant": exc.invariant_name,
                    "reason": exc.reason,
                },
            )
            entries.append(terminal.entry_id)

            spec_update = book.write(
                LedgerEntryType.SPECIFICATION_UPDATE,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "specification": outcome.specification,
                    "invariant": exc.invariant_name,
                    "status": "review_required",
                    "detail": (
                        "An Invariant was violated on a governed LLM call. The "
                        "active specification is registered for governance "
                        "review; nothing has been changed automatically."
                    ),
                },
            )
            entries.append(spec_update.entry_id)

            suspensions.suspend(
                _Suspension(
                    claim_id=claim_id,
                    terminal_state=exc.terminal_state_name or "",
                    invariant=exc.invariant_name or invariant.name,
                    terminal_entry_id=terminal.entry_id,
                    decision_id=decision_id,
                )
            )

            outcome.invariant_violated = exc.invariant_name
            outcome.terminal_state = exc.terminal_state_name
            outcome.reason = exc.reason
            logger.warning(
                "governance.llm_invariant_violated claim_id=%s agent=%s "
                "invariant=%s terminal_state=%s decision_id=%s",
                claim_id,
                agent,
                exc.invariant_name,
                exc.terminal_state_name,
                decision_id,
            )
            return outcome, None

    # -- (d) Permitted.
    verification = book.write_verification(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        caused_by=monitor.entry_id,
        result=VerificationResult.SUFFICIENT,
        extra_payload={
            "claim_id": claim_id,
            "agent": agent,
            "commitment": "llm_narration",
            "outcome": "approved",
        },
    )
    entries.append(verification.entry_id)
    outcome.action = "proceed"

    # -- (e) ONLY NOW is the provider reachable. Every denial path returned
    #        above; this line cannot be reached from any of them.
    result = perform()
    outcome.llm_called = True

    logger.info(
        "governance.llm_permitted claim_id=%s agent=%s decision_id=%s",
        claim_id,
        agent,
        decision_id,
    )
    return outcome, result


# ---------------------------------------------------------------------------
# PHASE 5 -- the governed conversational LLM call.
#
# This gate implements the approved baseline architecture exactly as drawn:
#
#     Insurance Agent
#         -> VSL PreNode + Monitor
#         -> Gamma evaluation / threshold
#         -> ALLOW
#         -> Gemini
#         -> Generated Output
#         -> VSL Invariant
#         -> PASS
#         -> downstream business logic / action router
#
#     PreNode DENY   -> NO GEMINI CALL -> human review / deterministic fallback
#     Invariant FAIL -> TerminalState  -> the output never reaches downstream
#
# Two structural properties, both enforced by construction rather than by
# convention, and both asserted by tests that read this function's own source:
#
#   1. `perform` -- the Gemini call -- is referenced EXACTLY ONCE, after the
#      PreNode. Every PreNode denial path returns above that line, so the
#      network call is unreachable from a denial.
#
#   2. `result` is returned EXACTLY ONCE, after the Invariants. Every violation
#      path returns None above that line, so a violating output is unreachable
#      from downstream code. The caller cannot "use it anyway" because it never
#      receives it.
#
# There is no PostNode. The stage after Gemini is an ordinary `vsl_core`
# Invariant, compiled by the same adapter as every other Invariant here, applied
# to the model's output before that output is used.
# ---------------------------------------------------------------------------

generated_output_gates = {
    invariant.name: _adapter.compile_invariant(invariant)
    for invariant in GENERATED_OUTPUT_INVARIANTS
}
invariant_gates.update(generated_output_gates)

extraction_gate = _adapter.compile_pre_node(CONVERSATION_EXTRACTION_CONFIDENCE)

ConversationAction = Literal["proceed", "human_queue", "blocked", "suspended"]


@dataclass
class ConversationGovernanceOutcome:
    """What the gate decided about one governed conversational model call.

    Every field answers a question a reviewer actually asks, and the three that
    matter most are kept apart on purpose:

        pre_node_denied   did the PreNode stop us BEFORE Gemini?
        llm_called        was the network call actually made?
        output_accepted   did the generated output clear the Invariants?

    A caller that reads any one of these as any other has made the mistake this
    whole structure exists to prevent.
    """

    action: ConversationAction
    decision_id: str
    conversation_id: str
    claim_id: str | None = None
    agent: str = "conversation"
    gate: str = "conversation-extraction"

    # -- the PreNode stage, before Gemini
    pre_node: str = CONVERSATION_EXTRACTION_CONFIDENCE.name
    pre_node_denied: bool = False
    gamma_threshold: float | None = CONVERSATION_EXTRACTION_CONFIDENCE.gamma_threshold
    confidence: float | None = None
    confidence_floor: float | None = None
    denial_reason: str | None = None
    fallback: str | None = None

    # -- the Gemini stage
    llm_called: bool = False

    # -- the Invariant stage, after Gemini
    output_accepted: bool = False
    invariant_violated: str | None = None
    terminal_state: str | None = None
    reason: str | None = None

    assurance_level: str | None = CONVERSATION_EXTRACTION_CONFIDENCE.assurance_level.value
    ledger_entry_ids: list[str] = field(default_factory=list)
    specification: str = f"{CLAIMS_SPECIFICATION.name} v{CLAIMS_SPECIFICATION.version}"

    @property
    def permitted(self) -> bool:
        """The model call was permitted AND its output cleared the Invariants.

        Deliberately not "the PreNode passed". An output that violated an
        Invariant was generated but must not be used, and calling that
        "permitted" is how a governance layer ends up rubber-stamping.
        """
        return self.action == "proceed"


async def govern_conversation_extraction(
    candidate: dict[str, Any],
    *,
    perform: Callable[[], T],
    inspect: Callable[[T], dict[str, Any]],
    ledger: Any | None = None,
) -> tuple[ConversationGovernanceOutcome, T | None]:
    """Gate the conversational model call on both sides of it.

    `candidate` carries what the PRE-Gemini stage evaluates:
        conversation_id, claim_id, confidence, source_text,
        payload_text, personal_identifiers

    `perform` makes the Gemini call. Invoked once, after the PreNode.

    `inspect` turns the result into the candidate the POST-Gemini Invariants
    evaluate -- `{"extracted": ..., "assistant_message": ..., "source_text": ...}`.
    It is a separate callable because the gate must not know the shape of a
    provider response, and the Invariants must not be handed anything but the
    facts they judge.

    Returns `(outcome, result)`. `result` is None on every path except a clean
    pass, which is the enforcement property: downstream code cannot act on
    output the Invariants rejected, because it never gets it.
    """
    book = ledger or default_ledger
    conversation_id = str(candidate.get("conversation_id") or "unknown")
    claim_id = str(candidate.get("claim_id") or conversation_id)
    decision_id = str(uuid.uuid4())
    instance = suspensions.instance_for(claim_id)
    identity = instance.identity_key.value
    entries: list[str] = []

    confidence = float(candidate.get("confidence") or 0.0)
    floor = effective_confidence_floor()

    outcome = ConversationGovernanceOutcome(
        action="blocked",
        decision_id=decision_id,
        conversation_id=conversation_id,
        claim_id=candidate.get("claim_id"),
        confidence=confidence,
        confidence_floor=floor,
        ledger_entry_ids=entries,
    )

    # =====================================================================
    # (a) MONITOR. Written by this application, explicitly, for every
    #     governed call -- the ledger records nothing it is not told.
    # =====================================================================
    monitor = book.write_monitor(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        drift_detected=confidence < floor,
        extra_payload={
            "claim_id": claim_id,
            "conversation_id": conversation_id,
            "commitment": "conversation_extraction",
            "confidence": round(confidence, 4),
            "confidence_floor": round(floor, 4),
            "specification": outcome.specification,
        },
    )
    entries.append(monitor.entry_id)

    # =====================================================================
    # (b) Suspended? An LLM call is an automated step.
    # =====================================================================
    existing = suspensions.get(claim_id)
    if existing is not None:
        outcome.action = "suspended"
        outcome.terminal_state = existing.terminal_state
        outcome.invariant_violated = existing.invariant
        outcome.reason = (
            "Automation is suspended for this conversation; no automated step "
            "may run until a claims authority re-enables it."
        )
        logger.warning(
            "governance.conversation_blocked_by_suspension conversation_id=%s "
            "terminal_state=%s decision_id=%s",
            conversation_id,
            existing.terminal_state,
            decision_id,
        )
        return outcome, None

    # =====================================================================
    # (c) VSL PRE-NODE + GAMMA. Soft gate. Denial means no Gemini call.
    # =====================================================================
    denied: AutomationDeniedException | None = None
    try:
        await extraction_gate({"confidence": confidence})
    except AutomationDeniedException as exc:
        denied = exc

    pre_node = book.write(
        LedgerEntryType.PRE_NODE,
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        caused_by=monitor.entry_id,
        payload={
            "claim_id": claim_id,
            "conversation_id": conversation_id,
            "pre_node": CONVERSATION_EXTRACTION_CONFIDENCE.name,
            "denied": denied is not None,
            "assurance_level": CONVERSATION_EXTRACTION_CONFIDENCE.assurance_level.value,
            "gamma_threshold": CONVERSATION_EXTRACTION_CONFIDENCE.gamma_threshold,
            "observed_confidence": round(confidence, 4),
            "threshold_value": round(floor, 4),
            "denial_key": DENIAL_KEYS[CONVERSATION_EXTRACTION_CONFIDENCE.name],
        },
    )
    entries.append(pre_node.entry_id)

    if denied is not None:
        # Governance WORKED -> SUFFICIENT. Writing INSUFFICIENT for an ordinary
        # low-confidence message would demand a SPECIFICATION_UPDATE on routine
        # traffic and the audit would fail permanently.
        verification = book.write_verification(
            identity_key=identity,
            instance_id=instance.instance_id,
            decision_id=decision_id,
            caused_by=pre_node.entry_id,
            result=VerificationResult.SUFFICIENT,
            extra_payload={
                "claim_id": claim_id,
                "conversation_id": conversation_id,
                "commitment": "conversation_extraction",
                "outcome": "llm_call_denied",
                "stage": "pre_node",
                "fallback": CONVERSATION_EXTRACTION_CONFIDENCE.fallback.on_failure,
                "reason": denied.reason,
                "observed_value": round(confidence, 4),
                "threshold_value": round(floor, 4),
            },
        )
        entries.append(verification.entry_id)

        outcome.action = "human_queue"
        outcome.pre_node_denied = True
        outcome.denial_reason = denied.reason
        outcome.fallback = CONVERSATION_EXTRACTION_CONFIDENCE.fallback.on_failure
        logger.info(
            "governance.conversation_pre_node_denied conversation_id=%s "
            "confidence=%.4f floor=%.4f decision_id=%s",
            conversation_id,
            confidence,
            floor,
            decision_id,
        )
        return outcome, None

    # =====================================================================
    # (d) GEMINI. The only reference to `perform` in this function. Every
    #     PreNode denial path returned above, so this is unreachable from one.
    # =====================================================================
    result = perform()
    outcome.llm_called = True

    # =====================================================================
    # (e) VSL INVARIANT, on the GENERATED OUTPUT. Non-bypassable, and it
    #     cannot run any earlier: what it judges did not exist until (d).
    # =====================================================================
    output_candidate = dict(inspect(result))
    output_candidate.setdefault("source_text", candidate.get("source_text"))

    for invariant in GENERATED_OUTPUT_INVARIANTS:
        try:
            await generated_output_gates[invariant.name](output_candidate)
        except InvariantViolation as exc:
            verification = book.write_verification(
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=pre_node.entry_id,
                result=VerificationResult.INSUFFICIENT,  # governance FAILED
                extra_payload={
                    "claim_id": claim_id,
                    "conversation_id": conversation_id,
                    "commitment": "conversation_extraction",
                    "stage": "generated_output_invariant",
                    "outcome": "generated_output_rejected",
                    "invariant": exc.invariant_name,
                    "denial_key": DENIAL_KEYS[invariant.name],
                    "reason": exc.reason,
                    "detail": (
                        "The model produced output that violates an Invariant. "
                        "The output was discarded and never reached the "
                        "conversation state or the customer."
                    ),
                },
            )
            entries.append(verification.entry_id)

            terminal = book.write(
                LedgerEntryType.TERMINAL,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "conversation_id": conversation_id,
                    "terminal_state": exc.terminal_state_name,
                    "invariant": exc.invariant_name,
                    "reason": exc.reason,
                },
            )
            entries.append(terminal.entry_id)

            spec_update = book.write(
                LedgerEntryType.SPECIFICATION_UPDATE,
                identity_key=identity,
                instance_id=instance.instance_id,
                decision_id=decision_id,
                caused_by=verification.entry_id,
                payload={
                    "claim_id": claim_id,
                    "conversation_id": conversation_id,
                    "specification": outcome.specification,
                    "invariant": exc.invariant_name,
                    "status": "review_required",
                    "detail": (
                        "An Invariant was violated by generated output. The "
                        "active specification is registered for governance "
                        "review; nothing has been changed automatically."
                    ),
                },
            )
            entries.append(spec_update.entry_id)

            suspensions.suspend(
                _Suspension(
                    claim_id=claim_id,
                    terminal_state=exc.terminal_state_name or "",
                    invariant=exc.invariant_name or invariant.name,
                    terminal_entry_id=terminal.entry_id,
                    decision_id=decision_id,
                )
            )

            outcome.action = "blocked"
            outcome.invariant_violated = exc.invariant_name
            outcome.terminal_state = exc.terminal_state_name
            outcome.reason = exc.reason
            logger.warning(
                "governance.generated_output_rejected conversation_id=%s "
                "invariant=%s terminal_state=%s decision_id=%s",
                conversation_id,
                exc.invariant_name,
                exc.terminal_state_name,
                decision_id,
            )
            # The generated output is NOT returned. Downstream cannot use what
            # it never receives -- that is the enforcement, not a convention.
            return outcome, None

    # =====================================================================
    # (f) PASS. Only now may the output go downstream.
    # =====================================================================
    verification = book.write_verification(
        identity_key=identity,
        instance_id=instance.instance_id,
        decision_id=decision_id,
        caused_by=pre_node.entry_id,
        result=VerificationResult.SUFFICIENT,
        extra_payload={
            "claim_id": claim_id,
            "conversation_id": conversation_id,
            "commitment": "conversation_extraction",
            "stage": "generated_output_invariant",
            "outcome": "approved",
        },
    )
    entries.append(verification.entry_id)

    outcome.action = "proceed"
    outcome.output_accepted = True
    logger.info(
        "governance.conversation_permitted conversation_id=%s decision_id=%s",
        conversation_id,
        decision_id,
    )
    return outcome, result
