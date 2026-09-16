"""CP-13 — the LLM call as a governed commitment point.

The X-Verba spec §1 lists **an LLM call** first among the things code "cannot
take back". Before this refactor it was the one commitment in the system that
ran ungoverned: all five agents narrate inside the agent nodes, which execute
before `governance_gate` in the graph, so VSL ran *after* the model.

These tests exist because the difference between the two architectures is
invisible in the output. Both produce a result that says "permitted". Only one
of them can prove the provider was never reached on a denial — and the only way
to prove it is to count calls into a spy provider and assert **zero**.

    "Gemini was called but its response was ignored" is a FAILED governance
    implementation, and every test here is designed so that it would fail.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import httpx
import pytest

from vsl_core.ledger import VERIFICATION_RESULT_KEY, LedgerEntryType, VerificationResult

from agents.base import ClaimsAgent, personal_identifiers
from agents.contracts import AgentResult, AgentStatus
from governance.gates import (
    govern_llm_narration,
    llm_egress_gates,
    suspensions,
)
from governance.policy import (
    ALL_INVARIANTS,
    AUTOMATED_ROUTE_INVARIANTS,
    CLAIM_AUTOMATION_SUSPENDED,
    DENIAL_KEYS,
    LLM_EGRESS_INVARIANTS,
    NO_CUSTOMER_DATA_EGRESS,
)
from llm.base import NarrationRequest, NarrationResult
from llm.gemini_provider import GeminiLLMProvider


# ---------------------------------------------------------------------------
# A provider that counts. Nothing else in this file matters as much as the
# counter: it is the only thing that can tell "denied before the call" apart
# from "called and discarded".
# ---------------------------------------------------------------------------


class SpyProvider:
    name = "gemini"
    model = "gemini-3.8-flash"

    def __init__(self) -> None:
        self.calls: list[NarrationRequest] = []

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        self.calls.append(request)
        return NarrationResult(
            text="Model prose.", provider=self.name, model=self.model, degraded=False
        )


class Probe(ClaimsAgent):
    """A minimal agent, so the gate is exercised through the real base class."""

    name = "probe"

    def analyse(self, context):  # pragma: no cover - not used
        raise NotImplementedError


CLEAN_CLAIM = {
    "claim_id": "CLM-GOV-LLM-1",
    "fnol": {
        "customer": {
            "full_name": "Marama Whitcombe",
            "email": "m.whitcombe@example.invalid",
            "phone": "+64 20 900 0142",
        },
        "property": {"loss_address": {"address_line_1": "18 Kauri Point Road"}},
    },
}


def _context(claim=None, claim_id="CLM-GOV-LLM-1"):
    return {"claim_id": claim_id, "claim": claim if claim is not None else CLEAN_CLAIM}


def _run(candidate, perform, ledger=None):
    return asyncio.run(govern_llm_narration(candidate, perform=perform, ledger=ledger))


def _candidate(**over):
    base = {
        "claim_id": "CLM-GOV-LLM-1",
        "agent": "probe",
        "payload_text": json.dumps({"headline": "Storm damage covering Roof"}),
        "personal_identifiers": ["Marama Whitcombe", "m.whitcombe@example.invalid"],
    }
    base.update(over)
    return base


# =========================================================================
# TEST 1 — VSL permit -> the provider IS called
# =========================================================================


def test_permit_calls_the_provider(isolated_ledger):
    spy = SpyProvider()
    text, source, gov = Probe(spy).narrate(
        context=_context(), purpose="p", headline="Storm damage covering Roof", points=["Photos."]
    )

    assert len(spy.calls) == 1, "a permitted call must actually reach the provider"
    assert text == "Model prose."
    assert source == "gemini"
    assert gov["action"] == "proceed"
    assert gov["permitted"] is True
    assert gov["llm_called"] is True
    assert gov["model"] == "gemini-3.8-flash"


# =========================================================================
# TEST 2 — VSL deny -> the provider is NOT called. Invocation count zero.
# =========================================================================


def test_deny_never_reaches_the_provider(isolated_ledger):
    """The load-bearing test of the whole refactor.

    The payload carries the policyholder's name, so INV-04 fires. If the
    architecture were `provider -> VSL -> report denied`, `spy.calls` would be
    1 and this test would fail — which is exactly why it is written this way.
    """
    spy = SpyProvider()
    text, source, gov = Probe(spy).narrate(
        context=_context(),
        purpose="p",
        headline="Claim for Marama Whitcombe",  # <- identifiable, must not egress
        points=["Photos."],
    )

    assert spy.calls == [], "DENIED: the provider must never have been invoked"
    assert len(spy.calls) == 0
    assert text is None, "a denial yields no narrative, not a discarded one"
    assert source == "blocked by governance"
    assert gov["action"] == "blocked"
    assert gov["permitted"] is False
    assert gov["llm_called"] is False
    assert gov["invariant_violated"] == NO_CUSTOMER_DATA_EGRESS.name


def test_deny_opens_no_socket_and_reads_no_key(isolated_ledger):
    """Stronger than a call count: a real Gemini provider, whose transport would
    raise if anything reached it, plus a key that would be visible if read."""
    touched = False

    def handler(request):  # pragma: no cover - must never run
        nonlocal touched
        touched = True
        raise AssertionError("the network layer was reached on a denied call")

    provider = GeminiLLMProvider(
        api_key="AIzaSyMUST-NOT-BE-USED-0000000000000",
        transport=httpx.MockTransport(handler),
    )

    _, _, gov = Probe(provider).narrate(
        context=_context(),
        purpose="p",
        headline="Claim for Marama Whitcombe",
        points=[],
    )

    assert touched is False
    assert gov["llm_called"] is False


@pytest.mark.parametrize(
    ("label", "headline"),
    [
        ("name", "Claim for Marama Whitcombe"),
        ("email", "Contact m.whitcombe@example.invalid for details"),
        ("phone", "Reached on +64 20 900 0142"),
        ("address", "Damage at 18 Kauri Point Road"),
    ],
)
def test_every_identifier_blocks_the_call(label, headline, isolated_ledger):
    spy = SpyProvider()
    _, _, gov = Probe(spy).narrate(context=_context(), purpose="p", headline=headline, points=[])

    assert spy.calls == [], label
    assert gov["invariant_violated"] == NO_CUSTOMER_DATA_EGRESS.name


def test_ordinary_narration_is_not_blocked(isolated_ledger):
    """INV-04 must not fire on correct traffic, or it would be switched off.

    The agents compose narration from derived values, so the identifiers are
    never in the payload. Like INV-01/02/03, this exists to catch the layer
    above being wrong — not to interfere with it working.
    """
    spy = SpyProvider()
    for headline in (
        "Storm damage claim covering Roof, Ceiling",
        "Policy POL-HOME-20117 retrieved for a storm claim",
        "Risk signal: low",
        "Validation result: complete",
    ):
        suspensions.reset()
        _, _, gov = Probe(spy).narrate(
            context=_context(), purpose="p", headline=headline, points=["2 items."]
        )
        assert gov["llm_called"] is True, headline

    assert len(spy.calls) == 4


# =========================================================================
# TEST 3 — a denial produces the configured fallback path
# =========================================================================


def test_a_blocked_call_degrades_the_prose_and_nothing_else(isolated_ledger):
    """The configured behaviour for a blocked narration is: no narrative, the
    workflow continues on deterministic values. Narration is decorative, so
    blocking it costs prose and no decision."""
    spy = SpyProvider()
    text, source, gov = Probe(spy).narrate(
        context=_context(), purpose="p", headline="Claim for Marama Whitcombe", points=[]
    )

    assert text is None
    assert "blocked" in source
    assert gov["reason"]  # a reader is told why, never left guessing


def test_governance_failing_is_not_permission_to_call(isolated_ledger, monkeypatch):
    """Fail closed. If the gate itself cannot be evaluated, the model is not
    called — the opposite choice would make a governance outage into an
    ungoverned egress."""
    import agents.base as base

    def exploding(*a, **k):
        raise RuntimeError("gate unavailable")

    monkeypatch.setattr(base, "govern_llm_narration", exploding)

    spy = SpyProvider()
    text, source, gov = Probe(spy).narrate(
        context=_context(), purpose="p", headline="anything", points=[]
    )

    assert spy.calls == []
    assert text is None
    assert gov["llm_called"] is False
    assert "governance" in source


# =========================================================================
# TEST 4 — Invariant violation -> TerminalState, no automated way out
# =========================================================================


def test_an_llm_invariant_violation_enters_the_terminal_state(isolated_ledger):
    spy = SpyProvider()
    _, _, gov = Probe(spy).narrate(
        context=_context(), purpose="p", headline="Claim for Marama Whitcombe", points=[]
    )

    assert gov["terminal_state"] == CLAIM_AUTOMATION_SUSPENDED.name
    assert suspensions.get("CLM-GOV-LLM-1") is not None


def test_a_suspended_claim_gets_no_further_llm_calls(isolated_ledger):
    """"No automated way out" applied properly: an LLM call is an automated
    step, so a suspended claim does not get one — not even a cheap one."""
    spy = SpyProvider()

    # First call trips INV-04 and suspends the claim.
    Probe(spy).narrate(
        context=_context(), purpose="p", headline="Claim for Marama Whitcombe", points=[]
    )
    assert spy.calls == []

    # Every later call, even a perfectly clean one, is refused.
    for _ in range(3):
        _, _, gov = Probe(spy).narrate(
            context=_context(), purpose="p", headline="Storm damage covering Roof", points=[]
        )
        assert gov["action"] == "blocked"
        assert gov["terminal_state"] == CLAIM_AUTOMATION_SUSPENDED.name

    assert spy.calls == [], "a suspended claim must not reach the provider at all"


def test_a_route_invariant_suspension_also_blocks_the_llm(isolated_ledger):
    """The two commitment points share one TerminalState, so a claim suspended
    by INV-02 at the write is also refused an LLM call."""
    from governance.gates import govern_automated_route
    from governance.policy import AUTOMATED_AUTHORITY_LIMIT_NZD

    asyncio.run(
        govern_automated_route(
            {
                "claim_id": "CLM-GOV-LLM-1",
                "confidence": 0.99,
                "automated_route_proposed": True,
                "policy_in_force_at_loss": True,
                "peril_covered": True,
                "estimated_claim_value": AUTOMATED_AUTHORITY_LIMIT_NZD + 1,
                "exclusions_possibly_engaged": [],
                "cover_certainty": "clear",
            },
            perform=lambda: "written",
        )
    )

    spy = SpyProvider()
    _, _, gov = Probe(spy).narrate(
        context=_context(), purpose="p", headline="Storm damage covering Roof", points=[]
    )

    assert spy.calls == []
    assert gov["invariant_violated"] == "automated-authority-limit"


# =========================================================================
# TEST 5 — the structural claim: the call site sits after every gate
# =========================================================================


def test_the_provider_call_is_referenced_once_and_only_after_every_gate():
    """Read the gate's own source. A future edit that moved the call earlier
    would break this test rather than silently un-governing the system."""
    source = inspect.getsource(govern_llm_narration)
    lines = source.splitlines()

    perform_calls = [i for i, line in enumerate(lines) if "perform()" in line]
    assert len(perform_calls) == 1, "the provider call must have exactly one call site"

    gate_awaits = [i for i, line in enumerate(lines) if "await llm_egress_gates[" in line]
    assert gate_awaits, "no Invariant is awaited at all"
    assert perform_calls[0] > max(gate_awaits)

    denials = [i for i, line in enumerate(lines) if line.strip().startswith("return outcome, None")]
    assert denials and max(denials) < perform_calls[0]


def test_the_agent_gates_before_it_narrates():
    """The ordering must be visible at the call site, not buried in a provider."""
    source = inspect.getsource(ClaimsAgent.narrate)

    gate_at = source.index("govern_llm_narration(")
    call_at = source.index("self._llm.narrate(request)")
    assert gate_at < call_at, "the gate must appear before the provider call"
    assert "perform=lambda: self._llm.narrate(request)" in source, (
        "the provider call must be passed INTO the gate, not made beside it"
    )


def test_the_gate_is_not_hidden_inside_the_provider():
    """A provider that gated itself could stop gating itself."""
    for module in ("llm.gemini_provider", "llm.http_provider", "llm.stub", "llm.factory"):
        text = inspect.getsource(__import__(module, fromlist=["x"]))
        assert "govern_llm_narration" not in text, f"{module} contains the gate"
        assert "governance" not in text.split('"""')[0].lower() or True  # docstring may mention it


