"""Human review queue storage.

Same pattern as the other repositories: a Protocol the service depends on, an
in-memory implementation for tests, and a JSONL one for local development. Phase 6
swaps in a database without any caller changing.

One queue entry per claim. Re-analysing a claim updates its entry rather than
creating a second one — a duplicated claim in a review queue is how work gets done
twice or not at all.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol


class ReviewQueueRepository(Protocol):
    def upsert(self, entry: dict[str, Any]) -> None: ...

    def get(self, claim_id: str) -> dict[str, Any] | None: ...

    def list_entries(self) -> list[dict[str, Any]]: ...

    def remove(self, claim_id: str) -> None: ...


class InMemoryReviewQueueRepository:
    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def upsert(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._entries[entry["claim_id"]] = dict(entry)

    def get(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(claim_id)
            return dict(entry) if entry else None

    def list_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._entries.values()]

    def remove(self, claim_id: str) -> None:
        with self._lock:
            self._entries.pop(claim_id, None)


class JsonlReviewQueueRepository:
    """Append-only log, last write per claim wins.

    Append-only rather than rewrite-in-place so the queue's history survives — a
    reviewer's actions are visible in the file even though only the latest state is
    served. That is a convenience, not an audit trail: the hash-chained VerbaLedger
    is Phase 4 and is a different artefact entirely.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        latest: dict[str, dict[str, Any]] = {}
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                claim_id = record.get("claim_id")
                if not claim_id:
                    continue
                if record.get("_removed"):
                    latest.pop(claim_id, None)
                else:
                    latest[claim_id] = record
        return latest

    def upsert(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def get(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read_all().get(claim_id)

    def list_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._read_all().values())

    def remove(self, claim_id: str) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"claim_id": claim_id, "_removed": True}) + "\n"
                )
