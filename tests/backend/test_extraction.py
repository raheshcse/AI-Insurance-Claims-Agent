"""Regression tests for the multi-field extraction defect.

=============================================================================
THE DEFECT

    "My name is John Smith, my email is john@example.com, my phone is
     0211234567, and my policy number is POL-HOME-20117."

The whole sentence was handed to `validate_full_name`. That validator checks
length and "contains a letter", so at 116 characters it PASSED and the
customer's name became the entire message. One character longer and it failed
instead, with "That name is longer than our system can accept" -- which is the
symptom that got reported, and the less dangerous of the two outcomes.

Two causes, and both are covered here:

    1. `validate_node` passed the RAW MESSAGE to the asked-about field's
       validator, with nothing checking that the message was a bare answer.
    2. Multi-field extraction had exactly one implementation -- the LLM -- so
       with the stub, a denial, a violation or an outage there was no extraction
       at all and cause (1) was reached on every multi-fact message.

=============================================================================
WHAT THESE TESTS ARE CAREFUL ABOUT

**No validator was weakened and no limit was raised.** Several tests below
assert that directly, because "make the test pass" and "fix the bug" have very
different-looking solutions here and the wrong one is easier.

**The provider is the STUB throughout section 1.** Every extraction asserted
there happens with no model involved, which is the point: understanding several
facts in one sentence is now a property of the system rather than a capability
of whichever provider is configured.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from conversation.extraction import bare_answer, extract
from conversation.fields import FIELDS_BY_NAME, validate_full_name
from tests.backend.conftest_phase5 import extraction

TEST_1 = (
    "My name is John Smith, my email is john@example.com, my phone is "
    "0211234567, and my policy number is POL-HOME-20117."
)


def _yesterday() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _collected(turn) -> dict[str, object]:
    return {item.field: item.value for item in turn.conversation.collected_information}


def _opened(assistant):
    """A conversation past the opening turn, so a field has actually been asked."""
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report some storm damage.")
    return conversation_id


# =========================================================================
# 1. The eight reported cases, end to end, with NO model
# =========================================================================


def test_1_four_fields_from_one_message(assistant, provider):
    """The reported case. Four fields, correctly separated."""
    conversation_id = _opened(assistant)
    before = provider.calls

    turn = assistant.send(conversation_id, TEST_1)

    collected = _collected(turn)
    assert collected["full_name"] == "John Smith"
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert collected["policy_number"] == "POL-HOME-20117"

    # And emphatically NOT the old behaviour.
    assert collected["full_name"] != TEST_1
    assert len(collected["full_name"]) < 30

    # The model contributed nothing here -- the stub returns no JSON. Extraction
    # is the system's, not the provider's.
    assert provider.calls == before + 1, "the governed call still happened"
    assert turn.governance["llm_called"] is True


def test_1_then_asks_for_the_next_missing_field(assistant):
    """After extracting, the assistant moves on rather than re-asking."""
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, TEST_1)

    missing = [item.field for item in turn.conversation.missing_information]
    assert "full_name" not in missing
    assert "email" not in missing
    assert "phone" not in missing
    assert "policy_number" not in missing

    # The reply asks for whatever is now first outstanding, from the catalogue.
    assert FIELDS_BY_NAME[missing[0]].question in turn.reply


def test_2_only_the_field_that_was_stated(assistant):
    """"My name is John Smith." fills the name and nothing else."""
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, "My name is John Smith.")

    collected = _collected(turn)
    assert collected["full_name"] == "John Smith"
    assert "email" not in collected
    assert "phone" not in collected
    assert "policy_number" not in collected


def test_3_two_fields_neither_of_them_the_one_asked_about(assistant):
    """Email and phone, while the assistant was asking for a name.

    The name is NOT invented from the leftovers -- there are none.
    """
    conversation_id = _opened(assistant)

    turn = assistant.send(
        conversation_id, "My email is john@example.com and my phone is 0211234567."
    )

    collected = _collected(turn)
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert "full_name" not in collected, "nothing in that sentence is a name"


def test_4_policy_incident_and_damage_from_one_sentence(assistant):
    """"I have policy POL-HOME-20117 and the storm damaged my roof yesterday." """
    conversation_id = _opened(assistant)

    turn = assistant.send(
        conversation_id,
        "I have policy POL-HOME-20117 and the storm damaged my roof yesterday.",
    )

    collected = _collected(turn)
    assert collected["policy_number"] == "POL-HOME-20117"
    assert collected["date_of_loss"] == _yesterday()
    # `collected_information` is the rendered view -- a list of areas is shown
    # as "Roof", not as ["Roof"]. The raw value is asserted in the extractor
    # tests below.
    assert collected["damaged_areas"] == "Roof"
    # The sentence fragment left behind is not anybody's name.
    assert "full_name" not in collected


def test_5_shape_identifies_a_value_position_does_not(assistant):
    """"John Smith, john@example.com, 0211234567" — a bare comma list.

    Email and phone are identified by SHAPE: nothing else looks like them. The
    name is not, because any text could be a name. What is left over is offered
    to the field the assistant actually asked about -- an inference the design
    supports, because we know what we asked -- and never to a field nobody
    asked about.
    """
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, "John Smith, john@example.com, 0211234567")

    collected = _collected(turn)
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert collected["full_name"] == "John Smith", "the residual answers the question asked"


def test_5_a_bare_list_does_not_fill_a_field_nobody_asked_about(assistant):
    """The other half of TEST 5, and the one that would be a real defect.

    Same message, but the assistant is asking about the SUBURB. The residual
    "John Smith" must not become a suburb merely because it was left over --
    and the validators cannot catch this, because "John Smith" is a perfectly
    well-formed suburb. Position must not imply meaning.
    """
    from conversation.extraction import extract as read

    message = "John Smith, john@example.com, 0211234567"
    found = read(message)

    # Shape-identified values only. No name, no suburb, no guess.
    assert set(found.proposed) == {"email", "phone"}
    assert "full_name" not in found.proposed
    assert "suburb" not in found.proposed

    # The residual is offered to the caller, which knows what it asked. The
    # extractor itself never assigns it.
    assert found.residual == "John Smith"


def test_6_ambiguity_becomes_uncertain_never_a_value(assistant):
    """Vague input produces uncertain/missing state, not a fabricated value."""
    conversation_id = _opened(assistant)

    turn = assistant.send(
        conversation_id,
        "It happened sometime last week and the damage is maybe a few thousand.",
    )

    collected = _collected(turn)
    assert "date_of_loss" not in collected, "a range is not a date"
    assert "estimated_damage_value" not in collected, "'a few thousand' is not an amount"

    uncertain = {item.field for item in turn.conversation.uncertain_information}
    assert "date_of_loss" in uncertain
    missing = {item.field for item in turn.conversation.missing_information}
    assert "date_of_loss" in missing


@pytest.mark.parametrize(
    "message, field_name",
    [
        ("My email is not-an-email", "email"),
        ("My email is john@@example..", "email"),
        ("My phone is 12", "phone"),
        ("My policy number is X", "policy_number"),
        ("My postcode is 60", "postcode"),
    ],
)
def test_7_deterministic_validation_still_rejects_bad_values(
    assistant, message, field_name
):
    """Extraction decides WHICH field. Validation decides whether it is usable.

    A labelled value the customer supplied is still run through the same
    validator, and a bad one is still refused. Extraction is not a way round
    validation and this is the test that says so.
    """
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, message)

    assert field_name not in _collected(turn)
    assert field_name in {item.field for item in turn.conversation.missing_information}


def test_8_a_bare_single_field_reply_still_works(assistant):
    """The original behaviour, unchanged.

    When nothing is identifiable, the residual IS the whole message and the
    path behaves exactly as it did before extraction existed.
    """
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, "Marama Whitcombe")

    assert _collected(turn)["full_name"] == "Marama Whitcombe"


def test_8_a_whole_conversation_still_completes_one_answer_at_a_time(
    assistant, complete_conversation, assistant_claims
):
    """The end-to-end journey, still reaching a real claim."""
    conversation_id = complete_conversation()

    created = assistant.confirm(conversation_id)

    assert created.claim_id.startswith("CLM-")
    assert assistant_claims.get(created.claim_id) is not None


# =========================================================================
# 2. No validation workaround was introduced
# =========================================================================


def test_the_name_length_limit_was_not_raised(assistant):
    """The tempting wrong fix, refused explicitly.

    Raising the limit would have made the reported message "work" while storing
    a whole sentence as someone's name. The limit is unchanged, and a genuinely
    over-long name is still refused.
    """
    value, reason = validate_full_name("x" * 121)

    assert value is None
    assert reason, "an over-long name is still rejected"
    assert validate_full_name("x" * 120)[0] is not None, "120 is still the boundary"


def test_the_raw_message_never_reaches_the_asked_about_validator(assistant):
    """The root cause, asserted against the source.

    `validate_node` must validate the RESIDUAL. If someone re-introduces
    `spec.validate(message)` the original defect is back, and an end-to-end test
    would only catch it for the particular sentences it happens to try.
    """
    import graph.conversation_graph as graph_module

    source = inspect.getsource(graph_module.validate_node)

    assert "spec.validate(residual)" in source
    assert "spec.validate(message)" not in source


def test_extraction_only_proposes_and_never_writes_state(assistant):
    """The module has no way to mutate a conversation.

    Asserted structurally: it does not import the conversation state at all, so
    "the LLM cannot directly mutate conversation state" is not weakened by the
    thing that reads the LLM's message.
    """
    import conversation.extraction as extraction_module

    source = inspect.getsource(extraction_module)

    assert "ConversationState" not in source
    assert "conversation.record" not in source
    assert ".record(" not in source


def test_every_proposal_goes_through_the_catalogue_validators(assistant):
    """Deterministic and model proposals take the SAME route.

    A second acceptance path for pattern-matched values would be a validation
    bypass wearing a helpful name.
    """
    import graph.conversation_graph as graph_module

    source = inspect.getsource(graph_module.validate_node)

    assert source.count("spec.validate(") == 3, (
        "exactly three call sites: the residual, the merged proposals, and the "
        "uncertain check -- and no fourth that accepts a value without asking"
    )


# =========================================================================
# 3. The extractor's own rules
# =========================================================================


def test_a_dot_inside_a_token_does_not_end_the_value():
    """The first version of the clause-end rule truncated john@example.com."""
    found = extract("My email is john@example.com.")

    assert found.proposed["email"] == "john@example.com"


def test_a_policy_number_does_not_swallow_the_rest_of_the_sentence():
    """An earlier pattern matched hyphen-or-space segments under IGNORECASE, so
    "POL-HOME-20117 and the storm damaged my roof" matched in full."""
    found = extract("I have policy POL-HOME-20117 and the storm damaged my roof.")

    assert found.proposed["policy_number"] == "POL-HOME-20117"
    assert found.proposed["damaged_areas"] == ["Roof"]


def test_connective_debris_is_never_offered_as_an_answer():
    """After removing four labelled clauses, "and" is what is left. It is not
    a suburb, and most validators would happily accept it as one."""
    found = extract(TEST_1)

    assert bare_answer(found, TEST_1, asked_about="suburb") is None


def test_a_fragment_that_still_names_a_field_is_not_an_answer():
    found = extract("I have policy POL-HOME-20117 and the storm damaged my roof.")

    assert bare_answer(found, "…", asked_about="full_name") is None


def test_a_relative_date_is_resolved_only_when_it_names_one_day():
    assert extract("The storm was yesterday.").proposed["date_of_loss"] == _yesterday()
    assert "date_of_loss" not in extract("It was sometime last week.").proposed
    assert extract("It was sometime last week.").uncertain["date_of_loss"]


def test_areas_are_recognised_never_invented():
    assert extract("The roof and the ceiling are damaged.").proposed["damaged_areas"] == [
        "Roof",
        "Ceiling",
    ]
    assert "damaged_areas" not in extract("Something got wet.").proposed


def test_an_empty_message_extracts_nothing_and_does_not_raise():
    found = extract("")

    assert found.proposed == {}
    assert found.uncertain == {}
    assert bare_answer(found, "") is None


# =========================================================================
# 4. The VSL architecture is untouched
# =========================================================================


def test_a_pre_node_denial_still_makes_zero_model_calls(assistant, provider):
    """PRESERVED PROOF. The count is the evidence, as before."""
    conversation_id = _opened(assistant)
    before = provider.calls

    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.governance["pre_node_denied"] is True
    assert turn.governance["llm_called"] is False
    assert provider.calls == before, "THE MODEL MUST NOT HAVE BEEN CALLED"


def test_deterministic_extraction_still_runs_when_the_pre_node_denies(
    assistant, provider
):
    """A denial costs the model's reading, not the system's.

    This is NOT a bypass of VSL. VSL governs the Gemini call -- a commitment
    point, because it sends data to a third party and cannot be taken back.
    Matching a regex against a string the customer already typed sends nothing
    anywhere and was never a commitment point. The deterministic path ran
    unconditionally before this fix too; it is simply better at its job now.
    """
    conversation_id = _opened(assistant)

    long_message = (
        "My email is john@example.com. " + ("I am typing a great deal more. " * 60)
    )
    turn = assistant.send(conversation_id, long_message)

    assert turn.governance["pre_node_denied"] is True
    assert turn.governance["llm_called"] is False
    assert _collected(turn)["email"] == "john@example.com"


def test_rejected_model_output_is_never_written_into_conversation_state(
    assistant, provider
):
    """PRESERVED PROOF. The Invariant stage still blocks the output.

    The model invents a policy number the customer never said. INV-05 rejects
    the whole generated output, and none of it reaches authoritative state.
    """
    conversation_id = _opened(assistant)
    # Set AFTER opening. Arranged before, the violation fires on the opening
    # turn, the conversation is suspended, and the turn under test is blocked
    # by the TerminalState instead -- correct behaviour, wrong test.
    provider.reply = extraction({"policy_number": "POL-HOME-99999"})

    turn = assistant.send(conversation_id, "My roof is damaged.")

    assert turn.governance["llm_called"] is True, "the Invariant judges real output"
    assert turn.governance["output_accepted"] is False
    assert turn.governance["invariant_violated"] == "no-fabricated-claim-values"
    assert "policy_number" not in _collected(turn)


def test_a_deterministic_value_is_not_a_route_round_the_invariant(assistant, provider):
    """The fix must not have opened a side door.

    The model proposes a fabricated policy number AND the customer's message
    contains a real one. The Invariant rejects the model's whole output; the
    customer's own value still stands, because it came from their message and
    never went near the model. What must NOT happen is the model's number
    surviving on the deterministic path's coat-tails.
    """
    conversation_id = _opened(assistant)
    provider.reply = extraction({"policy_number": "POL-HOME-99999"})

    turn = assistant.send(conversation_id, "My policy number is POL-HOME-20117.")

    collected = _collected(turn)
    assert collected["policy_number"] == "POL-HOME-20117", "the customer's own value"
    assert collected["policy_number"] != "POL-HOME-99999"
    assert turn.governance["output_accepted"] is False


def test_the_deterministic_reader_cannot_reach_the_model_or_the_gate(assistant):
    """Extraction is business logic. It has no provider and no gate.

    If it could call either, the ordering the architecture fixes -- PreNode,
    then Gemini, then Invariant -- would have a second, ungoverned entrance.
    """
    import conversation.extraction as extraction_module

    source = inspect.getsource(extraction_module)

    for forbidden in (
        "govern_",
        "LLMProvider",
        "narrate",
        "gemini",
        "httpx",
        "GEMINI_API_KEY",
    ):
        assert forbidden not in source, f"extraction must not reference {forbidden}"


def test_the_gate_ordering_is_unchanged_by_this_fix(assistant):
    """PreNode before the call, Invariant after it, one way out. Still true."""
    from governance.gates import govern_conversation_extraction

    source = inspect.getsource(govern_conversation_extraction)

    assert source.index("await extraction_gate(") < source.index("result = perform()")
    assert source.index("result = perform()") < source.index(
        "await generated_output_gates["
    )
    assert source.count("perform()") == 1
    assert source.count("return outcome, result") == 1


def test_inv_02_is_still_at_the_automated_action_commitment_point(assistant):
    """Untouched by this fix, and re-asserted because it is the thing that
    would be quietly broken by a careless edit to the governance layer."""
    from governance.gates import govern_automated_route

    performed: list[str] = []
    outcome, _ = asyncio.run(
        govern_automated_route(
            {
                "claim_id": "CLM-EXTRACTION-42K",
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

    assert outcome.invariant_violated == "automated-authority-limit"
    assert outcome.automated_action_allowed is False
    assert performed == []


# =========================================================================
# 5. The real Gemini provider, end to end
#
# These use `GeminiLLMProvider` itself with an httpx MockTransport, so every
# layer above the socket is the production path: the real provider, the real
# gate, the real graph, the real validators. The transport counts calls, which
# is the only evidence that distinguishes "never called" from "called and
# ignored".
# =========================================================================


def _gemini_assistant(handler):
    """An assistant wired to the REAL Gemini provider over a mock transport."""
    import httpx

    from agents.conversation import ConversationAgent
    from app.repositories.claim_repository import InMemoryClaimRepository
    from app.services.assistant_service import AssistantService
    from app.services.claim_service import ClaimService
    from conversation.store import InMemoryConversationRepository
    from graph.conversation_graph import build_conversation_graph
    from llm.gemini_provider import GeminiLLMProvider

    provider = GeminiLLMProvider(
        api_key="AIzaSyTEST-not-a-real-key-000000000000",
        transport=httpx.MockTransport(handler),
    )
    return AssistantService(
        conversations=InMemoryConversationRepository(),
        claims=ClaimService(InMemoryClaimRepository()),
        graph=build_conversation_graph(agent=ConversationAgent(provider)),
    )


def _faithful_gemini(calls: dict):
    """A model that reports only what the message actually contains.

    A mock that returns the same canned answer whatever it is sent is not a
    model, it is a fabricator -- and INV-05 correctly rejects it, which makes
    every later assertion a test of the suspension path instead of the thing
    under test.
    """
    import json as _json

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        body = _json.loads(request.content)
        calls.setdefault("bodies", []).append(body)
        text = body["input"]
        found = {
            name: value
            for name, value in (
                ("full_name", "John Smith"),
                ("email", "john@example.com"),
                ("phone", "0211234567"),
                ("policy_number", "POL-HOME-20117"),
            )
            if value in text
        }
        return httpx.Response(
            200,
            json={
                "id": "int_test",
                "model": body["model"],
                "status": "completed",
                "output_text": _json.dumps({"extracted": found, "uncertain": {}}),
            },
        )

    return handler


TEST_12 = (
    "My name is John Smith, my email is john@example.com, my phone number is "
    "0211234567, and my policy number is POL-HOME-20117."
)


def test_a_live_gemini_conversation_reports_gemini_and_not_degraded():
    """The brief's §12, with the real provider on the path."""
    calls: dict = {}
    assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(conversation_id, TEST_12)

    governance = turn.governance
    assert governance["provider_selected"] == "gemini"
    assert governance["provider"] == "gemini"
    assert governance["model"] == "gemini-3.8-flash"
    assert governance["request_succeeded"] is True
    assert governance["degraded"] is False
    assert governance["degraded_reason"] is None
    assert governance["output_accepted"] is True
    assert governance["invariant_violated"] is None

    collected = _collected(turn)
    assert collected["full_name"] == "John Smith"
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert collected["policy_number"] == "POL-HOME-20117"

    missing = [item.field for item in turn.conversation.missing_information]
    assert FIELDS_BY_NAME[missing[0]].question in turn.reply