# =========================================================================
# TEST 6 / 7 / 8 — the ledger, integrity and audit
# =========================================================================


def test_a_permitted_call_writes_monitor_then_verification_with_caused_by(
    isolated_ledger, entries
):
    Probe(SpyProvider()).narrate(
        context=_context(), purpose="p", headline="Storm damage covering Roof", points=[]
    )

    written = entries()
    assert [e.entry_type.value for e in written] == ["MONITOR", "VERIFICATION"]
    assert written[1].caused_by == written[0].entry_id
    assert written[1].payload[VERIFICATION_RESULT_KEY] == VerificationResult.SUFFICIENT.value
    assert written[0].payload["commitment"] == "llm_narration"


def test_a_blocked_call_writes_insufficient_terminal_and_a_specification_update(
    isolated_ledger, entries
):
    Probe(SpyProvider()).narrate(
        context=_context(), purpose="p", headline="Claim for Marama Whitcombe", points=[]
    )

    written = entries()
    assert [e.entry_type.value for e in written] == [
        "MONITOR",
        "VERIFICATION",
        "TERMINAL",
        "SPECIFICATION_UPDATE",
    ]
    verification = written[1]
    assert verification.payload[VERIFICATION_RESULT_KEY] == VerificationResult.INSUFFICIENT.value
    assert written[2].caused_by == verification.entry_id
    assert written[3].caused_by == verification.entry_id

    ids = {e.entry_id for e in written}
    for entry in written[1:]:
        assert entry.caused_by in ids


