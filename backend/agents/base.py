"""Shared agent machinery.

Every agent inherits the same three properties:

1. **It returns a contract, never free text.**
2. **It cannot raise.** `run()` wraps `analyse()`; an exception becomes a FAILED
   result with a customer-safe message. An agent crash must never look like
   permission to act -- see `safe_failure()`.
3. **It narrates through the LLM boundary**, and only after its structured
   result already exists. The prose describes the decision; it never makes it.

=============================================================================
THE LLM CALL IS A GOVERNED COMMITMENT POINT (CP-13)

The X-Verba spec names an LLM call as something code "cannot take back",
alongside a payment and a database write. Before the governance refactor this
was the one commitment in the system that ran ungoverned: all five agents
narrate during the agent nodes, which execute BEFORE `governance_gate` in the
graph, so VSL ran *after* the model rather than before it.

`narrate()` below now reads, in this order:

    agent  ->  govern_llm_narration(...)  ->  provider.narrate(...)

and the provider call is passed IN as a callable. On a denial the gate returns
before ever invoking it: no request is constructed, no socket opened, no API key
read. "Called and then ignored" is not what happens and could not be.

The gate is here rather than inside the provider on purpose. A provider that
gated itself could stop gating itself, and the ordering would be invisible at
the call site — the one place a reviewer actually looks.
=============================================================================
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from agents.contracts import AgentResult, AgentStatus, Confidence
from governance.gates import govern_llm_narration
from llm.base import LLMProvider, NarrationRequest

logger = logging.getLogger("claims.agents")

# Fields on the FNOL that identify a policyholder. INV-04 checks the outbound
# narration payload against the values the claim actually holds, rather than
# guessing at PII with a pattern -- a guessing rule either fires on ordinary
# traffic and gets switched off, or misses the real case and is theatre.
_IDENTIFIER_PATHS: tuple[tuple[str, ...], ...] = (
    ("customer", "full_name"),
    ("customer", "email"),
    ("customer", "phone"),
    ("property", "loss_address", "address_line_1"),
)


def personal_identifiers(claim: dict[str, Any] | None) -> list[str]:
    """Every value for this claim that must not reach a third-party model."""
    fnol = (claim or {}).get("fnol") or {}
    found: list[str] = []
    for path in _IDENTIFIER_PATHS:
        node: Any = fnol
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        if isinstance(node, str) and node.strip():
            found.append(node.strip())
    return found


class ClaimsAgent(ABC):
    """Base class for the five specialist agents."""

    name: str = "agent"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    # -- to implement -----------------------------------------------------

    @abstractmethod
    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        """Produce the structured result. May raise -- `run()` contains it."""

    # -- entry point ------------------------------------------------------

    def run(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        try:
            return self.analyse(context)
        except Exception as exc:  # noqa: BLE001 - an agent must not break the graph
            logger.exception("Agent %s failed", self.name, exc_info=exc)
            return self.safe_failure(exc), None

    # -- helpers ----------------------------------------------------------

    def safe_failure(self, exc: Exception) -> AgentResult:
        """The result an agent returns when it cannot do its job.

        The recommendation on this path always points at a person. A failed
        agent produces no finding, no confidence and no automation-friendly
        outcome -- silence is never read as approval.
        """
        return AgentResult(
            agent=self.name,
            status=AgentStatus.FAILED,
            recommendation=(
                "This step could not be completed automatically. A claims "
                "specialist should review the claim manually."
            ),
            reasons=[f"{self.name} did not complete ({exc.__class__.__name__})."],
            confidence=None,
            next_step="manual_review",
            error="This analysis step could not be completed.",
        )

    def narrate(
        self,
        *,
        context: dict[str, Any] | None = None,
        purpose: str,
        headline: str,
        points: list[str],
        caveat: str | None = None,
        max_words: int = 90,
    ) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Gate, then ask for prose about facts already determined.

        Returns `(text, source, governance)`. On a governance denial the text is
        None, the source says so, and **the provider was never called**.
        """
        import asyncio

        request = NarrationRequest(
            purpose=purpose,
            facts={
                "headline": headline,
                "points": [p for p in points if p],
                "caveat": caveat,
            },
            max_words=max_words,
        )

        claim = (context or {}).get("claim") or {}
        candidate = {
            "claim_id": (context or {}).get("claim_id") or claim.get("claim_id") or "unknown",
            "agent": self.name,
            # What would actually go on the wire, as the Invariant sees it.
            "payload_text": json.dumps(request.facts, default=str),
            "personal_identifiers": personal_identifiers(claim),
        }

        try:
            outcome, result = asyncio.run(
                govern_llm_narration(
                    candidate,
                    # The provider call, handed to the gate rather than made
                    # here. This is the whole pre-commitment property.
                    perform=lambda: self._llm.narrate(request),
                )
            )
        except Exception as exc:  # noqa: BLE001 - governance must fail closed
            # A governance failure is NOT permission to call the model. No
            # narration, and the workflow continues on deterministic values.
            logger.warning(
                "Narration governance failed for %s (%s); the model was not called.",
                self.name,
                exc.__class__.__name__,
            )
            return None, "blocked (governance error)", {
                "action": "blocked",
                "gate": "llm-narration",
                "llm_called": False,
                "reason": "The governance gate could not be evaluated.",
            }

        governance = {
            "action": outcome.action,
            "permitted": outcome.permitted,
            "gate": outcome.gate,
            "decision_id": outcome.decision_id,
            "llm_called": outcome.llm_called,
            "invariant_violated": outcome.invariant_violated,
            "terminal_state": outcome.terminal_state,
            "reason": outcome.reason,
            "ledger_entry_ids": list(outcome.ledger_entry_ids),
            "specification": outcome.specification,
        }

        if result is None:
            # Denied. Nothing was sent. The report says so rather than showing
            # deterministic prose under the model's name.
            return None, "blocked by governance", governance

        source = result.provider + (" (degraded)" if result.degraded else "")
        governance["provider"] = result.provider
        governance["model"] = result.model
        governance["degraded"] = result.degraded
        # WHY it degraded, when it did: a fixed code from `llm.base.DegradedReason`
        # -- never an exception string, never a URL, never anything derived from
        # the key. Without this the report can say "degraded" and leave a reader
        # guessing which layer failed, which is exactly how a silent fall-through
        # to the stub went undiagnosed.
        governance["degraded_reason"] = result.degraded_reason
        return result.text, source, governance

    @staticmethod
    def confidence(
        value: float,
        basis: str,
        *,
        floor: float | None = None,
        threshold_note: str | None = None,
    ) -> Confidence:
        clamped = min(max(value, 0.0), 1.0)
        return Confidence(
            value=round(clamped, 3),
            basis=basis,
            clears_poc_threshold=None if floor is None else clamped >= floor,
            threshold_note=threshold_note,
        )