def test_the_gemini_call_count_is_one_for_an_allowed_request():
    """§10. One governed turn, one request on the wire."""
    calls: dict = {}
    assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")
    before = calls["n"]

    assistant.send(conversation_id, TEST_12)

    assert calls["n"] - before == 1


def test_the_gemini_call_count_is_zero_for_a_denied_pre_node():
    """§10, and the evidence that governance really precedes the call."""
    calls: dict = {}
    assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")
    before = calls["n"]

    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.governance["pre_node_denied"] is True
    assert turn.governance["llm_called"] is False
    assert calls["n"] - before == 0, "NO REQUEST MAY REACH GEMINI ON A DENIAL"


def test_the_governed_request_asks_gemini_for_structured_output():
    """The extraction call carries a schema rather than hoping for JSON."""
    calls: dict = {}
    assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id = assistant.start().conversation.conversation_id

    assistant.send(conversation_id, "I need to report storm damage.")

    body = calls["bodies"][-1]
    assert body["response_format"]["mime_type"] == "application/json"
    assert "extracted" in body["response_format"]["schema"]["properties"]
    assert body["model"] == "gemini-3.8-flash"


def test_a_denied_turn_still_says_which_provider_was_selected():
    """"We did not call Gemini because governance said no" and "we did not
    call Gemini because none is configured" are different facts."""
    calls: dict = {}
    assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.governance["provider_selected"] == "gemini"
    assert turn.governance["request_succeeded"] is False
    assert turn.governance["degraded"] is False, "nothing fell back; governance declined"


