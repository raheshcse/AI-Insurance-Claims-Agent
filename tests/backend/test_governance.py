"""Phase 4 — X-Verba / VSL governance enforcement.

These tests exist to answer one question that a demonstration cannot answer on
its own: **is this real governance, or does it only look like it?**

So the file is organised around the ways a governance layer is usually faked,
and each section tries to catch that particular fake:

    1.  The constructs are the framework's, not local look-alikes
    2.  The gate runs BEFORE the side effect, and the side effect is unreachable
        from every denial path
    3.  An Invariant cannot be bypassed
    4.  A TerminalState does not clear itself
    5.  The ledger is a hash chain, not a log file
    6.  The audit is the framework's, and it can and does fail
    7.  Gamma and assurance are derived, not asserted
    8.  Governance is wired into the real application, not a side demo

Where the honest answer is a limitation, the test asserts the limitation rather
than hiding it — see `test_suspension_state_does_not_survive_a_restart`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

import vsl_core.constructs as vsl_constructs
from vsl_core.exceptions import AutomationDeniedException, InvariantViolation
from vsl_core.ledger import (
    VERIFICATION_RESULT_KEY,
    LedgerEntryType,
    VerificationResult,
)
from vsl_core.metrics import ROBUST_GAMMA_DEFAULT_THRESHOLD, AssuranceLevel

from governance import gates as gates_module
from governance.gates import (
    govern_automated_route,
    invariant_gates,
    rebuild_suspensions_from_ledger,
    re_enable_automation,
    suspensions,
)
from governance.policy import (
    ALL_INVARIANTS,
    AUTOMATED_AUTHORITY_LIMIT_NZD,
    AUTOMATION_CONFIDENCE,
    CLAIM_AUTOMATION_SUSPENDED,
    CLAIMS_SPECIFICATION,
    DECISION_THRESHOLD,
    OUTPUT_LAYER,
    confidence_gamma,
    effective_confidence_floor,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(candidate, perform):
    """Drive one governed call from synchronous test code."""
    return asyncio.run(govern_automated_route(candidate, perform=perform))


def _types(entries) -> list[str]:
    return [e.entry_type.value for e in entries]


# =========================================================================
# 1. The constructs are the framework's own
# =========================================================================


def test_every_construct_is_an_actual_vsl_core_type():
    """`type(x) is` — a subclass or a duck-type would pass `isinstance`."""
    assert type(AUTOMATION_CONFIDENCE) is vsl_constructs.PreNode
    assert type(CLAIM_AUTOMATION_SUSPENDED) is vsl_constructs.TerminalState
    assert ALL_INVARIANTS
    for invariant in ALL_INVARIANTS:
        assert type(invariant) is vsl_constructs.Invariant

    # And they come from the installed distribution, not from this repository.
    assert "AI_Insurance_Claims_Agent" not in vsl_constructs.__file__


def test_policy_module_imports_only_vsl_core_and_the_standard_library():
    """The enforced import rule from the spec, checked rather than promised.

    A governance policy that can import FastAPI is a governance policy that will
    eventually contain a request handler.
    """
    source = (PROJECT_ROOT / "governance" / "policy.py").read_text(encoding="utf-8")
    tree = compile(source, "policy.py", "exec", flags=0, dont_inherit=True)
    del tree  # compiles; we care about the import statements below

    import ast

    banned_roots = {"fastapi", "pydantic", "app", "agents", "graph", "routing", "llm"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not (roots & banned_roots), f"policy.py imports {roots & banned_roots}"


def test_the_gates_are_compiled_by_the_real_langgraph_adapter():
    from vsl_langgraph import LangGraphAdapter

    assert type(gates_module._adapter) is LangGraphAdapter
    assert set(invariant_gates) == {i.name for i in ALL_INVARIANTS}


# =========================================================================
# 2. Pre-commitment: the side effect is unreachable from a denial
# =========================================================================


def test_the_side_effect_fires_exactly_once_when_every_gate_passes(
    governed_claim, recorder
):
    outcome, result = _run(governed_claim, recorder)

    assert outcome.action == "proceed"
    assert outcome.permitted is True
    assert outcome.side_effect_performed is True
    assert result == "side-effect-performed"
    assert recorder.calls == 1


def test_a_pre_node_denial_never_reaches_the_side_effect(governed_claim, recorder):
    """Confidence below the derived floor. Denied, rerouted, nothing performed."""
    denied = {**governed_claim, "confidence": 0.55}

    outcome, result = _run(denied, recorder)

    assert outcome.action == "human_queue"
    assert outcome.pre_node_denied is True
    assert outcome.fallback == "ROUTE_TO_HUMAN_QUEUE"
    assert outcome.side_effect_performed is False
    assert result is None
    assert recorder.calls == 0


@pytest.mark.parametrize(
    ("field", "value", "expected_invariant"),
    [
        ("policy_in_force_at_loss", False, "policy-in-force"),
        ("peril_covered", False, "policy-in-force"),
        ("estimated_claim_value", AUTOMATED_AUTHORITY_LIMIT_NZD + 1, "automated-authority-limit"),
        ("cover_certainty", "uncertain", "no-auto-approval-under-exclusion"),
        ("exclusions_possibly_engaged", ["EXC-04"], "no-auto-approval-under-exclusion"),
    ],
)
def test_an_invariant_violation_never_reaches_the_side_effect(
    governed_claim, recorder, field, value, expected_invariant
):
    outcome, result = _run({**governed_claim, field: value}, recorder)

    assert outcome.action == "suspended"
    assert outcome.invariant_violated == expected_invariant
    assert outcome.terminal_state == CLAIM_AUTOMATION_SUSPENDED.name
    assert outcome.side_effect_performed is False
    assert result is None
    assert recorder.calls == 0


def test_the_side_effect_is_referenced_once_and_only_after_every_gate():
    """The structural claim, checked structurally.

    Reading a docstring that says "the gate runs first" proves nothing. This
    reads `govern_automated_route` and asserts that the single call to
    `perform()` sits after the last `await` of a gate — so no denial branch,
    which returns earlier, can reach it.
    """
    source = inspect.getsource(govern_automated_route)
    lines = source.splitlines()

    perform_calls = [i for i, line in enumerate(lines) if "perform()" in line]
    assert len(perform_calls) == 1, "the side effect must have exactly one call site"

    gate_awaits = [
        i
        for i, line in enumerate(lines)
        if "await confidence_gate(" in line or "await invariant_gates[" in line
    ]
    assert gate_awaits, "no gate is awaited at all"
    assert perform_calls[0] > max(gate_awaits), "the side effect precedes a gate"

    # And every denial path leaves before it.
    returns_before = [
        i for i, line in enumerate(lines) if line.strip().startswith("return outcome, None")
    ]
    assert returns_before and max(returns_before) < perform_calls[0]


def test_governance_only_ever_makes_the_outcome_more_conservative(governed_claim):
    """Across the whole space, a gate can deny, never grant."""
    permitted = []
    for confidence in (0.10, 0.50, 0.80, 0.8148, 0.90, 0.99):
        for value in (1_000.0, AUTOMATED_AUTHORITY_LIMIT_NZD * 5):
            for certainty in ("clear", "uncertain"):
                suspensions.reset()
                outcome, _ = _run(
                    {
                        **governed_claim,
                        "confidence": confidence,
                        "estimated_claim_value": value,
                        "cover_certainty": certainty,
                    },
                    lambda: "performed",
                )
                permitted.append(outcome.permitted)
                # A denial is never an approval of anything.
                assert outcome.action in {"proceed", "human_queue", "suspended"}

    assert any(permitted), "the gate denies everything -- it is not a gate, it is a wall"
    assert not all(permitted), "the gate permits everything -- it is not a gate"


# =========================================================================
# 3. An Invariant cannot be bypassed
# =========================================================================


def test_an_invariant_gate_raises_rather_than_returning_a_value():
    """There is no return value to ignore. That is the point of a hard rule."""
    gate = invariant_gates["automated-authority-limit"]

    with pytest.raises(InvariantViolation) as excinfo:
        asyncio.run(
            gate(
                {
                    "automated_route_proposed": True,
                    "estimated_claim_value": AUTOMATED_AUTHORITY_LIMIT_NZD + 5_000,
                }
            )
        )

    assert excinfo.value.invariant_name == "automated-authority-limit"
    assert excinfo.value.terminal_state_name == CLAIM_AUTOMATION_SUSPENDED.name
    assert isinstance(excinfo.value, AutomationDeniedException)


def test_a_suspended_claim_stays_suspended_on_retry(governed_claim, recorder):
    """Re-running a suspended claim must not be a way back in."""
    breach = {**governed_claim, "estimated_claim_value": AUTOMATED_AUTHORITY_LIMIT_NZD + 1}

    first, _ = _run(breach, recorder)
    assert first.action == "suspended"

    # Retry with a claim that would otherwise sail through every gate.
    second, result = _run(governed_claim, recorder)

    assert second.action == "suspended"
    assert second.terminal_state == CLAIM_AUTOMATION_SUSPENDED.name
    assert result is None
    assert recorder.calls == 0


def test_the_invariants_judge_the_claim_not_the_routing_decision(governed_claim, recorder):
    """The correction. This test previously asserted the opposite, and was wrong.

    The Invariants used to short-circuit to True whenever routing had not
    proposed the automated route. That made them agree with routing by
    construction: for a NZD 200,000 claim on a lapsed policy the gate returned
    "proceed", which was true of the bookkeeping write it was gating and badly
    misleading about the automated action.

    They now answer the question they are named for -- may THIS claim be handled
    automatically? -- whatever routing decided. The automated action is denied,
    the side effect does not run, and the claim goes to a person.
    """
    not_attempted = {
        **governed_claim,
        "automated_route_proposed": False,  # routing already said "a person"
        "estimated_claim_value": AUTOMATED_AUTHORITY_LIMIT_NZD * 10,
        "policy_in_force_at_loss": False,
        "cover_certainty": "no_cover_basis",
    }

    outcome, result = _run(not_attempted, recorder)

    assert outcome.action == "action_denied"
    assert outcome.automated_action_allowed is False
    assert outcome.invariant_violated is not None
    assert result is None and recorder.calls == 0

    # Routing and governance agree, so nothing is stuck: no TerminalState and no
    # human re-enablement is owed. That distinction is the point.
    assert outcome.terminal_state is None
    assert outcome.automated_action_attempted is False
    assert suspensions.get(governed_claim["claim_id"]) is None


def test_the_same_violation_is_an_incident_when_the_action_was_attempted(
    governed_claim, recorder
):
    """Same facts, but the layer above tried to automate. Now it IS an incident."""
    attempted = {
        **governed_claim,
        "automated_route_proposed": True,  # a bug, or a bad deploy
        "estimated_claim_value": AUTOMATED_AUTHORITY_LIMIT_NZD * 10,
    }

    outcome, result = _run(attempted, recorder)

    assert outcome.action == "suspended"
    assert outcome.automated_action_allowed is False
    assert outcome.terminal_state == CLAIM_AUTOMATION_SUSPENDED.name
    assert outcome.automated_action_attempted is True
    assert result is None and recorder.calls == 0
    assert suspensions.get(governed_claim["claim_id"]) is not None


# =========================================================================
# 4. A TerminalState does not clear itself
# =========================================================================


def test_the_terminal_state_requires_a_human_authorised_transition():
    assert CLAIM_AUTOMATION_SUSPENDED.requires_human_authorised_transition is True


def test_nothing_recovers_from_a_terminal_state_automatically(governed_claim, recorder):
    breach = {**governed_claim, "policy_in_force_at_loss": False}
    _run(breach, recorder)

    for _ in range(5):
        outcome, _ = _run(governed_claim, recorder)
        assert outcome.action == "suspended"

    assert recorder.calls == 0
    assert suspensions.get(governed_claim["claim_id"]) is not None


def test_re_enablement_requires_real_evidence(governed_claim, recorder, isolated_ledger):
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    with pytest.raises(ValueError):
        re_enable_automation(
            governed_claim["claim_id"],
            authorised_by="A. Reviewer",
            root_cause_analysis="   ",
            specification_update_proposal="something",
            ledger=isolated_ledger,
        )

    # Still suspended: a refused request changes nothing.
    assert suspensions.get(governed_claim["claim_id"]) is not None


def test_re_enablement_lets_automation_run_again_and_is_recorded(
    governed_claim, recorder, isolated_ledger, entries
):
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)
    terminal = next(e for e in entries() if e.entry_type is LedgerEntryType.TERMINAL)

    result = re_enable_automation(
        governed_claim["claim_id"],
        authorised_by="A. Reviewer",
        root_cause_analysis="The policy record had a stale expiry date.",
        specification_update_proposal="Validate policy expiry at ingest.",
        ledger=isolated_ledger,
    )

    hat = next(
        e
        for e in entries()
        if e.entry_type is LedgerEntryType.HUMAN_AUTHORISED_TRANSITION
    )
    # Caused by the TERMINAL it resolves -- this is what audit check 5 matches on.
    assert hat.caused_by == terminal.entry_id
    assert result["generation"] >= 1
    assert suspensions.get(governed_claim["claim_id"]) is None

    outcome, _ = _run(governed_claim, recorder)
    assert outcome.action == "proceed"
    assert recorder.calls == 1


def test_re_enabling_a_claim_that_is_not_suspended_is_refused(isolated_ledger):
    with pytest.raises(ValueError):
        re_enable_automation(
            "CLM-NOT-SUSPENDED",
            authorised_by="A. Reviewer",
            root_cause_analysis="n/a",
            specification_update_proposal="n/a",
            ledger=isolated_ledger,
        )


def test_suspension_state_does_not_survive_a_restart_and_is_rebuilt_from_the_ledger(
    governed_claim, recorder, isolated_ledger
):
    """The stated limitation, asserted rather than glossed over.

    Suspensions live in process memory. A restart loses them — that is true and
    this test says so. What stops it from being a hole is that the state is
    re-derivable from the ledger, and this exercises the re-derivation.
    """
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)
    assert suspensions.get(governed_claim["claim_id"]) is not None

    suspensions.reset()  # a restart
    assert suspensions.get(governed_claim["claim_id"]) is None

    # The claim would now wrongly proceed -- so the rebuild is not optional.
    restored = rebuild_suspensions_from_ledger(isolated_ledger)

    assert restored == 1
    assert suspensions.get(governed_claim["claim_id"]) is not None

    outcome, _ = _run(governed_claim, recorder)
    assert outcome.action == "suspended"


# =========================================================================
# 5. The ledger is a hash chain, not a log file
# =========================================================================


def test_every_governed_call_writes_a_monitor_entry(governed_claim, recorder, entries):
    _run(governed_claim, recorder)

    monitors = [e for e in entries() if e.entry_type is LedgerEntryType.MONITOR]
    assert len(monitors) == 1
    assert monitors[0].payload["claim_id"] == governed_claim["claim_id"]
    # Continuous evidence, not only-on-incident evidence.
    _run(governed_claim, recorder)
    assert len([e for e in entries() if e.entry_type is LedgerEntryType.MONITOR]) == 2


def test_a_pass_writes_monitor_pre_node_and_a_sufficient_verification(
    governed_claim, recorder, entries
):
    _run(governed_claim, recorder)

    assert _types(entries()) == ["MONITOR", "PRE_NODE", "VERIFICATION"]
    verification = entries()[-1]
    assert verification.payload[VERIFICATION_RESULT_KEY] == VerificationResult.SUFFICIENT.value


def test_a_pre_node_denial_is_recorded_as_sufficient_because_governance_worked(
    governed_claim, recorder, entries
):
    """The SUFFICIENT/INSUFFICIENT distinction, which is easy to get backwards.

    A PreNode denial means the gate did its job. Recording it as INSUFFICIENT
    would make audit check 4 demand a SPECIFICATION_UPDATE for every ordinary
    low-confidence claim, and the audit would then fail permanently on routine
    traffic — which would train everyone to ignore it.
    """
    _run({**governed_claim, "confidence": 0.2}, recorder)

    verification = next(e for e in entries() if e.entry_type is LedgerEntryType.VERIFICATION)
    assert verification.payload[VERIFICATION_RESULT_KEY] == VerificationResult.SUFFICIENT.value
    assert verification.payload["outcome"] == "routed_to_human_queue"

    # And no specification update was needed, because nothing failed.
    assert not [e for e in entries() if e.entry_type is LedgerEntryType.SPECIFICATION_UPDATE]


def test_an_invariant_violation_is_recorded_as_insufficient_with_a_spec_update(
    governed_claim, recorder, entries
):
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    assert _types(entries()) == [
        "MONITOR",
        "PRE_NODE",
        "VERIFICATION",
        "TERMINAL",
        "SPECIFICATION_UPDATE",
    ]
    verification = entries()[2]
    assert verification.payload[VERIFICATION_RESULT_KEY] == VerificationResult.INSUFFICIENT.value

    spec_update = entries()[4]
    assert spec_update.caused_by == verification.entry_id
    assert spec_update.payload["status"] == "review_required"


def test_caused_by_is_set_on_every_entry_except_the_first(
    governed_claim, recorder, entries
):
    """Without `caused_by`, `audit()` falls back to a timestamp heuristic that
    can match an unrelated PRE_NODE under concurrency and report a false pass.
    A claims queue is exactly that concurrency."""
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    written = entries()
    ids = {e.entry_id for e in written}
    assert written[0].entry_type is LedgerEntryType.MONITOR
    for entry in written[1:]:
        assert entry.caused_by, f"{entry.entry_type} has no caused_by"
        assert entry.caused_by in ids


def test_the_ledger_is_hash_chained_and_detects_tampering(
    governed_claim, recorder, isolated_ledger, tmp_path
):
    _run(governed_claim, recorder)
    _run({**governed_claim, "claim_id": "CLM-GOV-0002", "confidence": 0.2}, recorder)

    assert isolated_ledger.verify_integrity() is True

    # Rewrite history: make the recorded denial read as though it never happened.
    path = tmp_path / "ledger.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    index, record = next(
        (i, json.loads(line))
        for i, line in enumerate(lines)
        if json.loads(line)["payload"].get("denied") is True
    )
    record["payload"]["denied"] = False
    lines[index] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    from governance.ledger import build_ledger

    assert build_ledger(path).verify_integrity() is False


# =========================================================================
# 6. The audit is the framework's, and it can fail
# =========================================================================


def test_a_clean_run_passes_every_audit_check(governed_claim, recorder, isolated_ledger):
    _run(governed_claim, recorder)

    report = isolated_ledger.audit()
    assert report.all_passed, report.violations
    assert isolated_ledger.verify_integrity() is True


def test_an_open_terminal_state_fails_the_audit_by_design(
    governed_claim, recorder, isolated_ledger
):
    """A failing audit here is the ledger telling the truth, not misbehaving."""
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    report = isolated_ledger.audit()

    assert "terminal_has_human_authorised_transition" in report.checks_failed
    assert report.all_passed is False
    # Integrity is untouched: the records are intact, the process is unfinished.
    assert isolated_ledger.verify_integrity() is True


def test_the_audit_passes_again_once_a_person_authorises_the_transition(
    governed_claim, recorder, isolated_ledger
):
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)
    assert isolated_ledger.audit().all_passed is False

    re_enable_automation(
        governed_claim["claim_id"],
        authorised_by="A. Reviewer",
        root_cause_analysis="The policy record had a stale expiry date.",
        specification_update_proposal="Validate policy expiry at ingest.",
        ledger=isolated_ledger,
    )

    report = isolated_ledger.audit()
    assert report.all_passed, report.violations


def test_no_certificate_is_issued_for_a_failed_audit(
    governed_claim, recorder, isolated_ledger
):
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)
    assert isolated_ledger.issue_certificate() is None

    re_enable_automation(
        governed_claim["claim_id"],
        authorised_by="A. Reviewer",
        root_cause_analysis="The policy record had a stale expiry date.",
        specification_update_proposal="Validate policy expiry at ingest.",
        ledger=isolated_ledger,
    )
    assert isolated_ledger.issue_certificate() is not None


def test_integrity_and_audit_answer_different_questions(
    governed_claim, recorder, isolated_ledger
):
    """Both, always. Either one alone can be true while the other is false."""
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    assert isolated_ledger.verify_integrity() is True  # records intact
    assert isolated_ledger.audit().all_passed is False  # process unfinished


# -- the CLI ---------------------------------------------------------------


def test_audit_cli_exits_non_zero_on_an_open_terminal_state(
    governed_claim, recorder, tmp_path, capsys
):
    from governance.audit_cli import EXIT_FAILED, EXIT_OK, main

    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)
    ledger_path = str(tmp_path / "ledger.jsonl")

    assert main(["verify", "--ledger", ledger_path]) == EXIT_OK
    assert main(["audit", "--ledger", ledger_path]) == EXIT_FAILED
    assert main(["certify", "--ledger", ledger_path]) == EXIT_FAILED

    output = capsys.readouterr().out
    assert "terminal_has_human_authorised_transition" in output
    assert "CERTIFICATION REFUSED" in output


def test_audit_cli_reports_check_one_as_not_asserted_without_a_gap_threshold(
    governed_claim, recorder, tmp_path, capsys
):
    """vsl-core *skips* check 1 when no threshold is given and reports it as
    passed. Repeating that as 'passed' would overstate what was checked."""
    from governance.audit_cli import main

    _run(governed_claim, recorder)
    main(["audit", "--ledger", str(tmp_path / "ledger.jsonl")])

    output = capsys.readouterr().out
    assert "N/A    no_monitoring_gaps" in output

    main(["audit", "--ledger", str(tmp_path / "ledger.jsonl"), "--max-monitor-gap-seconds", "86400"])
    assert "PASS   no_monitoring_gaps" in capsys.readouterr().out


def test_audit_cli_refuses_to_certify_an_empty_ledger(tmp_path):
    from governance.audit_cli import EXIT_UNUSABLE, main

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    assert main(["certify", "--ledger", str(empty)]) == EXIT_UNUSABLE


# =========================================================================
# 7. Gamma and assurance are derived, not asserted
# =========================================================================


def test_gamma_is_measured_against_the_decision_boundary_not_one_half():
    """The silent failure this guards against.

    Using the raw odds p/(1-p) assumes a boundary of 0.5. At our boundary of
    0.80 that would make every claim look far more confident than it is, and the
    PreNode would wave through work it should stop -- with no error anywhere.
    """
    assert confidence_gamma(DECISION_THRESHOLD).gamma_hat == pytest.approx(1.0)

    naive = 0.80 / (1 - 0.80)
    assert confidence_gamma(0.80).gamma_hat != pytest.approx(naive)

    assert confidence_gamma(0.95).gamma_hat > 1.0
    assert confidence_gamma(0.50).gamma_hat < 1.0


def test_the_confidence_floor_is_derived_from_gamma_and_the_boundary():
    floor = effective_confidence_floor()

    assert floor == pytest.approx(0.8148, abs=5e-4)
    assert floor > DECISION_THRESHOLD  # robustness costs something, as it should
    assert confidence_gamma(floor).gamma_hat == pytest.approx(
        ROBUST_GAMMA_DEFAULT_THRESHOLD, rel=1e-6
    )


def test_assurance_is_derived_from_f1_f2_and_is_honestly_low():
    """LOW is the correct answer for an output-layer gate, and is reported as such.

    HIGH requires a formation-layer change -- loss function, feature space,
    training. This POC does not make one, so claiming anything above LOW would
    be a fabrication.
    """
    assert OUTPUT_LAYER.derived_level is AssuranceLevel.LOW
    assert AUTOMATION_CONFIDENCE.assurance_level is AssuranceLevel.LOW
    assert OUTPUT_LAYER.f1_pre_commitment is True


def test_the_specification_is_active_and_carries_its_authority():
    assert CLAIMS_SPECIFICATION.pre_nodes
    assert CLAIMS_SPECIFICATION.invariants
    assert CLAIMS_SPECIFICATION.terminal_states
    assert CLAIMS_SPECIFICATION.approved_by is not None


# =========================================================================
# 8. Wired into the real application
# =========================================================================


def test_the_workflow_graph_contains_the_governance_gate(run_workflow, submitted_claim):
    result = run_workflow(submitted_claim)

    assert [e["agent"] for e in result["trace"]][-1] == "governance_gate"
    gate = result["governance_gate"]
    assert gate["gate"] == AUTOMATION_CONFIDENCE.name
    assert gate["outcome"] in {"authorised", "denied"}
    assert gate["assurance_level"] == AssuranceLevel.LOW.value


def test_the_analyze_endpoint_publishes_the_governance_decision(
    review_client, valid_fnol
):
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    governance = body["governance"]
    assert governance["specification"].startswith("home-storm-claims-automation")
    assert governance["action"] in {"proceed", "human_queue", "suspended"}
    assert governance["decision_id"]
    assert governance["ledger_entry_ids"]
    assert governance["assurance_level"] == AssuranceLevel.LOW.value
    # Still a recommendation. Governance does not turn one into a decision.
    assert body["is_recommendation_only"] is True
    assert body["action_taken"] == "none"


def test_a_governance_denial_sends_the_claim_to_a_person(review_client, valid_fnol):
    """The end-to-end property: a denied automated route lands on the queue."""
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    # Raise the boundary so the claim cannot clear the derived floor.
    import governance.policy as policy_module

    original = policy_module.DECISION_THRESHOLD
    policy_module.DECISION_THRESHOLD = 0.999
    try:
        body = client.post(f"/api/claims/{claim_id}/analyze").json()
    finally:
        policy_module.DECISION_THRESHOLD = original

    assert body["governance"]["action"] != "proceed"
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert queue.get(claim_id) is not None


def test_the_re_enablement_endpoint_is_the_only_way_out(review_client, valid_fnol):
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]
    client.post(f"/api/claims/{claim_id}/analyze")

    # Not suspended -> refused.
    response = client.post(
        f"/api/review-queue/{claim_id}/re-enable-automation",
        json={
            "authorised_by": "A. Reviewer",
            "root_cause_analysis": "A sufficiently long root cause analysis string.",
            "specification_update_proposal": "A sufficiently long proposal string.",
        },
    )
    assert response.status_code == 409


# =========================================================================
# 9. The governance dashboard
# =========================================================================


@pytest.fixture
def governance_client(review_client):
    """The dashboard mounted on the same application the gate writes from."""
    client, claims, queue = review_client
    return client, claims, queue


def test_the_dashboard_reports_the_declared_specification(governance_client):
    client, _, _ = governance_client
    body = client.get("/api/governance/configuration").json()

    assert body["specification"].startswith("home-storm-claims-automation")
    assert body["specification_active"] is True
    # Phase 5 added PN-02 for the conversational model call. Asserted against
    # ALL_PRE_NODES rather than a hard-coded list so the dashboard is checked
    # for completeness -- a PreNode the specification declares but the dashboard
    # omits is a governance construct nobody can see.
    from governance.policy import ALL_PRE_NODES

    assert {p["name"] for p in body["pre_nodes"]} == {p.name for p in ALL_PRE_NODES}
    assert AUTOMATION_CONFIDENCE.name in {p["name"] for p in body["pre_nodes"]}
    assert {i["name"] for i in body["invariants"]} == {i.name for i in ALL_INVARIANTS}
    assert body["terminal_states"][0]["requires_human_authorised_transition"] is True

    # Assurance is reported as derived, and honestly.
    assert body["assurance_level"] == AssuranceLevel.LOW.value
    assert body["assurance_basis"]["derived_level"] == AssuranceLevel.LOW.value
    assert body["effective_confidence_floor"] == pytest.approx(0.8148, abs=5e-4)


def test_the_dashboard_reports_real_events_not_a_placeholder(
    governance_client, valid_fnol
):
    client, _, _ = governance_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]
    client.post(f"/api/claims/{claim_id}/analyze")

    body = client.get("/api/governance").json()

    assert body["counts"]["total_entries"] > 0
    assert body["counts"]["claims_seen"] >= 1
    assert body["integrity"]["verified"] is True
    assert body["recent_entries"]
    assert any(e["claim_id"] == claim_id for e in body["recent_entries"])


def test_the_dashboard_shows_denied_actions_and_the_open_terminal_state(
    governance_client, governed_claim, recorder
):
    client, _, _ = governance_client
    _run({**governed_claim, "confidence": 0.3}, recorder)
    _run({**governed_claim, "claim_id": "CLM-GOV-9002", "policy_in_force_at_loss": False}, recorder)

    body = client.get("/api/governance").json()

    kinds = {a["gate_kind"] for a in body["denied_actions"]}
    assert kinds == {"pre_node", "invariant"}
    assert body["counts"]["actions_denied"] == 2
    assert body["counts"]["terminal_states_open"] == 1
    assert body["suspended_claims"][0]["claim_id"] == "CLM-GOV-9002"
    assert body["suspended_claims"][0]["exit_route"] == "human_authorised_transition_only"

    # The audit failure is surfaced, not smoothed over.
    assert body["audit"]["all_passed"] is False
    assert "terminal_has_human_authorised_transition" in body["audit"]["checks_failed"]
    assert body["audit"]["certificate_issued"] is False


def test_the_dashboard_never_reports_a_skipped_check_as_passed(governance_client, governed_claim, recorder):
    client, _, _ = governance_client
    _run(governed_claim, recorder)

    body = client.get("/api/governance/audit").json()
    assert body["checks_not_asserted"] == ["no_monitoring_gaps"]
    assert "no_monitoring_gaps" not in body["checks_passed"]

    asserted = client.get(
        "/api/governance/audit", params={"max_monitor_gap_seconds": 86400}
    ).json()
    assert "no_monitoring_gaps" in asserted["checks_passed"]
    assert asserted["checks_not_asserted"] == []


def test_one_claims_governance_trail_is_readable_in_causal_order(
    governance_client, governed_claim, recorder
):
    client, _, _ = governance_client
    _run({**governed_claim, "policy_in_force_at_loss": False}, recorder)

    trail = client.get(f"/api/governance/ledger/{governed_claim['claim_id']}").json()

    assert [e["entry_type"] for e in trail] == [
        "MONITOR",
        "PRE_NODE",
        "VERIFICATION",
        "TERMINAL",
        "SPECIFICATION_UPDATE",
    ]
    ids = {e["entry_id"] for e in trail}
    for entry in trail[1:]:
        assert entry["caused_by"] in ids


def test_the_dashboard_is_read_only(governance_client):
    """No endpoint under /api/governance changes governance state."""
    client, _, _ = governance_client
    spec = client.get("/openapi.json").json()

    for path, operations in spec["paths"].items():
        if path.startswith("/api/governance"):
            assert set(operations) <= {"get"}, f"{path} exposes {set(operations)}"


# =========================================================================
# 10. The adapter obeys the framework's own contract
# =========================================================================


def test_the_langgraph_adapter_passes_the_frameworks_conformance_suite():
    """vsl-core's mechanical adapter check, run rather than cited.

    This is the strongest available evidence that the integration is genuine and
    not a shim: the framework's own suite, run against the adapter compiling our
    gates. It is a *different* claim from `audit()` -- adapter contract, not
    ledger content -- and the two are never reported as one.
    """
    from vsl_core.conformance.suite import run_conformance_suite
    from vsl_langgraph import LangGraphAdapter

    assert run_conformance_suite(LangGraphAdapter()) == []


def test_no_static_scan_tool_is_claimed_that_does_not_exist():
    """`x-verba scan` does not exist, and nothing here pretends it does.

    Neither distribution installs a console entry point or a static-analysis
    module. The CLI exposes `conformance` -- the real mechanical check -- and the
    report says plainly that no static-Γ scan was run, rather than printing a
    figure nobody computed.
    """
    import importlib.util
    import shutil

    assert shutil.which("x-verba") is None
    assert importlib.util.find_spec("vsl_core.scan") is None

    from governance.audit_cli import COMMANDS

    assert "conformance" in COMMANDS
    assert "scan" not in COMMANDS


def test_the_conformance_command_reports_the_real_result(tmp_path, capsys, governed_claim, recorder):
    from governance.audit_cli import EXIT_OK, main

    _run(governed_claim, recorder)
    assert main(["conformance", "--ledger", str(tmp_path / "ledger.jsonl")]) == EXIT_OK

    output = capsys.readouterr().out
    assert "CONFORMANT" in output
    assert "Not the ledger, not Gamma" in output


# =========================================================================
# 11. Defence in depth: what the Invariants are actually for
# =========================================================================


def test_in_normal_operation_the_invariants_never_fire(review_client, valid_fnol):
    """And that is the expected result, not a weak test.

    The three Invariants mirror Phase 3 escalation rules E-04, E-05 and E-06. So
    whenever the routing layer is working, a claim it sends down the automated
    path has already satisfied all three, and the Invariants pass. They are not
    there to catch a new class of claim -- they are there to catch the routing
    layer being wrong, which is the next test.
    """
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["routing"]["outcome"] == "AUTOMATED_PATH_RECOMMENDED"
    assert body["governance"]["action"] == "proceed"
    assert body["governance"]["invariant_violated"] is None


def test_an_invariant_catches_the_routing_layer_being_wrong(
    review_client, valid_fnol, isolated_ledger
):
    """The case the Invariants exist for, demonstrated rather than argued.

    A routing bug recommends the automated path for a claim far above the
    automated authority limit. Phase 3's business rule has failed. The Invariant
    at the commitment point does not: the write never happens, automation is
    suspended, and the ledger records that governance -- not routing -- stopped
    it.

    This is the whole argument for putting the gate at the side effect rather
    than trusting the layer above it.
    """
    client, claims, queue = review_client
    fnol = {
        "customer": valid_fnol["customer"],
        "property": valid_fnol["property"],
        "damage": {
            **valid_fnol["damage"],
            "damaged_items": [
                {**valid_fnol["damage"]["damaged_items"][0], "estimated_value": 240_000}
            ],
            "customer_estimated_value": 240_000,
        },
    }
    claim_id = client.post("/api/claims", json=fnol).json()["claim_id"]

    # Break the routing layer: claim the automated path for everything.
    from routing.contracts import RoutingOutcome
    import app.services.review_service as review_module

    original = review_module._governance_candidate

    def broken_candidate(claim, intelligence):
        candidate = original(claim, intelligence)
        candidate["automated_route_proposed"] = True  # the bug
        return candidate

    review_module._governance_candidate = broken_candidate
    try:
        body = client.post(f"/api/claims/{claim_id}/analyze").json()
    finally:
        review_module._governance_candidate = original

    governance = body["governance"]
    assert governance["action"] == "suspended"
    assert governance["invariant_violated"] == "automated-authority-limit"
    assert governance["terminal_state"] == "claim-automation-suspended"
    assert governance["side_effect_performed"] is False

    # The claim is with a person, and automation is off until someone lifts it.
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert claims.get(claim_id)["internal_status"] == "automation_suspended"
    assert queue.get(claim_id)["automation_suspended"] is True

    # And the ledger records that governance stopped it, not that routing did.
    report = isolated_ledger.audit()
    assert "terminal_has_human_authorised_transition" in report.checks_failed


def test_a_reviewer_can_lift_the_suspension_through_the_api(
    review_client, valid_fnol, isolated_ledger
):
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    import app.services.review_service as review_module

    original = review_module._governance_candidate
    review_module._governance_candidate = lambda claim, intel: {
        **original(claim, intel),
        "automated_route_proposed": True,
        "policy_in_force_at_loss": False,
    }
    try:
        client.post(f"/api/claims/{claim_id}/analyze")
    finally:
        review_module._governance_candidate = original

    detail = client.get(f"/api/review-queue/{claim_id}").json()
    assert detail["automation_suspended"] is True

    response = client.post(
        f"/api/review-queue/{claim_id}/re-enable-automation",
        json={
            "authorised_by": "A. Reviewer",
            "root_cause_analysis": "The policy record carried a stale expiry date.",
            "specification_update_proposal": "Validate policy expiry at ingest.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision_source"] == "human"
    assert body["human_authorised_transition_id"]

    # The claim is not decided by this -- only automation is permitted again.
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert isolated_ledger.audit().all_passed

    after = client.get(f"/api/review-queue/{claim_id}").json()
    assert after["automation_suspended"] is False


def test_evidence_is_required_by_the_api_too(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    response = client.post(
        f"/api/review-queue/{claim_id}/re-enable-automation",
        json={"authorised_by": "A. Reviewer", "root_cause_analysis": "x",
              "specification_update_proposal": "y"},
    )
    assert response.status_code == 422


# =========================================================================
# 12. CP-14 — INV-02 attached to the automated-action commitment point
#
# The correction. Governance must answer "may the system handle this claim
# without a person?" on the claim's own facts -- not agree with routing by
# construction and then report "permitted" about a bookkeeping write.
# =========================================================================


def _fnol(value: float, valid_fnol: dict) -> dict:
    """The same claim at a different value. Nothing else changes."""
    item = {**valid_fnol["damage"]["damaged_items"][0], "estimated_value": value}
    return {
        "customer": valid_fnol["customer"],
        "property": valid_fnol["property"],
        "damage": {
            **valid_fnol["damage"],
            "damaged_items": [item],
            "customer_estimated_value": value,
        },
    }


def test_a_42000_claim_is_denied_the_automated_action_by_inv_02(
    review_client, valid_fnol, isolated_ledger
):
    """The scenario in the brief, end to end through the real application.

    NZD 42,000 against a NZD 20,000 automated authority limit. Business rules
    route it to a person AND governance denies the automated action. Both facts
    are recorded; neither substitutes for the other.
    """
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=_fnol(42_000, valid_fnol)).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()
    governance = body["governance"]

    # Business rules: eligibility.
    assert body["routing"]["outcome"] == "HUMAN_REVIEW_REQUIRED"

    # Governance: permission. A separate answer, and it is DENIED.
    assert governance["action"] == "action_denied"
    assert governance["automated_action_allowed"] is False
    assert governance["permitted"] is False
    assert governance["invariant_violated"] == "automated-authority-limit"
    assert governance["observed_value"] == 42_000
    assert governance["threshold_value"] == 20_000

    # The automated action did not run.
    assert governance["side_effect_performed"] is False
    assert claims.get(claim_id)["claim_state"] == "Human Review"
    assert queue.get(claim_id) is not None

    # Routing and governance agree, so nothing is stuck.
    assert governance["terminal_state"] is None
    assert governance["automated_action_attempted"] is False


def test_a_claim_below_the_limit_is_permitted_the_automated_action(
    review_client, valid_fnol
):
    client, claims, queue = review_client
    claim_id = client.post("/api/claims", json=_fnol(3_200, valid_fnol)).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()
    governance = body["governance"]

    assert body["routing"]["outcome"] == "AUTOMATED_PATH_RECOMMENDED"
    assert governance["automated_action_allowed"] is True
    assert governance["side_effect_performed"] is True
    assert governance["invariant_violated"] is None
    assert claims.get(claim_id)["claim_state"] == "Assessment"
    assert queue.get(claim_id) is None


def test_the_ledger_answers_why_the_automated_action_was_denied(
    review_client, valid_fnol, isolated_ledger, entries
):
    """"Why was the automated action denied?" must be answerable from evidence
    alone — the value, the threshold, the policy and the causal chain."""
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=_fnol(42_000, valid_fnol)).json()["claim_id"]
    client.post(f"/api/claims/{claim_id}/analyze")

    written = [e for e in entries() if e.payload.get("claim_id") == claim_id]
    verification = next(
        e for e in written
        if e.entry_type is LedgerEntryType.VERIFICATION
        and e.payload.get("commitment") == "automated_claim_action"
    )

    assert verification.payload["invariant"] == "automated-authority-limit"
    assert verification.payload["observed_value"] == 42_000
    assert verification.payload["threshold_value"] == 20_000
    assert verification.payload["outcome"] == "automated_action_denied"
    assert verification.payload["automated_action_attempted"] is False
    assert verification.payload["assurance_level"]
    assert verification.caused_by, "caused_by must point at the PRE_NODE"

    # Routine denial, so no audit debt: governance worked.
    assert verification.payload[VERIFICATION_RESULT_KEY] == VerificationResult.SUFFICIENT.value
    assert isolated_ledger.audit().all_passed
    assert isolated_ledger.verify_integrity() is True


def test_an_llm_permission_is_not_an_action_permission(review_client, valid_fnol):
    """The distinction the brief calls extremely important.

    On a NZD 42,000 claim every LLM call is permitted and every one executes —
    and the automated claim action is denied. Two gates, two commitments, two
    answers. Reading the first as the second is the mistake.
    """
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=_fnol(42_000, valid_fnol)).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["llm_governance"]["permitted"] == 5
    assert body["llm_governance"]["blocked"] == 0
    for result in body["agent_results"].values():
        assert result["narration_governance"]["llm_called"] is True

    assert body["governance"]["automated_action_allowed"] is False
    assert body["governance"]["invariant_violated"] == "automated-authority-limit"


def test_governance_never_reports_permitted_for_a_denied_automated_action(
    review_client, valid_fnol
):
    """A regression guard on the exact wording that was misleading.

    `permitted` and `automated_action_allowed` must agree, and both must be
    False whenever an Invariant denied the action."""
    client, _, _ = review_client
    for value in (42_000, 3_200):
        claim_id = client.post("/api/claims", json=_fnol(value, valid_fnol)).json()["claim_id"]
        governance = client.post(f"/api/claims/{claim_id}/analyze").json()["governance"]

        assert governance["permitted"] == governance["automated_action_allowed"]
        if governance["invariant_violated"]:
            assert governance["automated_action_allowed"] is False
            assert governance["side_effect_performed"] is False


# =========================================================================
# 13. The dashboard has to count the CP-14 refusals it records
#
# A routine automated-action denial is written as SUFFICIENT, because
# governance worked. That is the right ledger record and, for a while, the
# wrong dashboard: "actions denied: 0" while the automated action on a
# $42,000 claim was blocked is the report saying the opposite of what the
# ledger says.
# =========================================================================


def test_the_dashboard_counts_a_refused_automated_action(
    governance_client, governed_claim, recorder
):
    client, _, _ = governance_client
    _run(
        {
            **governed_claim,
            "claim_id": "CLM-GOV-9101",
            # Routing already chose a person, so the automated action is never
            # attempted -- the ordinary case for a large claim.
            "automated_route_proposed": False,
            "estimated_claim_value": 42_000.0,
        },
        recorder,
    )

    body = client.get("/api/governance").json()

    assert body["counts"]["automated_actions_denied"] == 1
    assert body["counts"]["actions_denied"] == 1
    # Routine, not an incident: nothing was violated and nothing is suspended.
    assert body["counts"]["invariant_violations"] == 0
    assert body["counts"]["terminal_states_open"] == 0


def test_the_dashboard_answers_why_the_automated_action_was_denied(
    governance_client, governed_claim, recorder
):
    client, _, _ = governance_client
    _run(
        {
            **governed_claim,
            "claim_id": "CLM-GOV-9102",
            "automated_route_proposed": False,
            "estimated_claim_value": 42_000.0,
        },
        recorder,
    )

    denied = client.get("/api/governance").json()["denied_actions"]
    entry = next(a for a in denied if a["claim_id"] == "CLM-GOV-9102")

    assert entry["gate_kind"] == "automated_action"
    assert entry["gate"] == "automated-authority-limit"
    assert entry["commitment_point"] == "automated_claim_action"
    assert entry["observed_value"] == 42_000.0
    assert entry["threshold_value"] == 20_000.0
    assert entry["terminal_state"] is None
    assert "not permitted" in (entry["detail"] or "")


def test_a_refused_action_is_not_reported_as_an_invariant_violation(
    governance_client, governed_claim, recorder
):
    """The two must stay distinguishable.

    An Invariant violation means something tried to do a prohibited thing and a
    person now owes a root-cause analysis. A refusal means the rule held. Giving
    them the same gate_kind would make routine traffic look like an incident
    queue.
    """
    client, _, _ = governance_client
    _run(
        {
            **governed_claim,
            "claim_id": "CLM-GOV-9103",
            "automated_route_proposed": False,
            "estimated_claim_value": 42_000.0,
        },
        recorder,
    )
    # And one that IS an incident: the action was attempted on a lapsed policy.
    _run(
        {
            **governed_claim,
            "claim_id": "CLM-GOV-9104",
            "automated_route_proposed": True,
            "policy_in_force_at_loss": False,
        },
        recorder,
    )

    denied = client.get("/api/governance").json()["denied_actions"]
    kinds = {a["claim_id"]: a["gate_kind"] for a in denied}

    assert kinds["CLM-GOV-9103"] == "automated_action"
    assert kinds["CLM-GOV-9104"] == "invariant"
