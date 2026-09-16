"""Governance dashboard service — reads the ledger, decides nothing.

This service is strictly read-only. It has no `save`, no `write`, and no route
into `governance.gates` other than the suspension registry it reads. A dashboard
that can change governance state is a second, unaudited enforcement path.

Everything it reports comes from one of three places, and none of them is this
module's opinion:

    the declared specification   ->  governance/policy.py
    what actually happened       ->  the VerbaLedger
    whether it holds up          ->  VerbaLedger.verify_integrity() / .audit()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from vsl_core.ledger import (
    DRIFT_DETECTED_KEY,
    VERIFICATION_RESULT_KEY,
    LedgerEntryType,
    VerificationResult,
)

from app.schemas.governance import (
    AuditStatus,
    DeniedAction,
    GovernanceConfiguration,
    GovernanceDashboard,
    GovernanceEventCounts,
    LedgerEntryView,
    LedgerIntegrity,
    SuspendedClaim,
)
from governance import gates as gates_module
from governance.gates import suspensions
from governance.policy import (
    ALL_INVARIANTS,
    ALL_PRE_NODES,
    ALL_TERMINAL_STATES,
    AUTOMATED_AUTHORITY_LIMIT_NZD,
    AUTOMATION_CONFIDENCE,
    CLAIMS_GOVERNANCE_AUTHORITY,
    CLAIMS_SPECIFICATION,
    DECISION_THRESHOLD,
    OUTPUT_LAYER,
    POC_ASSUMPTION_NOTE,
    effective_confidence_floor,
)

_GAP_CHECK = "no_monitoring_gaps"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class GovernanceService:
    def __init__(self, *, ledger: Any | None = None) -> None:
        self._explicit_ledger = ledger

    @property
    def _ledger(self) -> Any:
        """Resolved through `governance.gates`, deliberately, and not cached.

        The dashboard must read the *same* ledger the gate writes to. Binding a
        module-level import here would create a second reference that could
        diverge from the gate's — and a governance dashboard reporting a
        different ledger from the one enforcing anything is worse than no
        dashboard.
        """
        return self._explicit_ledger or gates_module.default_ledger

    # -- the declared policy ------------------------------------------------

    def configuration(self) -> GovernanceConfiguration:
        return GovernanceConfiguration(
            specification=f"{CLAIMS_SPECIFICATION.name} v{CLAIMS_SPECIFICATION.version}",
            specification_active=CLAIMS_SPECIFICATION.activated_at is not None,
            governance_authority=CLAIMS_GOVERNANCE_AUTHORITY.name,
            pre_nodes=[
                {
                    "name": pre_node.name,
                    "description": pre_node.description,
                    "gamma_threshold": pre_node.gamma_threshold,
                    "assurance_level": pre_node.assurance_level.value,
                    "fallback": pre_node.fallback.on_failure,
                    "kind": "soft_gate",
                    "note": (
                        "A denial reroutes to a person. That is the gate working, "
                        "not failing."
                    ),
                }
                for pre_node in ALL_PRE_NODES
            ],
            invariants=[
                {
                    "name": invariant.name,
                    "description": invariant.description,
                    "assurance_level": invariant.assurance_level.value,
                    "on_violation": (
                        invariant.on_violation.name if invariant.on_violation else None
                    ),
                    "kind": "hard_rule",
                    "note": "Non-bypassable. A violation suspends automation for the claim.",
                }
                for invariant in ALL_INVARIANTS
            ],
            terminal_states=[
                {
                    "name": state.name,
                    "description": state.description,
                    "entry_conditions": list(state.entry_conditions),
                    "requires_human_authorised_transition": (
                        state.requires_human_authorised_transition
                    ),
                }
                for state in ALL_TERMINAL_STATES
            ],
            decision_threshold=DECISION_THRESHOLD,
            effective_confidence_floor=round(effective_confidence_floor(), 4),
            gamma_threshold=AUTOMATION_CONFIDENCE.gamma_threshold,
            automated_authority_limit_nzd=AUTOMATED_AUTHORITY_LIMIT_NZD,
            assurance_level=AUTOMATION_CONFIDENCE.assurance_level.value,
            assurance_basis={
                "f1_pre_commitment": OUTPUT_LAYER.f1_pre_commitment,
                "f2_modification": OUTPUT_LAYER.f2_modification.value,
                "derived_level": OUTPUT_LAYER.derived_level.value,
            },
            threshold_note=POC_ASSUMPTION_NOTE,
        )

    # -- what happened ------------------------------------------------------

    def _entries(self) -> list[Any]:
        return sorted(self._ledger.store.all_entries(), key=lambda e: e.sequence)

    def dashboard(self, *, limit: int = 100) -> GovernanceDashboard:
        entries = self._entries()

        by_type: dict[str, int] = {}
        for entry in entries:
            by_type[entry.entry_type.value] = by_type.get(entry.entry_type.value, 0) + 1

        pre_node_denials = [
            e
            for e in entries
            if e.entry_type is LedgerEntryType.PRE_NODE and e.payload.get("denied")
        ]
        violations = [
            e
            for e in entries
            if e.entry_type is LedgerEntryType.VERIFICATION
            and e.payload.get(VERIFICATION_RESULT_KEY)
            == VerificationResult.INSUFFICIENT.value
        ]
        # CP-14 denials that were NOT incidents: the claim was never eligible
        # for the automated action and the layer above never tried to take it,
        # so the verification result is SUFFICIENT (governance worked) rather
        # than INSUFFICIENT. That is the right ledger record but the wrong thing
        # to leave uncounted -- a dashboard that reports "actions denied: 0"
        # while the automated action on a $42,000 claim was blocked is telling
        # the reader the opposite of what happened.
        automated_action_denials = [
            e
            for e in entries
            if e.entry_type is LedgerEntryType.VERIFICATION
            and e.payload.get("outcome") == "automated_action_denied"
        ]
        terminals = [e for e in entries if e.entry_type is LedgerEntryType.TERMINAL]
        transitions = [
            e
            for e in entries
            if e.entry_type is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
        ]
        resolved = {e.payload.get("claim_id") for e in transitions}
        drift = [
            e
            for e in entries
            if e.entry_type is LedgerEntryType.MONITOR and e.payload.get(DRIFT_DETECTED_KEY)
        ]
        decisions = {e.decision_id for e in entries if e.decision_id}
        claims = {e.payload.get("claim_id") for e in entries if e.payload.get("claim_id")}
        open_terminals = [t for t in terminals if t.payload.get("claim_id") not in resolved]

        counts = GovernanceEventCounts(
            total_entries=len(entries),
            by_type=by_type,
            decisions=len(decisions),
            claims_seen=len(claims),
            drift_flagged=len(drift),
            pre_node_denials=len(pre_node_denials),
            invariant_violations=len(violations),
            terminal_states_entered=len(terminals),
            terminal_states_open=len(open_terminals),
            human_authorised_transitions=len(transitions),
            automated_actions_denied=len(automated_action_denials),
            actions_denied=(
                len(pre_node_denials) + len(violations) + len(automated_action_denials)
            ),
        )

        return GovernanceDashboard(
            configuration=self.configuration(),
            counts=counts,
            integrity=self.integrity(),
            audit=self.audit_status(),
            suspended_claims=self.suspended_claims(),
            denied_actions=self._denied_actions(entries),
            recent_entries=[_view(e) for e in entries[-limit:][::-1]],
        )

    def _denied_actions(self, entries: list[Any]) -> list[DeniedAction]:
        """Every action governance stopped, newest first.

        Both kinds, kept distinguishable: a PreNode denial is a reroute, an
        Invariant violation is a halt. Flattening them into one "blocked" count
        would hide the difference that matters most to a reviewer.
        """
        actions: list[DeniedAction] = []

        for entry in entries:
            if entry.entry_type is LedgerEntryType.PRE_NODE and entry.payload.get("denied"):
                verification = next(
                    (
                        e
                        for e in entries
                        if e.caused_by == entry.entry_id
                        and e.entry_type is LedgerEntryType.VERIFICATION
                    ),
                    None,
                )
                actions.append(
                    DeniedAction(
                        entry_id=entry.entry_id,
                        claim_id=entry.payload.get("claim_id"),
                        decision_id=entry.decision_id,
                        recorded_at=_iso(entry.timestamp),
                        gate=entry.payload.get("pre_node", AUTOMATION_CONFIDENCE.name),
                        gate_kind="pre_node",
                        reason=(verification.payload.get("reason") if verification else None),
                        fallback=(
                            verification.payload.get("fallback") if verification else None
                        ),
                    )
                )
            elif (
                entry.entry_type is LedgerEntryType.VERIFICATION
                and entry.payload.get("outcome") == "automated_action_denied"
            ):
                # The CP-14 refusal, published so the ledger view can answer
                # "why was the automated action denied on this claim?" with the
                # Invariant, the observed value and the limit it exceeded --
                # rather than leaving a reader to infer it from a claim state.
                actions.append(
                    DeniedAction(
                        entry_id=entry.entry_id,
                        claim_id=entry.payload.get("claim_id"),
                        decision_id=entry.decision_id,
                        recorded_at=_iso(entry.timestamp),
                        gate=entry.payload.get("invariant", "unknown"),
                        gate_kind="automated_action",
                        reason=entry.payload.get("reason"),
                        fallback=entry.payload.get("fallback", "ROUTE_TO_HUMAN_QUEUE"),
                        commitment_point=entry.payload.get("commitment"),
                        observed_value=entry.payload.get("observed_value"),
                        threshold_value=entry.payload.get("threshold_value"),
                        detail=entry.payload.get("detail"),
                    )
                )
            elif entry.entry_type is LedgerEntryType.TERMINAL:
                actions.append(
                    DeniedAction(
                        entry_id=entry.entry_id,
                        claim_id=entry.payload.get("claim_id"),
                        decision_id=entry.decision_id,
                        recorded_at=_iso(entry.timestamp),
                        gate=entry.payload.get("invariant", "unknown"),
                        gate_kind="invariant",
                        reason=entry.payload.get("reason"),
                        terminal_state=entry.payload.get("terminal_state"),
                    )
                )

        return actions[::-1]

    def suspended_claims(self) -> list[SuspendedClaim]:
        return [
            SuspendedClaim(
                claim_id=item.claim_id,
                terminal_state=item.terminal_state,
                invariant=item.invariant,
                decision_id=item.decision_id,
                terminal_entry_id=item.terminal_entry_id,
            )
            for item in suspensions.all().values()
        ]

    # -- whether it holds up ------------------------------------------------

    def integrity(self) -> LedgerIntegrity:
        checkpoint = self._ledger.current_checkpoint()
        return LedgerIntegrity(
            verified=self._ledger.verify_integrity(),
            entries=len(self._entries()),
            checkpoint_sequence=checkpoint.sequence if checkpoint else None,
            checkpoint_hash=checkpoint.entry_hash if checkpoint else None,
        )

    def audit_status(self, *, max_monitor_gap_seconds: float | None = None) -> AuditStatus:
        report = self._ledger.audit(max_monitor_gap_seconds=max_monitor_gap_seconds)
        asserted = max_monitor_gap_seconds is not None

        # vsl-core reports a SKIPPED check as passed. Repeating that here would
        # overstate what was actually checked, so it is separated out.
        passed = [
            c for c in report.checks_passed if asserted or c != _GAP_CHECK
        ]
        not_asserted = (
            [] if asserted else [c for c in report.checks_passed if c == _GAP_CHECK]
        )

        certificate = self._ledger.issue_certificate(
            max_monitor_gap_seconds=max_monitor_gap_seconds
        )

        return AuditStatus(
            all_passed=report.all_passed,
            checks_passed=passed,
            checks_failed=list(report.checks_failed),
            checks_not_asserted=not_asserted,
            violations={k: list(v) for k, v in report.violations.items()},
            certificate_issued=certificate is not None
            and self._ledger.verify_integrity(),
        )

    def entries_for_claim(self, claim_id: str) -> list[LedgerEntryView]:
        return [
            _view(e) for e in self._entries() if e.payload.get("claim_id") == claim_id
        ]


def _view(entry: Any) -> LedgerEntryView:
    return LedgerEntryView(
        sequence=entry.sequence,
        entry_id=entry.entry_id,
        entry_type=entry.entry_type.value,
        caused_by=entry.caused_by,
        decision_id=entry.decision_id,
        instance_id=entry.instance_id,
        identity_key=entry.identity_key,
        timestamp=entry.timestamp,
        recorded_at=_iso(entry.timestamp),
        claim_id=entry.payload.get("claim_id"),
        payload=dict(entry.payload),
    )