def test_a_failing_gemini_is_never_reported_as_a_choice_of_stub():
    """§7. The report the brief explicitly forbids.

    With LLM_PROVIDER=gemini and a refused key, the turn must say gemini,
    request_succeeded=false and name the reason -- never "provider: stub".
    """
    import httpx

    assistant = _gemini_assistant(
        lambda request: httpx.Response(401, json={"error": {"message": "…"}})
    )
    conversation_id = assistant.start().conversation.conversation_id

    turn = assistant.send(conversation_id, "My name is John Smith.")

    governance = turn.governance
    assert governance["provider_selected"] == "gemini"
    assert governance["provider"] == "gemini", "NOT stub"
    assert governance["request_succeeded"] is False
    assert governance["degraded"] is True
    assert governance["degraded_reason"] == "auth_rejected_401_403"
    assert governance["http_status"] == 401

    # And the conversation still works, on the deterministic path.
    assert _collected(turn)["full_name"] == "John Smith"


# =========================================================================
# 6. The paragraph that stalled the assistant
#
# Reported from the real UI: with the assistant asking for the street address,
# this paragraph produced NO state change, so the same question came back. The
# customer sent it twice and got the same question twice.
#
# Two defects, both covered below:
#
#   1. `_residual_carries_a_label` matched the BARE label word anywhere in the
#      residual. The paragraph says "I estimate the total repair cost", and
#      "estimate" is a label word -- so the whole paragraph was refused, the
#      asked-about field was never filled, and the loop was infinite.
#
#   2. Even with the guard fixed, deterministic extraction could not read an
#      address, a NZD figure, or any of the explicit safety statements. Its
#      documented rules are meant to cover exactly this shape of value.
# =========================================================================

