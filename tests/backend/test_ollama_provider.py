"""Ollama — a local model behind the same provider boundary.

=============================================================================
WHY THESE TESTS LOOK LIKE THE GEMINI ONES

Because the point of the abstraction is that they should. Ollama is a second
provider, not a second architecture: the same `narrate()`, the same
`NarrationResult`, the same failure vocabulary, the same VSL gate above it.
Anywhere these tests had to say something Gemini's do not, that is a real
difference and it is commented.

=============================================================================
NO TEST HERE NEEDS A RUNNING SERVER

`httpx.MockTransport` intercepts at the transport layer, so the real
`httpx.Request` is still built and can be asserted -- which is the useful part:
it proves the bytes that WOULD go to localhost:11434 are the right bytes,
without requiring Ollama to be installed on whatever machine runs the suite.

The call counts below are measured at that transport, not by checking whether a
function was referenced. "Never called" and "called and ignored" produce
identical results everywhere except in that number.
"""

from __future__ import annotations

import json

import httpx
import pytest

from llm.base import DegradedReason, LLMProvider, NarrationRequest
from llm.factory import get_llm_provider
from llm.gemini_provider import GeminiLLMProvider
from llm.ollama_provider import DEFAULT_BASE_URL, DEFAULT_MODEL, OllamaLLMProvider
from llm.stub import StubLLMProvider

REQUEST = NarrationRequest(
    purpose="claim intake summary",
    facts={"headline": "Storm damage covering Roof", "points": ["Photos supplied."]},
    max_words=60,
)


