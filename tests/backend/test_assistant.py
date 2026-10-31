"""Phase 5 — the conversational AI claims assistant.

Organised around the ways a conversational claims interface fails in practice,
because those are the tests worth having:

    1.  Lifecycle        does a conversation exist, persist and read back?
    2.  Understanding    does one message yield several facts?
    3.  Not guessing     is vague input refused rather than resolved?
    4.  Not fabricating  can the model put a value into a claim on its own?
    5.  Confirmation     can a claim exist before the customer said yes?
    6.  Creation         is it the SAME claim workflow, with a real id?
    7.  The architecture PreNode -> Gemini -> Invariant, in that order, always
    8.  Continuity       do Phase 3 and Phase 4 still work?

No test here makes a network call. `CountingProvider` records what would have
been sent and how many times, which is the only evidence that distinguishes
"the model was never called" from "the model was called and ignored".
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.assistant_service import (
    ClaimAlreadyCreatedError,
    ConversationNotFoundError,
    ConversationNotReadyError,
)
from conversation.builder import ConversationIncompleteError, to_submission
from conversation.contracts import ConversationStage, ConversationState
from conversation.fields import REQUIRED_FIELDS, missing_fields, next_field
from tests.backend.conftest_phase5 import ANSWERS, CountingProvider, extraction

# =========================================================================
# 1. Lifecycle
# =========================================================================


def test_a_conversation_can_be_created(assistant):
    """REQUIREMENT 1. Starting a conversation creates no claim and asks nothing."""
    turn = assistant.start()

    assert turn.conversation.conversation_id.startswith("CNV-")
    assert turn.conversation.claim_id is None
    assert turn.conversation.customer_confirmed is False
    assert turn.conversation.collected_count == 0
    assert turn.reply, "the assistant opens the conversation"


def test_a_customer_message_gets_a_reply(assistant):
    """REQUIREMENT 2."""
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "A storm damaged my roof last night.")

    assert turn.reply
    assert turn.conversation.conversation_id == conversation_id
    assert any(m["role"] == "customer" for m in turn.conversation.messages)
    assert any(m["role"] == "assistant" for m in turn.conversation.messages)


def test_conversation_state_persists_between_turns(assistant):
    """REQUIREMENT 3. State survives the turn, and is READ BACK from the store.

    Asserted through `get()` rather than the turn response, because a service
    that held state in memory and never saved it would pass the weaker check and
    lose every conversation on restart.
    """
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Storm damage.")
    assistant.send(conversation_id, "Marama Whitcombe")

    view = assistant.get(conversation_id)

    names = [item.field for item in view.collected_information]
    assert "full_name" in names
    assert len(view.messages) >= 4


def test_an_unknown_conversation_is_a_customer_safe_404(assistant):
    with pytest.raises(ConversationNotFoundError) as exc:
        assistant.get("CNV-DOES-NOT-EXIST")

    assert exc.value.http_status == 404
    assert "conversation" in exc.value.customer_message.lower()
    # No identifier, no exception text, nothing technical.
    assert "CNV-DOES-NOT-EXIST" not in exc.value.customer_message


# =========================================================================
# 2. Understanding — several facts from one message
# =========================================================================


def test_one_message_can_carry_several_facts(assistant, provider):
    """REQUIREMENTS 4 and 5.

    "The storm damaged my roof yesterday and the damage is probably around
    $7,500" is three facts, and a conversation that took them one at a time
    would be a form with extra steps.
    """
    provider.reply = extraction(
        {
            "damaged_areas": ["roof"],
            "date_of_loss": "2026-09-14",
            "estimated_damage_value": 7500,
        }
    )
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(
        conversation_id,
        "The storm damaged my roof yesterday and the damage is probably around $7,500.",
    )

    collected = {item.field for item in turn.conversation.collected_information}
    assert {"damaged_areas", "date_of_loss", "estimated_damage_value"} <= collected


def test_missing_information_is_detected_and_named(assistant):
    """REQUIREMENT 6. Derived from the catalogue, never remembered.

    Asserted as a relationship between what is collected and what is missing,
    rather than as a count. A count assumed one field per turn, which stopped
    being true once deterministic extraction could read several facts out of one
    sentence -- the opening message alone now yields a date and a damaged area.
    """
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "A storm damaged my roof last night.")
    turn = assistant.send(conversation_id, "Marama Whitcombe")

    missing = {item.field for item in turn.conversation.missing_information}
    collected = {item.field for item in turn.conversation.collected_information}

    assert "full_name" not in missing, "it was just collected"
    assert "full_name" in collected
    assert "policy_number" in missing
    # Every required field is in exactly one of the two sets, always.
    assert missing | collected >= set(REQUIRED_FIELDS)
    assert missing.isdisjoint(collected)
    assert all(item.question for item in turn.conversation.missing_information)


def test_the_assistant_asks_for_exactly_what_is_missing(assistant):
    """The next question comes from the catalogue, not from the model's mood."""
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Storm damage to the roof.")
    turn = assistant.send(conversation_id, "Marama Whitcombe")

    expected = next_field(
        {item.field: item.value for item in turn.conversation.collected_information}
    )
    assert expected is not None
    assert expected.question in turn.reply