PARAGRAPH = (
    "The damaged property is at 20B Cornwall Park Avenue in Epsom, Auckland 1023. "
    "The storm happened last night and caused damage to the roof and ceiling. "
    "The house is currently unsafe to live in because water is coming through the "
    "ceiling. Nobody was hurt, but the water is still coming in. We had to make "
    "some emergency repairs to prevent further damage, and we will need temporary "
    "accommodation because we can't stay in the house. I have taken photographs of "
    "the damage, and I estimate the total repair cost will be around NZD 7,500."
)


def _at_address_question(assistant):
    """Drive a conversation to the street-address question, as the UI did."""
    conversation_id = assistant.start().conversation.conversation_id
    for message in (
        "I need to report storm damage.",
        "Marama Whitcombe",
        "m.whitcombe@example.invalid",
        "+64 20 900 0142",
        "POL-HOME-20117",
        "Overnight storm tore tiles off the roof and water came through the ceiling.",
    ):
        turn = assistant.send(conversation_id, message)
    return conversation_id, turn


def test_1_the_full_paragraph_updates_state(assistant):
    """REGRESSION 1. The reported bug: the paragraph produced no state change."""
    conversation_id, before = _at_address_question(assistant)
    collected_before = len(before.conversation.collected_information)

    turn = assistant.send(conversation_id, PARAGRAPH)

    assert len(turn.conversation.collected_information) > collected_before, (
        "the paragraph must change state"
    )


