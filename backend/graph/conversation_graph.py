"""The conversational StateGraph.

One customer message in, one assistant reply out, through LangGraph -- not
through a chatbot loop bolted on beside it. The orchestration framework for this
project is LangGraph, and a conversation that orchestrated itself would be a
second orchestrator with its own bugs and no trace.

    START
      -> understand          governed model call: PreNode -> Gemini -> Invariant
      -> validate            deterministic; the ONLY writer of collected values
      -> detect_missing      derived from the catalogue
      -> respond             the next question, the summary, or the confirmation
      -> END

Each node reads the shared state and writes only its own slot, exactly as the
claims graph does. `understand` is the only node that can touch a model, and it
cannot touch the conversation state; `validate` is the only node that can write
a collected value, and it cannot touch a model. That separation is what makes
"the model proposes, the application decides" a property of the graph rather
than a convention in a docstring.

WHY A GRAPH FOR FOUR NODES

Because the alternative is a function that does all four things and can be
edited into doing them in the wrong order. Here, `validate` cannot run before
`understand`, and `respond` cannot run before `detect_missing`, because the
edges say so and the compiled graph enforces it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.conversation import ConversationAgent
from conversation import extraction as deterministic
from conversation.builder import summary_text
from conversation.contracts import ConversationStage, ConversationState
from conversation.fields import (
    FIELDS_BY_NAME,
    missing_fields,
    next_field,
    progress,
    stage_for,
)
from governance.gates import govern_conversation_extraction

logger = logging.getLogger("claims.conversation")


def _merge(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


def _append(left: list | None, right: list | None) -> list:
    return [*(left or []), *(right or [])]


class ConversationTurnState(TypedDict, total=False):
    """State for ONE turn. The conversation itself lives in `ConversationState`.

    A turn is a unit of work over a conversation, the way an analysis is a unit
    of work over a claim. Keeping them apart means a turn can fail without
    corrupting the conversation.
    """

    # -- inputs
    conversation_id: str
    message: str
    state: ConversationState
    asked_about: str | None

    # -- understand
    proposed: Annotated[dict[str, Any], _merge]
    """Everything proposed this turn, from BOTH sources. NOT yet a fact --
    `validate` decides that, and it is the only thing that can."""
    proposed_uncertain: Annotated[dict[str, Any], _merge]
    deterministic_fields: list[str]
    """Which proposals came from pattern reading rather than from the model.
    Published so a reviewer can tell the two apart in the trace."""
    residual: str | None
    """What was left of the message after the identifiable values were removed.

    This is what `validate` offers to the field the assistant actually asked
    about -- NOT the raw message. Handing the raw message to a validator is the
    defect this field exists to prevent."""
    governance: dict[str, Any]

    # -- validate
    accepted: Annotated[dict[str, Any], _merge]
    rejected: Annotated[dict[str, Any], _merge]

    # -- detect_missing
    missing: list[str]
    claim_ready: bool

    # -- respond
    reply: str
    stage: str

    trace: Annotated[list[dict[str, Any]], _append]


# ---------------------------------------------------------------------------
# 1. understand -- the ONLY node that may reach a model.
# ---------------------------------------------------------------------------


def understand_node(agent: ConversationAgent, *, confidence: float = 0.9):
    """Governed extraction.

    `confidence` is what the PreNode's Gamma evaluation judges. It is a property
    of the TURN, not of the model: a short reply to a direct question is a
    confident interpretation; a long free-form message answering nothing in
    particular is not. `_turn_confidence` below derives it deterministically, so
    the gate is never asked to trust a number the model supplied about itself.
    """

    def run(state: ConversationTurnState) -> dict[str, Any]:
        message = state.get("message") or ""
        conversation = state["state"]
        asked_about = state.get("asked_about")
        known = sorted(conversation.collected_information)

        # -- (i) DETERMINISTIC READING, always, before and regardless of the
        #        model. Patterns, no network, no key, no gate -- reading a
        #        sentence for structure is not a commitment to anything.
        #
        #        This runs unconditionally so that multi-field understanding is
        #        a property of the SYSTEM rather than a capability of whichever
        #        provider happens to be configured. A PreNode denial, an
        #        Invariant violation, a missing key or an outage now costs the
        #        model's reading of meaning, not the ability to understand
        #        "my email is x and my phone is y".
        read = deterministic.extract(message)
        residual = deterministic.bare_answer(read, message, asked_about=asked_about)

        request = agent.build_request(message, asked_about=asked_about, known=known)

        # WHY INV-04 IS NOT EVALUATED HERE.
        #
        # `no-customer-data-egress` governs CP-13, where the system composes a
        # narration payload out of a stored claim and could leak a policyholder
        # detail the customer never chose to send. This commitment is different:
        # the payload IS the sentence the customer just typed, deliberately, in
        # order to be understood. Running INV-04 against it would suspend
        # automation the moment someone typed their own name -- an Invariant
        # firing on correct traffic, which is how a governance layer gets
        # switched off.
        #
        # So the candidate carries only what this gate's rules actually judge.
        # A field nobody evaluates would imply a check that is not happening,
        # which is worse than no check at all.
        candidate = {
            "conversation_id": conversation.conversation_id,
            "claim_id": conversation.claim_id,
            "confidence": _turn_confidence(message, asked_about),
            "source_text": message,
        }

        outcome, result = asyncio.run(
            govern_conversation_extraction(
                candidate,
                # Handed IN. The gate calls it after the PreNode, or not at all.
                perform=lambda: agent.extract(request),
                # How the gate turns the result into what the Invariants judge.
                inspect=agent.inspect,
            )
        )

        governance = {
            "gate": outcome.gate,
            "action": outcome.action,
            # Which provider CONFIGURATION selected. Reported on every path,
            # including the denied ones: "we never called Gemini because the
            # PreNode said no" and "we never called Gemini because none is
            # configured" are different facts and a reader needs to tell them
            # apart without inferring it from a missing key.
            "provider_selected": agent.provider_name,
            "pre_node": outcome.pre_node,
            "pre_node_denied": outcome.pre_node_denied,
            "llm_called": outcome.llm_called,
            "output_accepted": outcome.output_accepted,
            "invariant_violated": outcome.invariant_violated,
            "terminal_state": outcome.terminal_state,
            "confidence": outcome.confidence,
            "confidence_floor": outcome.confidence_floor,
            "gamma_threshold": outcome.gamma_threshold,
            "assurance_level": outcome.assurance_level,
            "decision_id": outcome.decision_id,
            "specification": outcome.specification,
            "ledger_entry_ids": list(outcome.ledger_entry_ids),
            "reason": outcome.reason or outcome.denial_reason,
        }

        if result is None:
            # Denied before the call, or the output was rejected after it.
            # The model contributes nothing to this turn -- but the
            # deterministic reading still stands, because it never depended on
            # the model and governance has no quarrel with a regex.
            #
            # Note what is NOT here: no fabricated value, and no second attempt
            # at the model. A denial is an answer.
            # The call did not happen, so it did not succeed -- and it did not
            # "degrade" either: nothing fell back, governance declined.
            governance["request_succeeded"] = False
            governance["degraded"] = False
            return {
                "proposed": dict(read.proposed),
                "proposed_uncertain": dict(read.uncertain),
                "deterministic_fields": list(read.proposed),
                "residual": residual,
                "governance": governance,
                "trace": [
                    {
                        "node": "understand",
                        "llm_called": outcome.llm_called,
                        "deterministic_fields": list(read.proposed),
                    }
                ],
            }

        inspected = agent.inspect(result)

        # THREE FACTS, NEVER COLLAPSED INTO ONE.
        #
        #   provider_selected    what configuration chose        (gemini)
        #   request_succeeded    whether that provider answered  (true/false)
        #   degraded             whether the fallback wrote this (true/false)
        #
        # Reporting only the first is how "provider: stub" gets read as a
        # deliberate choice when it is actually a broken key. Reporting only the
        # third says something failed without saying what. A reader needs all
        # three and they are published separately.
        degraded = bool(getattr(result, "degraded", False))
        governance["provider"] = getattr(result, "provider", None)
        governance["model"] = getattr(result, "model", None)
        governance["request_succeeded"] = not degraded
        governance["degraded"] = degraded
        governance["degraded_reason"] = getattr(result, "degraded_reason", None)
        governance["http_status"] = getattr(result, "http_status", None)

        # -- (ii) MERGE. The model fills what the patterns could not identify;
        #         the patterns win where both spoke.
        #
        #         Deterministic first, then model, so `dict.update` cannot
        #         overwrite it. A pattern that matched `john@example.com` is
        #         certain by construction; a model proposing a different address
        #         for the same message has either misread it or invented it, and
        #         neither is a reason to prefer the model.
        #
        #         The model is still doing the job only it can do: reading a
        #         fact stated in a way no pattern anticipated.
        proposed: dict[str, Any] = {}
        for name, value in (inspected["extracted"] or {}).items():
            proposed[name] = value
        proposed.update(read.proposed)

        # Uncertainty merges the OTHER way round, and deliberately so. Its
        # content is never a claim value -- it is the customer's own words,
        # quoted back to them in the follow-up question. The model quotes more
        # usefully ("sometime last week" rather than the bare phrase a pattern
        # matched), and nothing downstream reads it as a fact.
        uncertain: dict[str, Any] = dict(read.uncertain)
        uncertain.update(inspected["uncertain"] or {})
        # Anything the patterns pinned down is not uncertain, whatever the
        # model thought.
        for name in read.proposed:
            uncertain.pop(name, None)

        return {
            "proposed": proposed,
            "proposed_uncertain": uncertain,
            "deterministic_fields": list(read.proposed),
            "residual": residual,
            "governance": governance,
            "trace": [
                {
                    "node": "understand",
                    "llm_called": True,
                    "deterministic_fields": list(read.proposed),
                    "model_fields": sorted(inspected["extracted"] or {}),
                }
            ],
        }

    return run


def _turn_confidence(message: str, asked_about: str | None) -> float:
    """How confident we are that automated interpretation of this turn is warranted.

    Deterministic and deliberately simple, because a confidence the model scored
    itself is not evidence. A direct reply to a direct question is the easy
    case; an unprompted wall of text is the one worth stopping on.

    The floor PN-02 enforces is 0.8148 at the default 0.80 boundary, so the
    bands below are chosen to sit clearly either side of it rather than to
    hover on it.
    """
    words = len((message or "").split())
    if not words:
        return 0.5
    if asked_about and words <= 40:
        return 0.95
    if words <= 80:
        return 0.88
    if words <= 160:
        return 0.84
    return 0.6


# ---------------------------------------------------------------------------
# 2. validate -- deterministic, and the ONLY writer of collected values.
# ---------------------------------------------------------------------------


def validate_node(state: ConversationTurnState) -> dict[str, Any]:
    """Accept, reject or defer every proposed value.

    No model is reachable from here. A proposal that fails its validator is
    dropped and recorded as rejected, with the validator's own sentence, which
    the responder then uses to ask a better question.
    """
    conversation = state["state"]
    message = state.get("message") or ""
    accepted: dict[str, Any] = {}
    rejected: dict[str, str] = {}

    # (a) The answer to the question we actually asked.
    #
    #     THE RESIDUAL, NOT THE RAW MESSAGE. This is the fix for the defect
    #     this path used to have: it passed the whole message to the validator
    #     for whichever field had just been asked about, so
    #
    #         "My name is John Smith, my email is john@example.com, my phone
    #          is 0211234567, and my policy number is POL-HOME-20117."
    #
    #     was handed to `validate_full_name`. That validator checks length and
    #     "contains a letter", and at 116 characters the whole sentence PASSED
    #     as the customer's name. A slightly longer one failed instead, with
    #     "That name is longer than our system can accept" -- the same bug
    #     wearing a different face.
    #
    #     `conversation/extraction.py` now removes everything it can identify
    #     and hands back what is left, or None when what is left is debris, a
    #     sentence fragment, or a field the extraction already claimed. No
    #     validator was changed and no limit was raised: the input reaching them
    #     is simply the right input.
    asked_about = state.get("asked_about")
    residual = state.get("residual")
    if asked_about and residual and residual.strip():
        spec = FIELDS_BY_NAME.get(asked_about)
        if spec is not None and conversation.value(asked_about) is None:
            value, reason = spec.validate(residual)
            if value is not None:
                conversation.record(asked_about, value, source_text=message)
                conversation.clear_uncertain(asked_about)
                accepted[asked_about] = value
            else:
                rejected[asked_about] = reason or "That did not look right."

    # (b) Every proposal -- deterministic and model alike -- through the SAME
    #     validators. Neither source is trusted; both are checked. This loop is
    #     the only thing in the system that can write a collected value.
    for name, raw in (state.get("proposed") or {}).items():
        spec = FIELDS_BY_NAME.get(name)
        if spec is None or name in accepted:
            continue
        value, reason = spec.validate(raw)
        if value is None:
            rejected.setdefault(name, reason or "That did not look right.")
            continue
        if conversation.value(name) is not None and name != asked_about:
            # Already known and not the field under discussion. A model
            # re-proposing a value the customer confirmed earlier must not be
            # able to overwrite it -- that is how a quietly changed date of loss
            # happens.
            continue
        conversation.record(name, value, source_text=message)
        conversation.clear_uncertain(name)
        accepted[name] = value

    # (c) Anything the customer raised but could not pin down.
    for name, said in (state.get("proposed_uncertain") or {}).items():
        if name in accepted or conversation.value(name) is not None:
            continue
        spec = FIELDS_BY_NAME.get(name)
        if spec is None:
            continue
        _, reason = spec.validate(said)
        conversation.flag_uncertain(
            name, said=str(said), why=reason or "This needs to be exact."
        )

    return {
        "accepted": accepted,
        "rejected": rejected,
        "trace": [{"node": "validate", "accepted": sorted(accepted)}],
    }


# ---------------------------------------------------------------------------
# 3. detect_missing -- derived, never remembered.
# ---------------------------------------------------------------------------


def detect_missing_node(state: ConversationTurnState) -> dict[str, Any]:
    conversation = state["state"]
    values = conversation.values()
    missing = missing_fields(values)
    ready = not missing

    conversation.missing_information = missing
    conversation.claim_ready = ready
    conversation.current_stage = stage_for(values, confirmed=conversation.customer_confirmed)

    return {
        "missing": missing,
        "claim_ready": ready,
        "stage": conversation.current_stage.value,
        "trace": [{"node": "detect_missing", "missing": len(missing)}],
    }


# ---------------------------------------------------------------------------
# 4. respond -- what the assistant says.
# ---------------------------------------------------------------------------

_ACK_FIRST = (
    "I'm sorry to hear that. I can help you report the damage and collect the "
    "information we need for your claim."
)


def respond_node(state: ConversationTurnState) -> dict[str, Any]:
    """Compose the reply deterministically.

    The assistant's words are assembled from the validators' own sentences and
    the catalogue's questions -- not generated. Two reasons, and the second is
    the load-bearing one:

    1. A generated question can drift from what the catalogue actually needs,
       and then the progress indicator and the conversation disagree.
    2. A generated reply is model output reaching a customer, which would need
       its own governed call and its own Invariant pass on every turn. The
       information the assistant conveys is already decided; generating it would
       add commitment-point surface for no gain.

    The model's contribution is understanding the customer, which is where it
    is genuinely better than a rule.
    """
    conversation = state["state"]
    rejected = state.get("rejected") or {}
    accepted = state.get("accepted") or {}
    missing = state.get("missing") or []
    first_turn = len([m for m in conversation.messages if m.role == "assistant"]) == 0

    parts: list[str] = []

    if first_turn:
        parts.append(_ACK_FIRST)
    elif accepted:
        parts.append("Thank you.")

    # Something the customer said could not be accepted -- say why, once.
    if rejected:
        parts.append(next(iter(rejected.values())))
        pending = next_field(conversation.values())
        reply = " ".join(parts)
        return _reply(conversation, reply, pending)

    # Something was mentioned but not pinned down.
    unresolved = [
        item
        for item in conversation.uncertain_information
        if item.field in missing
    ]
    if unresolved:
        item = unresolved[0]
        parts.append(f'You mentioned "{item.said}". {item.why}')
        reply = " ".join(parts)
        return _reply(conversation, reply, FIELDS_BY_NAME.get(item.field))

    if not missing:
        # Everything is in. Show the summary and ask for explicit confirmation.
        parts.append(
            "I think I have everything I need. Here is what I will submit."
        )
        reply = " ".join(parts) + "\n\n" + summary_text(conversation)
        conversation.current_stage = ConversationStage.READY_FOR_CONFIRMATION
        conversation.last_asked = None
        return {
            "reply": reply,
            "stage": conversation.current_stage.value,
            "trace": [{"node": "respond", "kind": "summary"}],
        }

    pending = next_field(conversation.values())
    have, total = progress(conversation.values())
    if pending is not None and not first_turn and not accepted and have == 0:
        parts.append("Let's start with the basics.")
    reply = " ".join(parts)
    return _reply(conversation, reply, pending)


def _reply(conversation: ConversationState, prefix: str, pending: Any) -> dict[str, Any]:
    question = pending.question if pending is not None else ""
    text = " ".join(part for part in (prefix, question) if part).strip()
    # Record what we ASKED, so the next turn's deterministic path knows which
    # field a bare reply belongs to. See ConversationState.last_asked.
    conversation.last_asked = getattr(pending, "name", None) if question else None
    conversation.current_stage = stage_for(
        conversation.values(), confirmed=conversation.customer_confirmed
    )
    return {
        "reply": text,
        "stage": conversation.current_stage.value,
        "trace": [{"node": "respond", "asked_about": conversation.last_asked},],
    }


# ---------------------------------------------------------------------------
# The graph.
# ---------------------------------------------------------------------------


def build_conversation_graph(*, agent: ConversationAgent) -> Any:
    graph = StateGraph(ConversationTurnState)

    graph.add_node("understand", understand_node(agent))
    graph.add_node("validate", validate_node)
    graph.add_node("detect_missing", detect_missing_node)
    graph.add_node("respond", respond_node)

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "validate")
    graph.add_edge("validate", "detect_missing")
    graph.add_edge("detect_missing", "respond")
    graph.add_edge("respond", END)

    return graph.compile()