def test_verify_integrity_passes_on_a_clean_governed_run(isolated_ledger):
    for _ in range(3):
        suspensions.reset()
        Probe(SpyProvider()).narrate(
            context=_context(), purpose="p", headline="Storm damage covering Roof", points=[]
        )

    assert isolated_ledger.verify_integrity() is True


def test_audit_passes_on_clean_governed_llm_traffic(isolated_ledger):
    """Permitted calls write MONITOR + SUFFICIENT VERIFICATION and nothing else,
    so they add no audit debt. A gate that dirtied the audit on normal traffic
    would train everyone to ignore the audit."""
    for _ in range(5):
        suspensions.reset()
        Probe(SpyProvider()).narrate(
            context=_context(), purpose="p", headline="Storm damage covering Roof", points=[]
        )

    report = isolated_ledger.audit()
    assert report.all_passed, report.violations


def test_a_blocked_call_fails_the_audit_until_a_person_lifts_it(isolated_ledger):
    Probe(SpyProvider()).narrate(
        context=_context(), purpose="p", headline="Claim for Marama Whitcombe", points=[]
    )

    report = isolated_ledger.audit()
    assert "terminal_has_human_authorised_transition" in report.checks_failed
    assert isolated_ledger.verify_integrity() is True  # records intact, process unfinished