def test_2_address_suburb_city_and_postcode_are_separated(assistant):
    """REGRESSION 2. The four parts of the address, each in its own field.

    They are read as one construction because that is the only thing that makes
    them identifiable: "Epsom" is a suburb because it sits between a street and
    a city, and "1023" is a postcode because it follows one.
    """
    conversation_id, _ = _at_address_question(assistant)

    turn = assistant.send(conversation_id, PARAGRAPH)

    collected = _collected(turn)
    assert collected["address_line_1"] == "20B Cornwall Park Avenue"
    assert collected["suburb"] == "Epsom"
    assert collected["city"] == "Auckland", "the brief's minimum bar"
    assert collected["postcode"] == "1023"


def test_3_many_remaining_fields_come_from_one_message(assistant):
    """REGRESSION 3. Every explicit statement the customer made."""
    conversation_id, _ = _at_address_question(assistant)

    turn = assistant.send(conversation_id, PARAGRAPH)

    collected = _collected(turn)
    assert collected["damaged_areas"] == "Roof, Ceiling"
    assert collected["estimated_damage_value"] == "NZD 7,500"
    assert collected["property_habitable"] == "No", "'unsafe to live in'"
    assert collected["anyone_injured"] == "No", "'Nobody was hurt'"
    assert collected["damage_ongoing"] == "Yes", "'the water is still coming in'"
    assert collected["emergency_repairs_done"] == "Yes", "'emergency repairs'"
    assert collected["photos_supplied"] == "Yes", "'I have taken photographs'"
    assert collected["temporary_accommodation_needed"] == "Yes", (
        "'we will need temporary accommodation' -- stated, not inferred"
    )
    assert collected["date_of_loss"] == _yesterday(), "'last night'"


