"""Storage for claims intelligence results.

Deliberately a separate store from claims. An analysis is a recommendation about
a claim, not part of it -- keeping them apart means running the workflow can
never mutate a claim record by accident, and the Phase 4 governance gate has one
obvious place to sit if writing an analysis ever becomes a governed act.

This is NOT the VerbaLedger. The ledger is hash-chained, append-only governance
evidence and belongs to governance/ledger.py in Phase 4. This file is ordinary
application data.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol


class AnalysisRepository(Protocol):
    def save(self, analysis: dict[str, Any]) -> None: ...

    def latest_for_claim(self, claim_id: str) -> dict[str, Any] | None: ...

    def all_for_claim(self, claim_id: str) -> list[dict[str, Any]]: ...


class InMemoryAnalysisRepository:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def save(self, analysis: dict[str, Any]) -> None:
        with self._lock:
            self._rows.append(dict(analysis))

    def latest_for_claim(self, claim_id: str) -> dict[str, Any] | None:
        rows = self.all_for_claim(claim_id)
        return rows[-1] if rows else None

    def all_for_claim(self, claim_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._rows if r.get("claim_id") == claim_id]


class JsonlAnalysisRepository:
    """Append-only JSON Lines store for local development."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save(self, analysis: dict[str, Any]) -> None:
        line = json.dumps(analysis, ensure_ascii=False, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def all_for_claim(self, claim_id: str) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        rows: list[dict[str, Any]] = []
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
                        rows.append(record)
        return rows

    def latest_for_claim(self, claim_id: str) -> dict[str, Any] | None:
        rows = self.all_for_claim(claim_id)
        return rows[-1] if rows else None