# =========================================================================
# 3. Not guessing
# =========================================================================


def test_an_ambiguous_date_is_marked_uncertain_not_resolved(assistant, provider):
    """REQUIREMENT 7. "Sometime last week" is not a date, and must not become one.

    A wrong date of loss can decide whether a policy was in force, so the
    assistant asks rather than picks a day.
    """
    provider.reply = extraction(uncertain={"date_of_loss": "sometime last week"})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "It happened sometime last week.")

    uncertain = {item.field: item for item in turn.conversation.uncertain_information}
    assert "date_of_loss" in uncertain
    assert uncertain["date_of_loss"].said == "sometime last week"
    assert "date_of_loss" in {
        item.field for item in turn.conversation.missing_information
    }
    assert not any(
        item.field == "date_of_loss" for item in turn.conversation.collected_information
    )


def test_a_rejected_answer_produces_a_specific_question_not_a_shrug(assistant):
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Storm damage.")
    assistant.send(conversation_id, "Marama Whitcombe")

    turn = assistant.send(conversation_id, "not an email")

    assert "email" in turn.reply.lower()
    assert not any(
        item.field == "email" for item in turn.conversation.collected_information
    )


def test_a_vague_money_answer_is_not_rounded_into_a_number(assistant):
    """"A few thousand" must not become 3000."""
    from conversation.fields import validate_money

    value, reason = validate_money("a few thousand")

    assert value is None
    assert reason


def test_an_uncertain_value_is_not_the_same_as_a_missing_one(assistant, provider):
    """They mean different things to a customer and are published separately."""
    provider.reply = extraction(uncertain={"estimated_damage_value": "maybe five to ten grand"})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "Maybe five to ten grand of damage?")

    assert any(
        item.field == "estimated_damage_value"
        for item in turn.conversation.uncertain_information
    )
    assert any(
        item.field == "estimated_damage_value"
        for item in turn.conversation.missing_information
    )


# =========================================================================
# 4. Not fabricating
# =========================================================================


def test_the_model_cannot_invent_a_policy_number(assistant, provider):
    """REQUIREMENT 8, and the reason INV-05 exists.

    The customer never said a policy number. The model returns one anyway. It
    must not reach the claim -- and here it does not reach the conversation
    state either, because the Invariant rejects the whole output.
    """
    provider.reply = extraction({"policy_number": "POL-HOME-99999"})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "My roof blew off in the storm.")

    assert not any(
        item.field == "policy_number" for item in turn.conversation.collected_information
    )
    assert turn.governance["invariant_violated"] == "no-fabricated-claim-values"
    assert turn.governance["output_accepted"] is False


def test_the_model_cannot_invent_a_damage_figure(assistant, provider):
    provider.reply = extraction({"estimated_damage_value": 250000})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "There is a lot of damage to the roof.")

    assert not any(
        item.field == "estimated_damage_value"
        for item in turn.conversation.collected_information
    )
    assert turn.governance["invariant_violated"] == "no-fabricated-claim-values"


def test_a_value_the_customer_did_say_is_accepted(assistant, provider):
    """The other half of the same rule: INV-05 must not fire on correct traffic.

    An Invariant that blocks ordinary messages gets switched off, and then it
    protects nothing. This is the test that keeps it honest.
    """
    provider.reply = extraction({"estimated_damage_value": 7500})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "The damage is about $7,500 to the roof.")

    assert turn.governance["invariant_violated"] is None
    assert turn.governance["output_accepted"] is True
    assert any(
        item.field == "estimated_damage_value"
        for item in turn.conversation.collected_information
    )