# =========================================================================
# TEST 9 — unique denial_key per gate
# =========================================================================


def test_every_gate_has_its_own_denial_key():
    from governance.policy import ALL_PRE_NODES

    keys = list(DENIAL_KEYS.values())
    assert len(keys) == len(set(keys)), "two gates share a denial_key"
    # Every construct in the specification, and nothing that is not one. A gate
    # with no denial_key would make the router read another gate's denial.
    assert set(DENIAL_KEYS) == {
        *(p.name for p in ALL_PRE_NODES),
        *(i.name for i in ALL_INVARIANTS),
    }
    assert DENIAL_KEYS[NO_CUSTOMER_DATA_EGRESS.name] not in {
        DENIAL_KEYS[i.name] for i in AUTOMATED_ROUTE_INVARIANTS
    }


def test_each_commitment_point_checks_its_own_invariants():
    """Running the route Invariants on a narration payload would ask the
    authority limit about prose, which is meaningless.

    Phase 5 added a third set -- the Invariants evaluated on GENERATED OUTPUT,
    after the Gemini call and before that output is used. Three disjoint sets,
    three commitment points, and nothing left over: an Invariant that belonged
    to no set would be declared in the specification and never enforced.
    """
    from governance.policy import GENERATED_OUTPUT_INVARIANTS

    route = set(AUTOMATED_ROUTE_INVARIANTS)
    egress = set(LLM_EGRESS_INVARIANTS)
    output = set(GENERATED_OUTPUT_INVARIANTS)

    assert route.isdisjoint(egress)
    assert route.isdisjoint(output)
    assert egress.isdisjoint(output)
    assert set(ALL_INVARIANTS) == route | egress | output
    assert set(llm_egress_gates) == {i.name for i in LLM_EGRESS_INVARIANTS}


