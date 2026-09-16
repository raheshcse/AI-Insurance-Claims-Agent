"""Claim persistence.

Phase 1 uses a development-friendly JSON Lines store. It is deliberately hidden
behind a Protocol so that Phase 6 can substitute a real database without any
caller changing: the service layer depends on `ClaimRepository`, never on the
file.

This is NOT the VerbaLedger. The ledger is append-only hash-chained governance
evidence and belongs to governance/ledger.py in Phase 4.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol


class ClaimRepository(Protocol):
    """The persistence contract the service layer depends on."""

    def save(self, claim: dict[str, Any]) -> None: ...

    def get(self, claim_id: str) -> dict[str, Any] | None: ...

    def exists(self, claim_id: str) -> bool: ...


class InMemoryClaimRepository:
    """Used by tests and by any run that should leave nothing behind."""

    def __init__(self) -> None:
        self._claims: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save(self, claim: dict[str, Any]) -> None:
        with self._lock:
            self._claims[claim["claim_id"]] = claim

    def get(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            claim = self._claims.get(claim_id)
            return dict(claim) if claim else None

    def exists(self, claim_id: str) -> bool:
        with self._lock:
            return claim_id in self._claims


class JsonlClaimRepository:
    """Append-only JSON Lines file store for local development.

    Known limitations, stated rather than hidden:
      * The whole file is scanned on read. Fine for a POC, not for production.
      * The in-process lock does not coordinate across workers.
      * There is no index.
    All three disappear when this is swapped for a database in Phase 6.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, claim: dict[str, Any]) -> None:
        line = json.dumps(claim, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def get(self, claim_id: str) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        found: dict[str, Any] | None = None
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
                    if record.get("claim_id") == claim_id:
                        found = record  # last write wins
        return found

    def exists(self, claim_id: str) -> bool:
        return self.get(claim_id) is not None