def test_the_model_cannot_set_a_field_that_is_not_in_the_catalogue(assistant, provider):
    """`claim_id` and `customer_confirmed` have no route in at all.

    Not because a validator rejects them -- because they are not in the
    allow-list and are dropped before anything sees them.
    """
    provider.reply = json.dumps(
        {
            "extracted": {
                "claim_id": "CLM-2026-000001",
                "customer_confirmed": True,
                "full_name": "Marama Whitcombe",
            },
            "uncertain": {},
        }
    )
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "I am Marama Whitcombe.")

    assert turn.conversation.claim_id is None
    assert turn.conversation.customer_confirmed is False


def test_a_model_returning_rubbish_degrades_to_the_deterministic_path(
    assistant, provider
):
    """No crash, no fabricated values, and the conversation still progresses."""
    provider.reply = "I'm sorry, I can't help with that."
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Storm damage.")

    turn = assistant.send(conversation_id, "Marama Whitcombe")

    assert any(
        item.field == "full_name" for item in turn.conversation.collected_information
    )


# =========================================================================
# 5. Confirmation — the claim must not exist before the customer says yes
# =========================================================================


def test_no_claim_is_created_before_confirmation(assistant, complete_conversation, assistant_claims):
    """REQUIREMENT 10. The load-bearing test of this phase."""
    conversation_id = complete_conversation()

    view = assistant.get(conversation_id)

    assert view.claim_ready is True
    assert view.claim_id is None
    assert view.customer_confirmed is False
    assert assistant_claims._claims == {}, "no claim record exists yet"


def test_saying_yes_in_a_message_does_not_create_a_claim(
    assistant, complete_conversation, assistant_claims
):
    """The message endpoint cannot create a claim, whatever the customer types.

    This is why confirmation is a separate endpoint: otherwise "yes" would be a
    phrase a model gets to interpret as consent to lodge a claim.
    """
    conversation_id = complete_conversation()

    for affirmative in ("yes", "yes please submit it", "go ahead", "confirmed"):
        assistant.send(conversation_id, affirmative)
        assert assistant.get(conversation_id).claim_id is None

    assert assistant_claims._claims == {}


def test_confirming_an_incomplete_conversation_is_refused(assistant, assistant_claims):
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Storm damage to my roof.")

    with pytest.raises(ConversationNotReadyError) as exc:
        assistant.confirm(conversation_id)

    assert exc.value.http_status == 409
    assert assistant_claims._claims == {}


def test_the_builder_refuses_an_incomplete_conversation_too(assistant):
    """The backstop under the service check.

    Two independent refusals, because "a claim is never built from an incomplete
    conversation" should not depend on one caller remembering to check.
    """
    state = ConversationState(conversation_id="CNV-PARTIAL")
    state.record("full_name", "Marama Whitcombe")

    with pytest.raises(ConversationIncompleteError) as exc:
        to_submission(state)

    assert "policy_number" in exc.value.missing


def test_a_claim_cannot_be_created_twice(assistant, complete_conversation):
    conversation_id = complete_conversation()
    assistant.confirm(conversation_id)

    with pytest.raises(ClaimAlreadyCreatedError):
        assistant.confirm(conversation_id)


# =========================================================================
# 6. Creation — the same workflow, a real id
# =========================================================================


def test_confirmation_creates_the_claim_and_returns_a_real_id(
    assistant, complete_conversation, assistant_claims
):
    """REQUIREMENTS 11, 12 and 13."""
    conversation_id = complete_conversation()

    created = assistant.confirm(conversation_id)

    assert created.claim_id.startswith("CLM-")
    assert created.claim_state.value == "Submitted"
    # The real record, in the ORIGINAL claim store -- not a second one.
    record = assistant_claims.get(created.claim_id)
    assert record is not None
    assert record["claim_state"] == "Submitted"
    assert record["source"] == "customer_portal"
    assert record["synthetic"] is True


