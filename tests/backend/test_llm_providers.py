"""Phase 4A — the Gemini provider, and the boundary it has to respect.

The integration is easy to get superficially right and quietly wrong, so these
tests are organised around the ways it fails in practice:

    1.  Selection      — does LLM_PROVIDER actually reach the Gemini provider?
    2.  The wire       — is the request Gemini's *current* API, or last year's?
    3.  Failure        — does every failure degrade instead of raising?
    4.  The key        — can it leak into a log, a result, or a stored analysis?
    5.  Determinism    — can the model change a claim decision? (it must not)
    6.  Governance     — does any of this reach VSL? (it must not)

No test here makes a network call. `httpx.MockTransport` intercepts at the
transport layer, so the real `httpx.Request` is still constructed and can be
asserted — which is the point: it proves the bytes that *would* go to Google are
the right bytes, without a key and without the network.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from llm.base import DegradedReason, LLMProvider, NarrationRequest
from llm.factory import get_llm_provider
from llm.gemini_provider import DEFAULT_MODEL, GeminiLLMProvider, _extract_text
from llm.http_provider import HttpChatLLMProvider
from llm.stub import StubLLMProvider

FAKE_KEY = "AIzaSyTEST-not-a-real-key-000000000000000"

REQUEST = NarrationRequest(
    purpose="claim intake summary for a claims employee",
    facts={"headline": "Storm damage claim covering Roof", "points": ["Photos supplied."],
           "caveat": None},
    max_words=60,
)


def _ok_body(text: str = "The customer reports storm damage to the roof.") -> dict:
    """A realistic Interactions API success response."""
    return {
        "id": "interactions/abc123",
        "status": "completed",
        "model": "gemini-3.8-flash",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}],
        "usage": {"total_input_tokens": 120, "total_output_tokens": 18, "total_tokens": 138},
    }


def _provider(handler, **kwargs) -> GeminiLLMProvider:
    return GeminiLLMProvider(
        api_key=kwargs.pop("api_key", FAKE_KEY),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# =========================================================================
# 1. Selection
# =========================================================================


@pytest.mark.parametrize("value", ["gemini", "GEMINI", " gemini ", "google", "google-gemini"])
def test_gemini_is_selectable_through_the_existing_factory(value, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", value)
    assert isinstance(get_llm_provider(), GeminiLLMProvider)


def test_the_stub_is_still_the_default(monkeypatch):
    """A POC that only works with a paid key is a POC nobody can run."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    provider = get_llm_provider()
    assert isinstance(provider, StubLLMProvider)
    assert provider.name == "stub"
    assert provider.model is None


def test_the_openai_compatible_provider_is_untouched(monkeypatch):
    """Phase 4A added a provider; it did not modify the existing one."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert isinstance(get_llm_provider(), HttpChatLLMProvider)


def test_an_unknown_provider_falls_back_loudly_not_silently(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "gemmini")  # a typo, not a provider
    with caplog.at_level(logging.WARNING, logger="claims.llm"):
        provider = get_llm_provider()
    assert isinstance(provider, StubLLMProvider)
    assert any("gemmini" in r.getMessage() for r in caplog.records)


def test_every_provider_satisfies_the_existing_protocol():
    """The abstraction was extended, not replaced."""
    for provider in (StubLLMProvider(), HttpChatLLMProvider(), GeminiLLMProvider()):
        assert isinstance(provider, LLMProvider)
        assert hasattr(provider, "name") and hasattr(provider, "narrate")
        assert hasattr(provider, "model")


def test_narrate_is_still_the_only_method_agents_may_call():
    """If a second method appeared, an agent could ask the model to decide
    something rather than describe it. The protocol's whole safety value is that
    there is nowhere to put such a call."""
    methods = {
        n for n in dir(LLMProvider)
        if not n.startswith("_") and callable(getattr(LLMProvider, n, None))
    }
    assert methods == {"narrate"}

    # Phase 4A added `model` as an annotation only -- additive, no new behaviour.
    assert set(LLMProvider.__annotations__) == {"name", "model"}


# =========================================================================
# 2. The wire — Gemini's current API, not the legacy one
# =========================================================================


def test_the_request_targets_the_interactions_api_with_the_google_auth_header():
    """`generateContent` is legacy and `Authorization: Bearer` is OpenAI's header.
    Getting either wrong produces a 404 or a 401 that degrades silently, so the
    shape is asserted rather than assumed."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    _provider(handler).narrate(REQUEST)

    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert seen["headers"]["x-goog-api-key"] == FAKE_KEY
    assert "authorization" not in seen["headers"]
    assert ":generatecontent" not in seen["url"].lower()