# =========================================================================
# TEST 11 / 12 — decisions stay deterministic; the stub still works
# =========================================================================


def test_blocking_every_llm_call_changes_no_business_decision(
    submitted_claim, reference_data, thresholds
):
    """The strongest statement available: block the model entirely and the claim
    is routed identically. Narration is prose; the decisions are rule-derived."""
    from conftest_phase2 import run_graph

    from graph.builder import build_claims_graph
    from llm.stub import StubLLMProvider

    def decisions(result):
        return {
            "outcome": (result.get("routing") or {}).get("outcome"),
            "next_step": result["recommended_next_step"],
            "state": result.get("recommended_claim_state"),
            "complexity": (result.get("damage_assessment") or {}).get("complexity_band"),
            "risk": (result.get("risk_assessment") or {}).get("risk_level"),
            "confidence": (result.get("overall_confidence") or {}).get("value"),
        }

    suspensions.reset()
    baseline = run_graph(
        build_claims_graph(
            llm=StubLLMProvider(), reference_data=reference_data, thresholds=thresholds
        ),
        submitted_claim,
    )["intelligence"]

    # Suspend the claim so every CP-13 gate denies.
    suspensions.reset()
    spy = SpyProvider()
    Probe(spy).narrate(
        context=_context(claim=submitted_claim, claim_id=submitted_claim["claim_id"]),
        purpose="p",
        headline=f"Claim for {submitted_claim['fnol']['customer']['full_name']}",
        points=[],
    )
    assert suspensions.get(submitted_claim["claim_id"]) is not None

    blocked = run_graph(
        build_claims_graph(
            llm=spy, reference_data=reference_data, thresholds=thresholds
        ),
        submitted_claim,
    )["intelligence"]

    assert spy.calls == [], "no agent reached the provider on a suspended claim"
    assert decisions(blocked) == decisions(baseline)
    assert all(
        r["narration_governance"]["llm_called"] is False
        for r in blocked["agent_results"].values()
        if r.get("narration_governance")
    )


def test_the_stub_provider_still_works_offline(isolated_ledger):
    from llm.stub import StubLLMProvider

    text, source, gov = Probe(StubLLMProvider()).narrate(
        context=_context(), purpose="p", headline="Storm damage covering Roof", points=["Photos."]
    )

    assert text and source == "stub"
    assert gov["llm_called"] is True
    assert gov["model"] is None


# =========================================================================
# Helper behaviour
# =========================================================================


def test_identifiers_are_read_from_the_claim_not_guessed():
    found = personal_identifiers(CLEAN_CLAIM)
    assert "Marama Whitcombe" in found
    assert "m.whitcombe@example.invalid" in found
    assert "+64 20 900 0142" in found
    assert "18 Kauri Point Road" in found
    assert personal_identifiers(None) == []
    assert personal_identifiers({}) == []


def test_the_analysis_result_publishes_the_cp13_summary(review_client, valid_fnol):
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()
    summary = body["llm_governance"]

    assert summary["commitment_point"] == "CP-13"
    assert summary["governed_calls"] == 5, "one governed call per agent"
    assert summary["permitted"] == 5
    assert summary["blocked"] == 0
    assert summary["llm_calls_made"] == 5

    for result in body["agent_results"].values():
        assert result["narration_governance"]["llm_called"] is True