def _answering(text: str, calls: dict | None = None):
    """A transport that behaves like a healthy Ollama."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls["n"] = calls.get("n", 0) + 1
            calls.setdefault("bodies", []).append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": DEFAULT_MODEL,
                "response": text,
                "done": True,
                "total_duration": 1_000_000,
            },
        )

    return handler


def _provider(handler, **kwargs) -> OllamaLLMProvider:
    return OllamaLLMProvider(transport=httpx.MockTransport(handler), **kwargs)


# =========================================================================
# 1-3. The factory chooses, and nothing else does
# =========================================================================


def test_1_the_factory_selects_ollama():
    provider = get_llm_provider("ollama")

    assert isinstance(provider, OllamaLLMProvider)
    assert provider.name == "ollama"
    assert isinstance(provider, LLMProvider), "it must satisfy the existing protocol"


def test_1_local_is_an_accepted_alias():
    assert isinstance(get_llm_provider("local"), OllamaLLMProvider)


def test_2_the_factory_still_selects_gemini():
    provider = get_llm_provider("gemini")

    assert isinstance(provider, GeminiLLMProvider)
    assert provider.name == "gemini"


def test_3_the_factory_still_selects_the_stub():
    assert isinstance(get_llm_provider("stub"), StubLLMProvider)
    assert isinstance(get_llm_provider("definitely-not-a-provider"), StubLLMProvider)


def test_provider_selection_lives_in_exactly_one_place():
    """No agent, graph node or governance module may choose a provider.

    Adding Ollama required no change to any of them, and this is what keeps
    that true: a second selection site is a second thing to keep in step.
    """
    import inspect

    import agents.conversation as conversation_agent
    import governance.gates as gates
    import graph.conversation_graph as graph_module

    for module in (conversation_agent, graph_module, gates):
        source = inspect.getsource(module)
        assert "OllamaLLMProvider" not in source
        assert "GeminiLLMProvider" not in source
        assert "11434" not in source, "no provider networking outside llm/"
        assert "httpx" not in source, "no provider HTTP outside llm/"


# =========================================================================
# 4. A successful request
# =========================================================================


def test_4_a_successful_request_returns_the_generated_text():
    provider = _provider(_answering("The roof was damaged in a storm."))

    result = provider.narrate(REQUEST)

    assert result.text == "The roof was damaged in a storm."
    assert result.provider == "ollama"
    assert result.model == DEFAULT_MODEL
    assert result.degraded is False
    assert result.degraded_reason is None


def test_4_the_request_matches_ollamas_documented_api():
    """POST /api/generate with model, system, prompt, stream=false, options.

    Verified against Ollama's own `docs/api.md`.
    """
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = "authorization" in request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _provider(capture).narrate(REQUEST)

    assert seen["method"] == "POST"
    assert seen["url"] == f"{DEFAULT_BASE_URL}/api/generate"
    assert seen["auth"] is False, "a local server authenticates nothing"
    body = seen["body"]
    assert body["model"] == DEFAULT_MODEL
    assert isinstance(body["prompt"], str)
    assert isinstance(body["system"], str)
    assert body["options"]["temperature"] == 0.0


def test_4_streaming_is_explicitly_disabled():
    """`stream` defaults to TRUE and a streamed body is NDJSON.

    Forgetting this does not fail loudly -- it returns something that will not
    parse, which would surface as `response_not_json` and send someone looking
    for a proxy that is not there.
    """
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "ok"})

    _provider(capture).narrate(REQUEST)

    assert seen["stream"] is False


def test_4_the_base_url_and_model_come_from_configuration():
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"response": "ok"})

    provider = _provider(capture, base_url="http://10.0.0.5:9999", model="qwen3:4b")
    provider.narrate(REQUEST)

    assert seen["url"] == "http://10.0.0.5:9999/api/generate"
    assert seen["model"] == "qwen3:4b"


# =========================================================================
# 5-7. Failure, named precisely
# =========================================================================


def test_5_a_connection_failure_says_so():
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = _provider(refuse).narrate(REQUEST)

    assert result.degraded is True
    assert result.degraded_reason == DegradedReason.CONNECTION_FAILED
    assert result.http_status is None, "nothing answered, so there is no status"


def test_6_a_timeout_says_so():
    def hang(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    result = _provider(hang).narrate(REQUEST)

    assert result.degraded_reason == DegradedReason.TIMEOUT


def test_7_a_missing_model_is_not_a_missing_endpoint():
    """The one place Ollama's taxonomy differs from a hosted API's, on purpose.

    A 404 from a server that plainly answered does not mean "wrong endpoint" --
    it means the model has not been pulled, and the fix is one command rather
    than a configuration hunt.
    """
    def missing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})

    result = _provider(missing).narrate(REQUEST)

    assert result.degraded_reason == DegradedReason.MODEL_NOT_FOUND
    assert result.degraded_reason != DegradedReason.NOT_FOUND
    assert result.http_status == 404


def test_a_streamed_body_is_reported_as_unparseable_not_as_success():
    def ndjson(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"response":"a"}\n{"response":"b"}\n')

    assert _provider(ndjson).narrate(REQUEST).degraded_reason == (
        DegradedReason.INVALID_JSON
    )


def test_an_empty_response_is_not_treated_as_an_answer():
    assert _provider(_answering("")).narrate(REQUEST).degraded_reason == (
        DegradedReason.EMPTY_RESPONSE
    )


def test_a_server_error_is_the_servers_problem():
    def broken(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "…"})

    assert _provider(broken).narrate(REQUEST).degraded_reason == (
        DegradedReason.PROVIDER_ERROR
    )


def test_narrate_never_raises_whatever_happens():
    """The contract every provider owes the workflow."""

    def chaos(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something nobody anticipated")

    result = _provider(chaos).narrate(REQUEST)

    assert result.degraded is True
    assert result.text, "a degraded result still carries usable prose"


# =========================================================================
# 8. Structured extraction — the SAME contract Gemini uses
# =========================================================================


def test_8_a_response_schema_becomes_ollamas_format_field():
    """The conversation layer sets `response_schema` once.

    Neither provider knows about the other: Gemini turns it into
    `response_format`, Ollama into `format`, and the caller sets one field.
    """
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "{}"})

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    _provider(capture).narrate(
        NarrationRequest(
            purpose="p", facts={"headline": "h"}, max_words=10, response_schema=schema
        )
    )

    assert seen["format"] == schema


def test_8_no_schema_means_no_format_field():
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "prose"})

    _provider(capture).narrate(REQUEST)

    assert "format" not in seen


def test_8_the_extraction_contract_survives_the_round_trip():
    """The assistant's own schema, through Ollama, into the parser.

    `{"extracted": ..., "uncertain": ...}` is the project's contract and it is
    not renegotiated per provider.
    """
    from agents.conversation import EXTRACTION_SCHEMA, ConversationAgent, parse_extraction

    answer = {
        "extracted": {"full_name": "John Smith", "email": "john@example.com"},
        "uncertain": {},
    }
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps(answer)})

    agent = ConversationAgent(_provider(capture))
    result = agent.extract(
        agent.build_request("My name is John Smith.", asked_about="full_name", known=[])
    )

    assert seen["format"] == EXTRACTION_SCHEMA
    assert parse_extraction(result.text)["extracted"] == answer["extracted"]


# =========================================================================
# 9. Provider metadata — selection is not success
# =========================================================================


def test_9_a_success_reports_ollama_succeeded_and_not_degraded():
    result = _provider(_answering("fine")).narrate(REQUEST)

    assert result.provider == "ollama"
    assert result.degraded is False


def test_9_a_failure_still_reports_ollama_never_stub():
    """The rule the brief states explicitly.

    `LLM_PROVIDER=ollama` with the server down must not be reported as
    "provider: stub" -- that reads as a deliberate choice rather than a fault.
    """
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    result = _provider(refuse).narrate(REQUEST)

    assert result.provider == "ollama", "NOT stub"
    assert result.degraded is True
    assert result.degraded_reason == DegradedReason.CONNECTION_FAILED
    assert result.model == DEFAULT_MODEL


def test_9_the_availability_check_distinguishes_down_from_missing_model():
    """Two different problems, two different answers, no inference spent."""
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    ok, why = _provider(down).available()
    assert (ok, why) == (False, DegradedReason.CONNECTION_FAILED)

    def without_the_model(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    ok, why = _provider(without_the_model).available()
    assert (ok, why) == (False, DegradedReason.MODEL_NOT_FOUND)

    def with_the_model(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": DEFAULT_MODEL}]})

    assert _provider(with_the_model).available() == (True, "ok")


def test_ollama_requires_and_reads_no_api_key(monkeypatch):
    """A local endpoint must never be handed a cloud credential."""
    import inspect

    import llm.ollama_provider as module

    # Checked against the QUOTED forms, because code references an environment
    # variable in quotes and prose references it in backticks -- this module's
    # docstring says GEMINI_API_KEY must never be used here, and a bare
    # substring check would fail on its own documentation.
    source = inspect.getsource(module)
    for quoted in ('"GEMINI_API_KEY"', "'GEMINI_API_KEY'",
                   '"OPENAI_API_KEY"', "'OPENAI_API_KEY'",
                   '"Authorization"', "'Authorization'"):
        assert quoted not in source, f"{quoted} must not appear in code"
    assert "api_key" not in source.replace("`", "")

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTEST-not-a-real-key-0000000")
    seen: dict = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"response": "ok"})

    _provider(capture).narrate(REQUEST)

    assert "AIzaSy" not in json.dumps(seen["headers"])
    assert "AIzaSy" not in seen["body"]
    assert _provider(capture).configured is True, "nothing to configure"


# =========================================================================
# 10-13. VSL — unchanged, and re-proven against the Ollama transport
# =========================================================================


def _ollama_assistant(handler):
    """The full assistant, wired to the REAL Ollama provider over a transport."""
    from agents.conversation import ConversationAgent
    from app.repositories.claim_repository import InMemoryClaimRepository
    from app.services.assistant_service import AssistantService
    from app.services.claim_service import ClaimService
    from conversation.store import InMemoryConversationRepository
    from graph.conversation_graph import build_conversation_graph

    return AssistantService(
        conversations=InMemoryConversationRepository(),
        claims=ClaimService(InMemoryClaimRepository()),
        graph=build_conversation_graph(agent=ConversationAgent(_provider(handler))),
    )


def _faithful(calls: dict):
    """A model that reports only what the message contains.

    A mock returning the same canned answer whatever it is sent is a
    fabricator, and INV-05 rejects it -- which would turn every assertion below
    into a test of the suspension path.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        body = json.loads(request.content)
        calls.setdefault("bodies", []).append(body)
        found = {
            name: value
            for name, value in (
                ("full_name", "John Smith"),
                ("email", "john@example.com"),
                ("policy_number", "POL-HOME-20117"),
            )
            if value in body["prompt"]
        }
        return httpx.Response(
            200,
            json={
                "model": DEFAULT_MODEL,
                "response": json.dumps({"extracted": found, "uncertain": {}}),
            },
        )

    return handler