def test_the_request_body_is_the_interactions_shape():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_ok_body())

    _provider(handler, model="gemini-3.8-flash", temperature=0.0).narrate(REQUEST)

    assert seen["model"] == "gemini-3.8-flash"
    assert "system_instruction" in seen and seen["system_instruction"]
    assert isinstance(seen["input"], str) and "Facts:" in seen["input"]
    assert seen["generation_config"]["temperature"] == 0.0
    assert seen["generation_config"]["max_output_tokens"] > 0
    # Not OpenAI's shape.
    assert "messages" not in seen and "max_tokens" not in seen


def test_the_system_instruction_forbids_deciding_a_claim():
    """The prompt is part of the safety story, so it is asserted like code."""
    body = GeminiLLMProvider(api_key=FAKE_KEY).build_request_body(REQUEST)
    instruction = body["system_instruction"].lower()
    assert "never invent" in instruction
    assert "approved, declined, settled or fraudulent" in instruction
    assert "prompts to investigate, never accusations" in instruction


def test_a_successful_response_is_parsed_and_reported_as_live():
    provider = _provider(lambda r: httpx.Response(200, json=_ok_body("Roof damage reported.")))
    result = provider.narrate(REQUEST)

    assert result.text == "Roof damage reported."
    assert result.provider == "gemini"
    assert result.model == "gemini-3.8-flash"
    assert result.degraded is False