def test_the_created_claim_carries_what_the_customer_actually_said(
    assistant, complete_conversation, assistant_claims
):
    conversation_id = complete_conversation()
    created = assistant.confirm(conversation_id)

    fnol = assistant_claims.get(created.claim_id)["fnol"]

    assert fnol["customer"]["full_name"] == "Marama Whitcombe"
    assert fnol["customer"]["policy_number"] == "POL-HOME-20117"
    # "…last night" in the opening message, resolved deterministically. Asserted
    # against a computed date rather than a literal, because a hard-coded one
    # is only correct on the day it was written.
    assert fnol["damage"]["date_of_loss"] == (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    ).isoformat()
    assert fnol["damage"]["customer_estimated_value"] == 7500.0
    assert fnol["damage"]["peril"] == "storm"
    assert fnol["property"]["loss_address"]["postcode"] == "0604"


def test_the_estimate_is_not_multiplied_across_damaged_areas(
    assistant, complete_conversation, assistant_claims
):
    """The customer gave ONE figure for the whole loss, not one per area.

    Repeating it on every damaged item would silently inflate a NZD 7,500 claim
    to NZD 15,000 -- and straight past INV-02's authority limit on a larger one.
    """
    conversation_id = complete_conversation()
    created = assistant.confirm(conversation_id)

    items = assistant_claims.get(created.claim_id)["fnol"]["damage"]["damaged_items"]

    assert len(items) == 2, "roof and ceiling"
    assert sum(i["estimated_value"] or 0 for i in items) == 7500.0


def test_the_summary_shown_is_the_claim_submitted(assistant, complete_conversation):
    """What the customer confirms and what is lodged must be the same thing."""
    conversation_id = complete_conversation()
    before = {
        item.field: item.value
        for item in assistant.get(conversation_id).collected_information
    }

    created = assistant.confirm(conversation_id)

    after = {item.field: item.value for item in created.conversation.collected_information}
    for field_name, value in before.items():
        assert after[field_name] == value


def test_the_claim_created_message_names_the_real_reference(
    assistant, complete_conversation
):
    conversation_id = complete_conversation()

    created = assistant.confirm(conversation_id)

    assert created.claim_id in created.message
    assert created.conversation.current_stage is ConversationStage.CLAIM_CREATED
    assert "approved" not in created.poc_note.lower().split("not ")[0]
    assert "not been assessed" in created.poc_note


def test_the_assistant_never_tells_a_customer_the_claim_is_decided(
    assistant, complete_conversation
):
    """Collecting information is not deciding a claim, and must not read as one."""
    conversation_id = complete_conversation()
    created = assistant.confirm(conversation_id)

    everything = " ".join(
        m["text"] for m in created.conversation.messages
    ).lower()

    for phrase in ("approved", "declined", "we will pay", "settled", "covered under"):
        assert phrase not in everything


# =========================================================================
# 7. The architecture — PreNode, then Gemini, then Invariant
# =========================================================================


def test_the_pre_node_runs_before_the_model_is_called(assistant, provider):
    """REQUIREMENT 15, asserted from the gate's own source.

    A passing end-to-end test cannot distinguish "gated, then called" from
    "called, then gated and the answer kept anyway" -- both produce a result.
    This reads the function and checks the ordering directly, which survives a
    future edit in a way a comment does not.
    """
    from governance.gates import govern_conversation_extraction

    source = inspect.getsource(govern_conversation_extraction)
    call_site = source.index("result = perform()")
    pre_node_await = source.index("await extraction_gate(")

    assert pre_node_await < call_site, "the PreNode must be awaited before the call"
    assert source.count("perform()") == 1, "one call site, or the ordering means nothing"


def test_the_invariants_run_after_the_model_and_before_the_result_escapes(assistant):
    """REQUIREMENTS 17 and 18, likewise from the source.

    Both halves matter. The Invariant must run AFTER the call (it judges output
    that does not exist before then) and the result must be returned only AFTER
    the Invariant (or a violating output could still be used).
    """
    from governance.gates import govern_conversation_extraction

    source = inspect.getsource(govern_conversation_extraction)
    call_site = source.index("result = perform()")
    invariant_await = source.index("await generated_output_gates[")
    success_return = source.rindex("return outcome, result")

    assert call_site < invariant_await, "the Invariant judges generated output"
    assert invariant_await < success_return, "nothing escapes before the Invariant"
    assert source.count("return outcome, result") == 1, "one way out"


