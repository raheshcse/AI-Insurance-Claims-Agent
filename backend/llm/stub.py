"""Deterministic offline provider.

This is the default when no API key is configured, and what the test suite uses.
It is not a mock bolted on for tests -- it is how the POC runs without a model,
so a demonstration never depends on a network call and the workflow is fully
reproducible.

It composes prose from the same structured facts a real model would receive.
The result is plainer, and says so.
"""

from __future__ import annotations

from llm.base import NarrationRequest, NarrationResult


def _sentence(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else text + "."


class StubLLMProvider:
    """Rule-composed narration. No network, no variance."""

    name = "stub"
    model = None
    """No model answered. Reported as null rather than as a placeholder name."""

    def narrate(self, request: NarrationRequest) -> NarrationResult:
        facts = request.facts
        parts: list[str] = []

        headline = facts.get("headline")
        if headline:
            parts.append(_sentence(headline))

        for item in facts.get("points", []) or []:
            if item:
                parts.append(_sentence(item))

        caveat = facts.get("caveat")
        if caveat:
            parts.append(_sentence(caveat))

        if not parts:
            parts.append(_sentence(f"No narrative available for {request.purpose}"))

        text = " ".join(parts)
        words = text.split()
        if len(words) > request.max_words:
            text = " ".join(words[: request.max_words]).rstrip(",;") + "..."

        return NarrationResult(text=text, provider=self.name, model=None, degraded=False)
