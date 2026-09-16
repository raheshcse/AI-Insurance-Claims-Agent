"""Where conversations live.

Same shape as the other Phase 1-3 repositories: a Protocol, an in-memory
implementation for tests, and a JSONL implementation for the POC. Phase 6
replaces the JSONL one with a database and nothing else changes.

This is NOT a second claim store. A conversation holds what the customer has
said so far; the claim record is created once, by the existing
`ClaimService.submit_claim`, and the conversation then holds only its ID.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol

from conversation.contracts import ConversationState


class ConversationRepository(Protocol):
    def save(self, state: ConversationState) -> None: ...

    def get(self, conversation_id: str) -> ConversationState | None: ...


class InMemoryConversationRepository:
    """For tests, and for a POC run that should leave nothing behind."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def save(self, state: ConversationState) -> None:
        with self._lock:
            self._items[state.conversation_id] = state.model_dump(mode="json")

    def get(self, conversation_id: str) -> ConversationState | None:
        with self._lock:
            raw = self._items.get(conversation_id)
        return ConversationState.model_validate(raw) if raw else None


class JsonlConversationRepository:
    """Append-only JSONL; the last record for an id wins.

    Append-only rather than rewrite-in-place for the same reason the claim store
    is: a crash mid-write loses the newest turn, not the whole conversation.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, state: ConversationState) -> None:
        line = json.dumps(state.model_dump(mode="json"), ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def get(self, conversation_id: str) -> ConversationState | None:
        if not self._path.exists():
            return None
        found: dict | None = None
        with self._lock:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("conversation_id") == conversation_id:
                        found = record
        return ConversationState.model_validate(found) if found else None