def test_a_pre_node_denial_makes_zero_model_calls(assistant, provider):
    """REQUIREMENT 16. The count is the evidence; nothing else would do."""
    conversation_id = assistant.start().conversation.conversation_id
    before = provider.calls

    # A very long unprompted message: low turn confidence, below the derived
    # floor of 0.8148, so PN-02's Gamma evaluation denies.
    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.governance["pre_node_denied"] is True
    assert turn.governance["llm_called"] is False
    assert provider.calls == before, "THE MODEL MUST NOT HAVE BEEN CALLED"


def test_a_pre_node_denial_still_answers_the_customer(assistant, provider):
    """Governance denying a model call is not an outage. The claim continues."""
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.reply, "the customer is not left with silence"
    assert turn.governance["pre_node_denied"] is True


def test_an_invariant_violation_blocks_the_output_from_downstream(assistant, provider):
    """REQUIREMENT 18, end to end.

    The model WAS called -- the Invariant judges generated output, so it has to
    have been. What must not happen is the output reaching the state.
    """
    provider.reply = extraction({"policy_number": "POL-HOME-99999"})
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "The roof is damaged.")

    assert turn.governance["llm_called"] is True
    assert turn.governance["output_accepted"] is False
    assert turn.governance["terminal_state"] == "claim-automation-suspended"

    # The MODEL'S value is what must not have landed. Asserting an empty state
    # would be asserting something else entirely: "The roof is damaged" also
    # yields a damaged area by pattern, which never went near the model and is
    # not what the Invariant rejected. A test that conflated the two would fail
    # for a correct reason and be "fixed" by weakening the extractor.
    collected = {item.field for item in turn.conversation.collected_information}
    assert "policy_number" not in collected, "the rejected output must not land"
    assert collected <= {"damaged_areas"}


def test_the_gate_never_hands_back_output_it_rejected(assistant):
    """The enforcement is structural: the caller never receives it.

    Not "the caller is trusted to check the outcome first" -- there is nothing
    to check, because `result` is None on every rejection path.
    """
    from governance.gates import govern_conversation_extraction

    outcome, result = asyncio.run(
        govern_conversation_extraction(
            {
                "conversation_id": "CNV-REJECT",
                "claim_id": "CNV-REJECT",
                "confidence": 0.95,
                "source_text": "the roof is damaged",
            },
            perform=lambda: "GENERATED",
            inspect=lambda _: {
                "extracted": {"policy_number": "POL-HOME-00000"},
                "assistant_message": "",
            },
        )
    )

    assert outcome.llm_called is True
    assert outcome.output_accepted is False
    assert result is None, "a rejected output is never returned"


def test_the_gate_returns_output_it_accepted(assistant):
    """The other direction, so the test above is not passing for a silly reason."""
    from governance.gates import govern_conversation_extraction

    outcome, result = asyncio.run(
        govern_conversation_extraction(
            {
                "conversation_id": "CNV-ACCEPT",
                "claim_id": "CNV-ACCEPT",
                "confidence": 0.95,
                "source_text": "the damage is about 7500 dollars",
            },
            perform=lambda: "GENERATED",
            inspect=lambda _: {
                "extracted": {"estimated_damage_value": 7500},
                "assistant_message": "Thank you.",
            },
        )
    )

    assert outcome.output_accepted is True
    assert result == "GENERATED"


def test_no_construct_in_this_project_is_called_a_post_node(assistant):
    """REQUIREMENT: no PostNode, and no invented interception mechanism.

    Asserted against the constructs themselves rather than against the text of
    the modules -- the docstrings say the word "PostNode" precisely in order to
    say that there is not one, and a grep-based test would fail on its own
    documentation while a real PostNode named something else sailed through.

    What actually matters: every governance construct in the active
    Specification is a `vsl_core` PreNode, Invariant or TerminalState, and the
    gates module exposes no identifier suggesting a post-hoc interception
    mechanism.
    """
    from vsl_core import constructs as vsl_constructs

    import governance.gates as gates_module
    from governance.policy import ALL_INVARIANTS, ALL_PRE_NODES, ALL_TERMINAL_STATES

    assert not hasattr(vsl_constructs, "PostNode"), (
        "vsl_core itself has no PostNode; if that ever changes, this project's "
        "architecture decision needs revisiting deliberately, not silently."
    )

    for pre_node in ALL_PRE_NODES:
        assert type(pre_node) is vsl_constructs.PreNode
    for invariant in ALL_INVARIANTS:
        assert type(invariant) is vsl_constructs.Invariant
    for terminal in ALL_TERMINAL_STATES:
        assert type(terminal) is vsl_constructs.TerminalState

    exported = [name for name in dir(gates_module) if not name.startswith("_")]
    assert not [name for name in exported if "post" in name.lower()]


