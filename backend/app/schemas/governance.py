"""Governance dashboard models.

What the dashboard is *for*: showing that a governance layer exists, that it
runs, and that it sometimes says no — with the ledger entries that prove it.

Two things this deliberately does not do:

1. **It does not summarise a failed audit as a pass.** `audit_all_passed` is the
   framework's own verdict, and `checks_not_asserted` keeps a skipped check from
   being read as a passed one.
2. **It does not present assurance as better than it is.** `assurance_level` is
   whatever VSL derived from the F1/F2 facts, which for this POC is LOW.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GovernanceConfiguration(BaseModel):
    """The active specification, as declared — not as hoped."""

    model_config = ConfigDict(extra="forbid")

    specification: str
    specification_active: bool
    governance_authority: str
    pre_nodes: list[dict[str, Any]] = Field(default_factory=list)
    invariants: list[dict[str, Any]] = Field(default_factory=list)
    terminal_states: list[dict[str, Any]] = Field(default_factory=list)
    decision_threshold: float
    effective_confidence_floor: float
    gamma_threshold: float
    automated_authority_limit_nzd: float
    assurance_level: str
    assurance_basis: dict[str, Any]
    assurance_note: str = (
        "Derived by VSL from the F1/F2 facts, not asserted. LOW means "
        "output-layer control: the gate blocks a bad action, it does not change "
        "how the model decides. HIGH would require a formation-layer change "
        "(loss function, feature space, training), which this POC does not make."
    )
    threshold_note: str = (
        "Every threshold here is a POC proposal awaiting business approval. "
        "None is an insurer-approved rule."
    )


class LedgerEntryView(BaseModel):
    """One ledger entry, as the dashboard shows it."""

    model_config = ConfigDict(extra="forbid")

    sequence: int
    entry_id: str
    entry_type: str
    caused_by: str | None = None
    decision_id: str | None = None
    instance_id: str | None = None
    identity_key: str
    timestamp: float
    recorded_at: str
    claim_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GovernanceEventCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_entries: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    decisions: int = 0
    claims_seen: int = 0
    drift_flagged: int = 0
    pre_node_denials: int = 0
    invariant_violations: int = 0
    terminal_states_entered: int = 0
    terminal_states_open: int = 0
    human_authorised_transitions: int = 0
    automated_actions_denied: int = 0
    """CP-14 denials where the automated claim action was refused and the layer
    above had not attempted it -- an Invariant doing its job on a claim that was
    never eligible. Counted separately from `invariant_violations` because these
    are routine and owe nobody a root-cause analysis, whereas a violation on an
    *attempted* action is an incident that suspends automation."""

    actions_denied: int = 0
    """Every action governance stopped: PreNode denials, Invariant violations on
    attempted actions, and refused automated claim actions."""


class SuspendedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    terminal_state: str
    invariant: str
    decision_id: str
    terminal_entry_id: str
    exit_route: Literal["human_authorised_transition_only"] = (
        "human_authorised_transition_only"
    )


class DeniedAction(BaseModel):
    """One action governance stopped, and what happened instead."""

    model_config = ConfigDict(extra="forbid")

    entry_id: str
    claim_id: str | None = None
    decision_id: str | None = None
    recorded_at: str
    gate: str
    gate_kind: Literal["pre_node", "invariant", "automated_action"]
    """`automated_action` is the CP-14 refusal: the Invariant held and the claim
    action never ran. It is not an `invariant` violation, because nothing
    violated anything -- the rule was enforced before the action existed."""

    reason: str | None = None
    fallback: str | None = None
    terminal_state: str | None = None
    commitment_point: str | None = None
    observed_value: float | None = None
    threshold_value: float | None = None
    detail: str | None = Field(
        default=None,
        description="Plain-language answer to 'why was the automated action denied?'",
    )


class LedgerIntegrity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    entries: int
    checkpoint_sequence: int | None = None
    checkpoint_hash: str | None = None
    note: str = (
        "verify_integrity() re-walks the hash chain and answers 'were these "
        "records edited?'. It does not answer 'is this a governed process?' -- "
        "that is the audit, and they are reported separately on purpose."
    )


class AuditStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    all_passed: bool
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    checks_not_asserted: list[str] = Field(default_factory=list)
    violations: dict[str, list[str]] = Field(default_factory=dict)
    certificate_issued: bool = False
    note: str = (
        "An open terminal state fails check 5 by design: automation was "
        "suspended on a claim and no person has authorised resuming it. A "
        "failing audit here is the ledger telling the truth, not a defect."
    )


class GovernanceDashboard(BaseModel):
    """Everything the governance screen shows, in one response."""

    model_config = ConfigDict(extra="forbid")

    configuration: GovernanceConfiguration
    counts: GovernanceEventCounts
    integrity: LedgerIntegrity
    audit: AuditStatus
    suspended_claims: list[SuspendedClaim] = Field(default_factory=list)
    denied_actions: list[DeniedAction] = Field(default_factory=list)
    recent_entries: list[LedgerEntryView] = Field(default_factory=list)
    boundary_note: str = (
        "Governance decides whether an automated step may proceed. It never "
        "decides a claim. Nothing recorded here approves, declines or settles "
        "anything, and no customer is contacted."
    )