def test_4_the_paragraph_works_with_no_model_at_all(assistant, provider):
    """REGRESSION 4. Gemini unavailable.

    The `assistant` fixture's provider returns no usable JSON, so every field
    below came from patterns. Understanding this paragraph is a property of the
    system, not of the provider.
    """
    conversation_id, _ = _at_address_question(assistant)

    turn = assistant.send(conversation_id, PARAGRAPH)

    collected = _collected(turn)
    assert collected["address_line_1"] == "20B Cornwall Park Avenue"
    assert collected["city"] == "Auckland"
    assert collected["postcode"] == "1023"


def test_5_the_paragraph_works_when_gemini_answers(assistant):
    """REGRESSION 5. With a real structured extraction on top."""
    import json as _json

    import httpx

    def gemini(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gemini-3.8-flash",
                "output_text": _json.dumps(
                    {
                        "extracted": {"incident_description": PARAGRAPH},
                        "uncertain": {},
                    }
                ),
            },
        )

    gemini_assistant = _gemini_assistant(gemini)
    conversation_id, _ = _at_address_question(gemini_assistant)

    turn = gemini_assistant.send(conversation_id, PARAGRAPH)

    collected = _collected(turn)
    assert collected["address_line_1"] == "20B Cornwall Park Avenue"
    assert turn.governance["provider_selected"] == "gemini"
    assert turn.governance["request_succeeded"] is True
    assert turn.governance["degraded"] is False