def test_the_generated_output_invariants_are_real_vsl_constructs(assistant):
    """`type(x) is Invariant`, not isinstance -- a duck-typed mock passes isinstance."""
    from vsl_core import constructs as vsl_constructs

    from governance.policy import GENERATED_OUTPUT_INVARIANTS

    assert GENERATED_OUTPUT_INVARIANTS, "the stage must have rules"
    for invariant in GENERATED_OUTPUT_INVARIANTS:
        assert type(invariant) is vsl_constructs.Invariant
        assert invariant.on_violation is not None
        assert invariant.assurance_level.value == "LOW"


def test_the_conversation_pre_node_is_a_real_vsl_pre_node(assistant):
    from vsl_core import constructs as vsl_constructs

    from governance.policy import CONVERSATION_EXTRACTION_CONFIDENCE

    assert type(CONVERSATION_EXTRACTION_CONFIDENCE) is vsl_constructs.PreNode
    assert CONVERSATION_EXTRACTION_CONFIDENCE.gamma_threshold is not None


def test_the_governed_turn_is_written_to_the_verba_ledger(assistant, entries):
    """REQUIREMENT 21. The application writes these entries; nothing intercepts."""
    conversation_id = assistant.start().conversation.conversation_id
    turn = assistant.send(conversation_id, "Marama Whitcombe")

    written = entries()
    kinds = [e.entry_type.value for e in written]

    assert "MONITOR" in kinds
    assert "PRE_NODE" in kinds
    assert "VERIFICATION" in kinds
    assert turn.governance["ledger_entry_ids"]
    # Causal order, not a timestamp heuristic.
    assert all(e.caused_by for e in written if e.entry_type.value != "MONITOR")


def test_the_ledger_records_the_conversation_and_the_threshold(assistant, entries):
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Marama Whitcombe")

    pre_nodes = [e for e in entries() if e.entry_type.value == "PRE_NODE"]

    assert pre_nodes
    payload = pre_nodes[-1].payload
    assert payload["conversation_id"] == conversation_id
    assert payload["pre_node"] == "conversation-extraction-confidence"
    assert payload["threshold_value"] == pytest.approx(0.8148, abs=5e-4)
    assert payload["denial_key"] == "vsl_denial__conversation_extraction_confidence"