def test_10_a_pre_node_denial_makes_zero_ollama_calls():
    """Measured at the TRANSPORT. Not "was a function referenced"."""
    calls: dict = {}
    assistant = _ollama_assistant(_faithful(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")
    before = calls.get("n", 0)

    turn = assistant.send(conversation_id, "words " * 300)

    assert turn.governance["pre_node_denied"] is True
    assert turn.governance["llm_called"] is False
    assert calls.get("n", 0) - before == 0, "NO REQUEST MAY REACH OLLAMA ON A DENIAL"


def test_11_a_pre_node_allow_makes_exactly_one_ollama_call():
    calls: dict = {}
    assistant = _ollama_assistant(_faithful(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")
    before = calls["n"]

    turn = assistant.send(conversation_id, "My name is John Smith.")

    assert turn.governance["pre_node_denied"] is False
    assert turn.governance["llm_called"] is True
    assert calls["n"] - before == 1


def test_12_ollama_output_passes_through_the_vsl_invariant():
    calls: dict = {}
    assistant = _ollama_assistant(_faithful(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(conversation_id, "My name is John Smith.")

    assert turn.governance["output_accepted"] is True
    assert turn.governance["invariant_violated"] is None
    assert turn.governance["provider_selected"] == "ollama"
    assert turn.governance["provider"] == "ollama"
    assert turn.governance["request_succeeded"] is True
    assert turn.governance["degraded"] is False


def test_13_an_invariant_violation_keeps_ollama_output_out_of_state():
    """A local model is not a trusted model. Same Invariant, same rejection."""
    def fabricate(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        extracted = (
            {"policy_number": "POL-HOME-99999"}
            if "The roof is damaged" in body["prompt"]
            else {}
        )
        return httpx.Response(
            200,
            json={"response": json.dumps({"extracted": extracted, "uncertain": {}})},
        )

    assistant = _ollama_assistant(fabricate)
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(conversation_id, "The roof is damaged.")

    assert turn.governance["llm_called"] is True, "the Invariant judges real output"
    assert turn.governance["output_accepted"] is False
    assert turn.governance["invariant_violated"] == "no-fabricated-claim-values"
    collected = {i.field for i in turn.conversation.collected_information}
    assert "policy_number" not in collected


def test_a_failing_ollama_still_leaves_a_working_assistant():
    """Deterministic extraction never depended on a provider.

    Ollama down costs the model's reading of meaning, not the ability to take
    a claim -- the same property that holds for Gemini.
    """
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no server")

    assistant = _ollama_assistant(down)
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(
        conversation_id,
        "My name is John Smith, my email is john@example.com, my phone is "
        "0211234567, and my policy number is POL-HOME-20117.",
    )

    collected = {i.field: i.value for i in turn.conversation.collected_information}
    assert collected["full_name"] == "John Smith"
    assert collected["email"] == "john@example.com"
    assert collected["policy_number"] == "POL-HOME-20117"

    assert turn.governance["provider_selected"] == "ollama"
    assert turn.governance["request_succeeded"] is False
    assert turn.governance["degraded"] is True
    assert turn.governance["degraded_reason"] == DegradedReason.CONNECTION_FAILED


def test_the_four_field_message_extracts_correctly_through_ollama():
    """The project's standing regression case, with a local model answering."""
    calls: dict = {}
    assistant = _ollama_assistant(_faithful(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(
        conversation_id,
        "My name is John Smith, my email is john@example.com, my phone is "
        "0211234567, and my policy number is POL-HOME-20117.",
    )

    collected = {i.field: i.value for i in turn.conversation.collected_information}
    assert collected["full_name"] == "John Smith"
    assert collected["email"] == "john@example.com"
    assert collected["phone"] == "0211234567"
    assert collected["policy_number"] == "POL-HOME-20117"


def test_the_address_paragraph_extracts_correctly_through_ollama():
    """The other standing regression case."""
    calls: dict = {}
    assistant = _ollama_assistant(_faithful(calls))
    conversation_id = assistant.start().conversation.conversation_id
    assistant.send(conversation_id, "I need to report storm damage.")

    turn = assistant.send(
        conversation_id,
        "The damaged property is at 20B Cornwall Park Avenue in Epsom, Auckland "
        "1023. The house is unsafe, nobody was hurt, water is still coming in, we "
        "had to make emergency repairs, we need temporary accommodation, we have "
        "photographs, and the estimated damage is NZD 7,500.",
    )

    collected = {i.field: i.value for i in turn.conversation.collected_information}
    assert collected["address_line_1"] == "20B Cornwall Park Avenue"
    assert collected["suburb"] == "Epsom"
    assert collected["city"] == "Auckland"
    assert collected["postcode"] == "1023"
    assert collected["estimated_damage_value"] == "NZD 7,500"
    assert collected["property_habitable"] == "No"
    assert collected["anyone_injured"] == "No"
    assert collected["temporary_accommodation_needed"] == "Yes"


def test_no_post_node_was_introduced_by_adding_a_provider():
    """The architecture is frozen; a provider is not an architectural change."""
    from vsl_core import constructs as vsl_constructs

    from governance.policy import ALL_INVARIANTS, ALL_PRE_NODES, ALL_TERMINAL_STATES

    assert not hasattr(vsl_constructs, "PostNode")
    for pre_node in ALL_PRE_NODES:
        assert type(pre_node) is vsl_constructs.PreNode
    for invariant in ALL_INVARIANTS:
        assert type(invariant) is vsl_constructs.Invariant
    for terminal in ALL_TERMINAL_STATES:
        assert type(terminal) is vsl_constructs.TerminalState


def test_the_gate_ordering_is_unchanged_by_adding_a_provider():
    """PreNode before the call, Invariant after it, one way out."""
    import inspect

    from governance.gates import govern_conversation_extraction

    source = inspect.getsource(govern_conversation_extraction)

    assert source.index("await extraction_gate(") < source.index("result = perform()")
    assert source.index("result = perform()") < source.index(
        "await generated_output_gates["
    )
    assert source.count("perform()") == 1
    assert source.count("return outcome, result") == 1