def test_6_an_empty_model_answer_does_not_discard_deterministic_extraction(assistant):
    """REGRESSION 6. The merge must not let an empty proposal win.

    A model that returns `{"extracted": {}}` is saying "I found nothing", not
    "there is nothing". Deterministic extraction stands on its own.
    """
    import httpx

    empty = _gemini_assistant(
        lambda request: httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": '{"extracted": {}, "uncertain": {}}',
            },
        )
    )
    conversation_id, _ = _at_address_question(empty)

    turn = empty.send(conversation_id, PARAGRAPH)

    collected = _collected(turn)
    assert collected["address_line_1"] == "20B Cornwall Park Avenue"
    assert collected["city"] == "Auckland"
    assert turn.governance["request_succeeded"] is True


def test_7_the_same_message_twice_does_not_repeat_the_same_question(assistant):
    """REGRESSION 7. The symptom the customer actually experienced."""
    conversation_id, _ = _at_address_question(assistant)

    first = assistant.send(conversation_id, PARAGRAPH)
    second = assistant.send(conversation_id, PARAGRAPH)

    assert "street address" not in first.reply.lower()
    assert "street address" not in second.reply.lower()
    assert first.reply != second.reply, "the conversation must have moved on"


def test_7_a_supplied_value_is_never_asked_for_again(assistant):
    conversation_id, _ = _at_address_question(assistant)

    turn = assistant.send(conversation_id, PARAGRAPH)

    still_missing = {item.field for item in turn.conversation.missing_information}
    for supplied in ("address_line_1", "suburb", "city", "postcode"):
        assert supplied not in still_missing


def test_8_the_earlier_multi_field_case_still_works(assistant):
    """REGRESSION 8. The previous fix, unharmed."""
    conversation_id = _opened(assistant)

    turn = assistant.send(conversation_id, TEST_1)

    collected = _collected(turn)
    assert collected["full_name"] == "John Smith"
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert collected["policy_number"] == "POL-HOME-20117"
    assert collected["full_name"] != TEST_1


def test_9_a_pre_node_denial_still_makes_zero_gemini_calls_on_this_paragraph():
    """REGRESSION 9. Governance before the model, with the real provider."""
    calls: dict = {}
    gemini_assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id, _ = _at_address_question(gemini_assistant)
    before = calls["n"]

    turn = gemini_assistant.send(conversation_id, "words " * 300)

    assert turn.governance["pre_node_denied"] is True
    assert calls["n"] - before == 0, "NO REQUEST MAY REACH GEMINI ON A DENIAL"


def test_9_a_denied_paragraph_is_still_understood_deterministically():
    """A denial costs the model's reading, not the system's.

    The paragraph is long enough to be denied by PN-02 on its own, and the
    address still lands -- from patterns, with no model call.
    """
    calls: dict = {}
    gemini_assistant = _gemini_assistant(_faithful_gemini(calls))
    conversation_id, _ = _at_address_question(gemini_assistant)
    before = calls["n"]

    long_paragraph = PARAGRAPH + " " + ("I will add more detail here. " * 60)
    turn = gemini_assistant.send(conversation_id, long_paragraph)

    assert turn.governance["pre_node_denied"] is True
    assert calls["n"] - before == 0
    assert _collected(turn)["address_line_1"] == "20B Cornwall Park Avenue"