def test_the_ledger_never_records_a_secret(assistant, entries, monkeypatch):
    """REQUIREMENT: no credential reaches the audit record."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyLEDGER-test-only-000000000000")
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "Marama Whitcombe")

    blob = json.dumps([e.payload for e in entries()])

    assert "AIzaSy" not in blob
    assert "GEMINI_API_KEY" not in blob


# =========================================================================
# 8. Continuity — nothing earlier was broken to make room
# =========================================================================


def test_the_existing_claim_api_still_works(client, valid_fnol):
    """REQUIREMENT 13. The form-based journey is untouched."""
    response = client.post("/api/claims", json=valid_fnol)

    assert response.status_code == 201
    assert response.json()["claim_state"] == "Submitted"


def test_a_conversationally_created_claim_runs_the_existing_workflow(
    assistant, complete_conversation, assistant_claims
):
    """REQUIREMENT 20. It is the same claim record, so it is the same workflow.

    Asserted on the record's SHAPE rather than by running the graph here: the
    Phase 2/3/4 suites already prove what the workflow does with a claim of this
    shape, and re-proving it would test those phases again rather than this one.
    """
    conversation_id = complete_conversation()
    created = assistant.confirm(conversation_id)

    record = assistant_claims.get(created.claim_id)

    assert set(record) >= {
        "claim_id",
        "claim_state",
        "internal_status",
        "created_at",
        "submitted_at",
        "source",
        "synthetic",
        "fnol",
    }
    assert record["policy_id"] is None, "Phase 2's Policy Agent resolves it"


def test_inv_02_still_governs_the_automated_action(assistant):
    """REQUIREMENT 19. Phase 5 must not have moved INV-02 into the conversation.

    A NZD 42,000 claim is still denied the automated action at CP-14, by the
    same Invariant, on the claim's own value.
    """
    from governance.gates import govern_automated_route

    performed: list[str] = []
    outcome, _ = asyncio.run(
        govern_automated_route(
            {
                "claim_id": "CLM-PHASE5-42K",
                "confidence": 0.94,
                "automated_route_proposed": False,
                "policy_in_force_at_loss": True,
                "peril_covered": True,
                "estimated_claim_value": 42_000.0,
                "exclusions_possibly_engaged": [],
                "cover_certainty": "clear",
            },
            perform=lambda: performed.append("side effect"),
        )
    )

    assert outcome.action == "action_denied"
    assert outcome.automated_action_allowed is False
    assert outcome.invariant_violated == "automated-authority-limit"
    assert outcome.observed_value == 42_000.0
    assert performed == [], "the automated action must not have run"


def test_the_conversation_layer_does_not_import_inv_02(assistant):
    """The separation stated as a rule, checked as a fact.

    The conversational layer governs a model call. It has no business deciding
    whether a claim may be handled automatically, and the way to keep that true
    is for the authority limit to be unreachable from here.
    """
    import app.services.assistant_service as service_module
    import conversation.fields as fields_module
    import graph.conversation_graph as graph_module

    for module in (service_module, fields_module, graph_module):
        source = inspect.getsource(module)
        assert "AUTOMATED_AUTHORITY_LIMIT" not in source
        assert "govern_automated_route" not in source


def test_the_human_review_queue_is_untouched_by_this_phase(client, valid_fnol):
    """REQUIREMENT 20."""
    response = client.get("/api/review-queue")

    assert response.status_code == 200
    assert "entries" in response.json()


def test_the_assistant_is_not_the_decision_maker(assistant):
    """The authority note is published on every view, not buried in a docstring."""
    view = assistant.start().conversation

    note = view.assistant_authority_note.lower()
    assert "does not approve" in note
    assert "claims specialist" in note


# =========================================================================
# 9. What the customer is shown
# =========================================================================


def test_no_governance_vocabulary_reaches_the_customer(assistant, complete_conversation):
    """The customer sees a conversation, not a governance console."""
    conversation_id = complete_conversation()
    view = assistant.get(conversation_id)

    customer_facing = " ".join(
        [m["text"] for m in view.messages]
        + [item.label for item in view.collected_information]
        + [item.question for item in view.missing_information]
        + [view.assistant_authority_note]
    ).lower()

    for term in (
        "vsl",
        "prenode",
        "pre-node",
        "invariant",
        "gamma",
        "verbaledger",
        "terminalstate",
        "fraud_risk",
        "x-verba",
    ):
        assert term not in customer_facing, f"{term!r} must not reach a customer"


def test_progress_is_derived_from_the_catalogue(assistant):
    view = assistant.start().conversation

    assert view.required_count == len(REQUIRED_FIELDS)
    assert view.collected_count == 0


def test_every_required_field_has_a_question_a_person_would_ask(assistant):
    """A catalogue entry with no question is a field the assistant can never collect."""
    from conversation.fields import FIELDS_BY_NAME

    for name in REQUIRED_FIELDS:
        spec = FIELDS_BY_NAME[name]
        # A question mark somewhere, not necessarily at the end: the policy
        # number question ends with an example, which is more useful than a
        # bare "?" and still reads as a question.
        assert "?" in spec.question, name
        assert spec.display(), name


def test_the_stage_reflects_what_is_known(assistant):
    conversation_id = assistant.start().conversation.conversation_id
    assert assistant.get(conversation_id).current_stage is ConversationStage.START

    assistant.send(conversation_id, "Storm damage.")
    assistant.send(conversation_id, "Marama Whitcombe")

    assert assistant.get(conversation_id).current_stage in {
        ConversationStage.CUSTOMER_INFORMATION,
        ConversationStage.POLICY_INFORMATION,
    }


def test_missing_fields_is_derived_not_stored(assistant):
    """Two callers, one answer. A stored list can disagree with reality."""
    assert missing_fields({}) == list(REQUIRED_FIELDS)
    assert missing_fields({name: "x" for name in REQUIRED_FIELDS}) == []