def test_text_is_read_from_either_supported_shape():
    assert _extract_text({"output_text": "  convenience field  "}) == "convenience field"
    assert _extract_text(_ok_body("from steps")) == "from steps"
    assert _extract_text(
        {"steps": [{"type": "model_output",
                    "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}]}
    ) == "a b"
    # Tool calls with no text is not a narration.
    assert _extract_text({"steps": [{"type": "tool_call", "content": []}]}) == ""


# =========================================================================
# 3. Failure — every path degrades, none raises
# =========================================================================


def test_a_missing_api_key_is_handled_safely_and_makes_no_request():
    """The most likely misconfiguration. It must not raise, and must not dial out."""
    called = False

    def handler(request):  # pragma: no cover - must never run
        nonlocal called
        called = True
        return httpx.Response(200, json=_ok_body())

    provider = GeminiLLMProvider(api_key="", transport=httpx.MockTransport(handler))
    assert provider.configured is False

    result = provider.narrate(REQUEST)

    assert called is False, "a provider with no key must not attempt a request"
    assert result.degraded is True
    assert result.provider == "gemini"
    assert result.text  # deterministic prose, not an empty string


@pytest.mark.parametrize(
    ("label", "handler"),
    [
        ("401", lambda r: httpx.Response(401, json={"error": {"code": 401, "message": "no"}})),
        ("429", lambda r: httpx.Response(429, json={"error": {"code": 429, "message": "quota"}})),
        ("500", lambda r: httpx.Response(500, text="upstream error")),
        ("not-json", lambda r: httpx.Response(200, text="<html>nope</html>")),
        ("empty-text", lambda r: httpx.Response(200, json=_ok_body(""))),
        ("no-steps", lambda r: httpx.Response(200, json={"status": "completed", "steps": []})),
        ("failed-status", lambda r: httpx.Response(200, json={"status": "failed", "steps": []})),
        ("requires-action", lambda r: httpx.Response(
            200, json={"status": "requires_action", "steps": []})),
    ],
)
def test_every_failure_mode_degrades_rather_than_raising(label, handler):
    result = _provider(handler).narrate(REQUEST)

    assert result.degraded is True, label
    assert result.provider == "gemini"
    assert result.text, "a degraded result must still carry usable prose"


def test_a_timeout_degrades():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    result = _provider(handler).narrate(REQUEST)
    assert result.degraded is True
    assert result.text


def test_a_truncated_response_still_yields_its_text():
    """`incomplete` means the token limit was hit. The prose so far is usable, and
    narration is decorative anyway — discarding it would lose information for no
    safety gain."""
    body = _ok_body("The customer reports storm damage to the")
    body["status"] = "incomplete"
    result = _provider(lambda r: httpx.Response(200, json=body)).narrate(REQUEST)

    assert result.degraded is False
    assert result.text.endswith("the")


def test_a_degraded_result_is_labelled_so_a_reader_can_tell():
    """Silently substituting fallback prose for model prose would be the
    dishonest option. `narrative_source` is how the report shows the difference."""
    from agents.base import ClaimsAgent

    class Probe(ClaimsAgent):
        name = "probe"

        def analyse(self, context):  # pragma: no cover - not used
            raise NotImplementedError

    # narrate() returns (text, source, governance) since the refactor -- the
    # third value is the CP-13 gate decision.
    _, source, gov = Probe(_provider(lambda r: httpx.Response(500))).narrate(
        context={"claim_id": "CLM-DEGRADED-1"}, purpose="p", headline="h", points=["x"]
    )
    assert source == "gemini (degraded)"
    assert gov["llm_called"] is True, "degraded means the call was made and failed"

    _, source, gov = Probe(
        _provider(lambda r: httpx.Response(200, json=_ok_body()))
    ).narrate(context={"claim_id": "CLM-DEGRADED-2"}, purpose="p", headline="h", points=["x"])
    assert source == "gemini"
    assert gov["llm_called"] is True


# =========================================================================
# 4. The key never leaks
# =========================================================================


def test_the_api_key_is_read_from_the_environment_and_never_hard_coded(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert GeminiLLMProvider().configured is True

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiLLMProvider().configured is False

    source = (__import__("pathlib").Path(__file__).resolve().parents[2]
              / "backend" / "llm" / "gemini_provider.py").read_text(encoding="utf-8")
    assert "AIza" not in source, "no key-shaped literal may appear in the provider"


def test_the_key_never_reaches_a_log_line(caplog):
    with caplog.at_level(logging.DEBUG, logger="claims.llm"):
        _provider(lambda r: httpx.Response(401, json={"error": {"message": FAKE_KEY}})).narrate(
            REQUEST
        )

    blob = " ".join(r.getMessage() for r in caplog.records)
    assert FAKE_KEY not in blob
    assert "gemini" in blob.lower()  # something *was* logged


def test_the_key_never_reaches_a_narration_result():
    for handler in (
        lambda r: httpx.Response(200, json=_ok_body()),
        lambda r: httpx.Response(401),
    ):
        result = _provider(handler).narrate(REQUEST)
        assert FAKE_KEY not in json.dumps(result.__dict__, default=str)


# =========================================================================
# 5. The model cannot change a claim decision
# =========================================================================


def _decisions(result: dict) -> dict:
    """Every value a claim decision turns on. None of these may vary by provider."""
    return {
        "routing_outcome": (result.get("routing") or {}).get("outcome"),
        "recommended_next_step": result["recommended_next_step"],
        "recommended_claim_state": result.get("recommended_claim_state"),
        "priority": (result.get("routing") or {}).get("priority"),
        "reason_codes": sorted(
            r["code"] for r in (result.get("routing") or {}).get("reasons") or []
        ),
        "complexity": (result.get("damage_assessment") or {}).get("complexity_band"),
        "urgency": (result.get("damage_assessment") or {}).get("urgency_band"),
        "value_band": (result.get("damage_assessment") or {}).get("value_band"),
        "risk_level": (result.get("risk_assessment") or {}).get("risk_level"),
        "cover_certainty": ((result.get("policy_assessment") or {}).get("interpretation") or {})
        .get("cover_certainty"),
        "confidence": (result.get("overall_confidence") or {}).get("value"),
        "governance_gate": (result.get("governance_gate") or {}).get("outcome"),
    }


@pytest.mark.parametrize(
    ("label", "handler"),
    [
        ("gemini answering", lambda r: httpx.Response(
            200, json=_ok_body("An entirely different narrative, invented by the model."))),
        ("gemini failing", lambda r: httpx.Response(500)),
    ],
)
def test_the_provider_changes_the_prose_and_nothing_else(
    label, handler, submitted_claim, reference_data, thresholds
):
    """The claim this whole layer rests on, checked across every decision field.

    A model that could move a band, a reason code or a routing outcome would be
    making an insurance decision. It cannot: those values are rule-derived before
    `narrate()` is ever called."""
    from conftest_phase2 import run_graph

    from graph.builder import build_claims_graph

    def build(provider):
        return run_graph(
            build_claims_graph(
                llm=provider, reference_data=reference_data, thresholds=thresholds
            ),
            submitted_claim,
        )["intelligence"]

    baseline = build(StubLLMProvider())
    with_gemini = build(_provider(handler))

    assert _decisions(with_gemini) == _decisions(baseline), label

    # And the prose genuinely did change on the live path, or this proves nothing.
    if label == "gemini answering":
        assert with_gemini["agent_results"]["intake"]["narrative"] != (
            baseline["agent_results"]["intake"]["narrative"]
        )
        assert with_gemini["agent_results"]["intake"]["narrative_source"] == "gemini"


def test_a_gemini_outage_never_produces_an_automation_friendly_outcome(
    claim_factory, reference_data, thresholds
):
    """Fail closed. An unreachable model must not read as 'nothing to worry about'."""
    from conftest_phase2 import run_graph

    from graph.builder import build_claims_graph

    result = run_graph(
        build_claims_graph(
            llm=_provider(lambda r: httpx.Response(503)),
            reference_data=reference_data,
            thresholds=thresholds,
        ),
        claim_factory(photos=False),
    )["intelligence"]

    assert result["recommended_next_step"] == "information_required"
    assert result["is_recommendation_only"] is True
    assert result["action_taken"] == "none"


# =========================================================================
# 6. None of this reaches the rules or the governance layer
# =========================================================================


def test_neither_routing_nor_governance_imports_any_llm_module():
    """Structural, not a promise. If an import appeared here, a model could start
    influencing a routing decision or a governance candidate."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for folder in ("backend/routing", "governance"):
        for path in (root / folder).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    roots = {(node.module or "").split(".")[0]}
                else:
                    continue
                assert "llm" not in roots, f"{path.name} imports an LLM module"
                assert "agents" not in roots, f"{path.name} imports an agent"


def test_the_governance_candidate_carries_no_model_output():
    """What the gates evaluate is facts, not prose."""
    import app.services.review_service as rs

    claim = {"claim_id": "CLM-X"}
    intelligence = {
        "routing": {"outcome": "AUTOMATED_PATH_RECOMMENDED"},
        "overall_confidence": {"value": 0.9},
        "policy_assessment": {"interpretation": {
            "in_force_at_date_of_loss": True, "peril_covered": True,
            "exclusions_possibly_engaged": [], "cover_certainty": "clear"}},
        "damage_assessment": {"estimated_claim_value": 3200},
        "agent_results": {"intake": {"narrative": "PROSE-THAT-MUST-NOT-TRAVEL"}},
        "llm_provider": "gemini",
    }

    candidate = rs._governance_candidate(claim, intelligence)

    assert "PROSE-THAT-MUST-NOT-TRAVEL" not in json.dumps(candidate)
    assert set(candidate) == {
        "claim_id", "confidence", "automated_route_proposed", "policy_in_force_at_loss",
        "peril_covered", "estimated_claim_value", "exclusions_possibly_engaged",
        "cover_certainty",
    }


# =========================================================================
# 7. The analysis result publishes what actually answered
# =========================================================================


def test_the_analysis_result_reports_provider_model_and_degraded(
    review_client, valid_fnol, monkeypatch
):
    """Without this, "we integrated Gemini" is unfalsifiable from the output."""
    client, _, _ = review_client
    claim_id = client.post("/api/claims", json=valid_fnol).json()["claim_id"]

    body = client.post(f"/api/claims/{claim_id}/analyze").json()

    assert body["llm_provider"] == "stub"
    assert body["llm_model"] is None
    assert body["llm_degraded"] is False
    assert FAKE_KEY not in json.dumps(body)


def test_degraded_is_reported_when_the_fallback_wrote_the_narrative():
    from app.services.intelligence_service import _any_narration_degraded

    assert _any_narration_degraded(
        {"agent_results": {"intake": {"narrative_source": "gemini"},
                           "policy": {"narrative_source": "gemini (degraded)"}}}
    ) is True
    assert _any_narration_degraded(
        {"agent_results": {"intake": {"narrative_source": "gemini"}}}
    ) is False
    assert _any_narration_degraded({"agent_results": {}}) is False


# =========================================================================
# 8. The verification CLI tells the truth
# =========================================================================


def test_the_verify_cli_reports_stub_and_does_not_claim_a_live_call(monkeypatch, capsys):
    from llm.verify_cli import EXIT_FALLBACK, main

    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert main(["--provider", "stub"]) == EXIT_FALLBACK

    out = capsys.readouterr().out
    assert "STUB" in out and "no call was made" in out


def test_the_verify_cli_never_prints_the_key(monkeypatch, capsys):
    from llm.verify_cli import main

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    main(["--provider", "gemini", "--json"])

    out = capsys.readouterr().out
    assert FAKE_KEY not in out
    payload = json.loads(out)
    assert payload["api_key"]["configured"] is True
    assert payload["api_key"]["length"] == len(FAKE_KEY)
    assert payload["provider"] == "gemini"
    assert payload["model"] == DEFAULT_MODEL


# =========================================================================
# 9. `.env` actually reaches the process
#
# The bug these guard: python-dotenv was a declared dependency from Phase 1 and
# `load_dotenv()` was never called. Every module reads os.environ directly, so a
# correct `.env` was invisible and the factory silently returned the stub. No
# error, no warning -- the default is a legitimate configuration.
# =========================================================================


def test_a_dotenv_file_reaches_the_provider_selection(tmp_path, monkeypatch):
    import bootstrap

    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=gemini\nGEMINI_API_KEY=AIzaSyDOTENV-test-only-0000\n", encoding="utf-8"
    )
    monkeypatch.setattr(bootstrap, "DOTENV_PATH", env)
    monkeypatch.setattr(bootstrap, "_loaded", False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    provider = get_llm_provider()

    assert isinstance(provider, GeminiLLMProvider), (
        "a configured .env must select Gemini, not fall through to the stub"
    )
    assert provider.configured is True


def test_an_exported_variable_beats_the_dotenv_file(tmp_path, monkeypatch):
    """`override=False`. A one-off run and CI must not be silently reconfigured
    by a developer's file."""
    import bootstrap

    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=gemini\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "DOTENV_PATH", env)
    monkeypatch.setattr(bootstrap, "_loaded", False)
    monkeypatch.setenv("LLM_PROVIDER", "stub")

    assert isinstance(get_llm_provider(), StubLLMProvider)


def test_a_missing_dotenv_is_not_an_error(tmp_path, monkeypatch):
    """Every setting has a working default; that is what lets the POC run with
    no configuration at all."""
    import bootstrap

    monkeypatch.setattr(bootstrap, "DOTENV_PATH", tmp_path / "nope.env")
    monkeypatch.setattr(bootstrap, "_loaded", False)

    assert bootstrap.load_project_env() is False


def test_secrets_are_masked_never_shown():
    from bootstrap import mask_secret

    assert mask_secret("AIzaSyEXAMPLE-key-value-wxyz") == "****wxyz"
    assert mask_secret(None) == "(not set)"
    assert mask_secret("") == "(not set)"
    assert "AIzaSy" not in mask_secret("AIzaSyEXAMPLE-key-value-wxyz")


def test_the_diagnostic_reports_configured_true_without_the_key(monkeypatch, capsys):
    from llm.verify_cli import main

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    main(["--provider", "gemini", "--json"])

    out = capsys.readouterr().out
    assert FAKE_KEY not in out
    payload = json.loads(out)
    assert payload["api_key"]["configured"] is True
    assert payload["api_key"]["masked"] == f"****{FAKE_KEY[-4:]}"
    assert FAKE_KEY[:10] not in out


# ---------------------------------------------------------------------------
# 10. A degraded result has to say WHY.
#
# The bug that started this work looked like "provider: stub" and nothing else.
# The provider now reports a reason code on every fallback path, so a reader can
# tell a missing key from an unreachable endpoint from a filtered response --
# without any of those codes carrying a credential, a URL or an exception string.
# ---------------------------------------------------------------------------


def test_a_missing_key_says_so_instead_of_just_degrading(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiLLMProvider(api_key="")

    result = provider.narrate(REQUEST)

    assert result.degraded is True
    assert result.degraded_reason == DegradedReason.NOT_CONFIGURED
    # And it still reports itself as gemini. Rewriting the provider to "stub"
    # here is what hid the real fault: it made a configuration problem look
    # like a deliberate choice of provider.
    assert result.provider == "gemini"


def test_an_unreachable_endpoint_is_reported_as_a_transport_error():
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = GeminiLLMProvider(
        api_key=FAKE_KEY, transport=httpx.MockTransport(refuse)
    )
    result = provider.narrate(REQUEST)

    assert result.degraded is True
    assert result.degraded_reason == DegradedReason.TRANSPORT_ERROR


def test_a_failed_interaction_status_is_distinguishable_from_a_dead_endpoint():
    def failed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "failed", "steps": []})

    provider = GeminiLLMProvider(
        api_key=FAKE_KEY, transport=httpx.MockTransport(failed)
    )
    result = provider.narrate(REQUEST)

    assert result.degraded_reason == DegradedReason.UNUSABLE_STATUS
    assert result.degraded_reason != DegradedReason.TRANSPORT_ERROR


def test_a_filtered_empty_response_is_its_own_reason():
    def empty(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "steps": []})

    provider = GeminiLLMProvider(api_key=FAKE_KEY, transport=httpx.MockTransport(empty))
    result = provider.narrate(REQUEST)

    assert result.degraded_reason == DegradedReason.EMPTY_RESPONSE


def test_no_reason_code_can_carry_a_credential_or_a_url():
    """The whole point of a fixed vocabulary.

    A reason built from `str(exc)` would eventually carry the request URL, and a
    URL is one careless refactor away from carrying the key as a query parameter.
    """
    codes = [
        value
        for name, value in vars(DegradedReason).items()
        if not name.startswith("_") and isinstance(value, str)
    ]

    assert codes, "DegradedReason must publish at least one code"
    for code in codes:
        assert "://" not in code
        assert "key" not in code or code == DegradedReason.NOT_CONFIGURED
        assert code == code.lower()
        assert " " not in code


def test_a_successful_call_carries_no_reason():
    def ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [
                            {"type": "text", "text": "The roof was damaged in a storm."}
                        ],
                    }
                ],
            },
        )

    provider = GeminiLLMProvider(api_key=FAKE_KEY, transport=httpx.MockTransport(ok))
    result = provider.narrate(REQUEST)

    assert result.degraded is False
    assert result.degraded_reason is None