def test_10_an_invariant_violation_still_blocks_rejected_output():
    """REGRESSION 10. The Invariant stage, unchanged by any of this."""
    import httpx

    import json as _json

    def fabricate_on_the_turn_under_test(request: httpx.Request) -> httpx.Response:
        # Only on the message being tested. Fabricating on the OPENING turn
        # suspends the conversation, and the turn under test is then blocked by
        # the TerminalState instead -- correct behaviour, wrong test.
        body = _json.loads(request.content)
        extracted = (
            {"policy_number": "POL-HOME-99999"}
            if "The roof is damaged" in body["input"]
            else {}
        )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": _json.dumps({"extracted": extracted, "uncertain": {}}),
            },
        )

    hostile = _gemini_assistant(fabricate_on_the_turn_under_test)
    conversation_id = hostile.start().conversation.conversation_id
    hostile.send(conversation_id, "I need to report storm damage.")

    turn = hostile.send(conversation_id, "The roof is damaged.")

    assert turn.governance["llm_called"] is True
    assert turn.governance["output_accepted"] is False
    assert turn.governance["invariant_violated"] == "no-fabricated-claim-values"
    assert "policy_number" not in _collected(turn)


# =========================================================================
# 7. The extractor's new rules, and the limits on them
# =========================================================================


def test_a_street_needs_a_street_type_to_be_an_address():
    """The suffix is the whole basis for calling it an address."""
    assert extract("I live at 20B Cornwall Park Avenue").proposed["address_line_1"]
    assert "address_line_1" not in extract("There were 15 broken tiles").proposed
    assert "address_line_1" not in extract("20 people were there").proposed


def test_nzd_is_recognised_without_a_dollar_sign():
    """The project writes NZD everywhere; the pattern required `$`."""
    for text, expected in (
        ("around NZD 7,500", "NZD 7,500"),
        ("about $7,500", "$7,500"),
        ("roughly NZ$7500", "NZ$7500"),
        ("about 7500 dollars", "7500 dollars"),
    ):
        assert extract(text).proposed["estimated_damage_value"] == expected


def test_only_explicit_accommodation_statements_count():
    """The brief's own example of what must NOT be inferred.

    Being unable to stay somewhere and needing the insurer to house you are
    different facts, and only the second belongs on a claim.
    """
    stated = extract("we will need temporary accommodation because of the damage")
    assert stated.proposed["temporary_accommodation_needed"] is True

    inferred = extract("The house is unsafe and we're staying with my sister.")
    assert "temporary_accommodation_needed" not in inferred.proposed


def test_a_negated_phrase_is_declined_rather_than_reversed():
    """"We do not need accommodation" must not read as needing it."""
    assert (
        extract("we do not need accommodation").proposed.get(
            "temporary_accommodation_needed"
        )
        is not True
    )


def test_prose_is_never_offered_as_a_short_answer():
    """The discriminator: words plus grammar is prose; words alone is a value."""
    from conversation.extraction import _looks_like_a_bare_answer

    assert _looks_like_a_bare_answer("John Smith")
    assert _looks_like_a_bare_answer("20B Cornwall Park Avenue")
    assert _looks_like_a_bare_answer("roof and ceiling")
    assert _looks_like_a_bare_answer("0604")

    assert not _looks_like_a_bare_answer("I have policy and the storm damaged my roof")
    assert not _looks_like_a_bare_answer(PARAGRAPH)


def test_a_free_text_field_receives_the_customers_own_words(assistant):
    """`incident_description` gets the message, not the residual.

    The residual has the address and date cut out of it, which produced
    "damaged property is at . The storm happened and caused damage to..." --
    not what the customer wrote, and not something a reviewer should read.
    """
    conversation_id, _ = _at_address_question(assistant)
    assistant.send(conversation_id, PARAGRAPH)

    turn = assistant.send(conversation_id, PARAGRAPH)

    description = _collected(turn)["incident_description"]
    assert description.startswith("The damaged property is at 20B Cornwall Park Avenue")
    assert "20B Cornwall Park Avenue" in description
    assert "NZD 7,500" in description
