"""Phase 4 test fixtures — governance.

Two things every governance test needs, and one thing the whole suite needs.

**Isolation.** `governance/ledger.py` binds a process-wide ledger at import,
which is right for the application and wrong for tests: a suite that appends to
`data/ledger.jsonl` would leave a developer's real ledger full of test records
and would make `audit()` results depend on how many times you had run pytest.
`isolated_ledger` redirects the module-level ledger at a tmp path.

**A clean suspension registry.** Suspensions live in process memory (a stated
limitation, see `governance/gates.py`). A test that suspends a claim would
otherwise block every later test using the same claim id.

The autouse fixture applies both to *every* test in the suite, not only the
governance ones, because the Phase 2 and Phase 3 tests now run the gate too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the process-wide ledger at a temporary file, and reset suspensions.

    Yields the ledger so a test can read the entries the code under test wrote.
    """
    from governance import gates as gates_module
    from governance.ledger import build_ledger

    ledger = build_ledger(tmp_path / "ledger.jsonl")
    monkeypatch.setattr(gates_module, "default_ledger", ledger)
    gates_module.suspensions.reset()
    try:
        yield ledger
    finally:
        gates_module.suspensions.reset()


@pytest.fixture
def entries(isolated_ledger):
    """Every ledger entry written so far, in sequence order."""

    def read() -> list[Any]:
        return sorted(isolated_ledger.store.all_entries(), key=lambda e: e.sequence)

    return read


@pytest.fixture
def governed_claim() -> dict[str, Any]:
    """A candidate that passes every gate.

    Confidence sits above the derived floor (0.8148 at a 0.80 boundary), the
    policy is in force, the peril is covered, the value is inside the automated
    authority limit and no exclusion is engaged.
    """
    return {
        "claim_id": "CLM-GOV-0001",
        "confidence": 0.94,
        "automated_route_proposed": True,
        "policy_in_force_at_loss": True,
        "peril_covered": True,
        "estimated_claim_value": 3200.0,
        "exclusions_possibly_engaged": [],
        "cover_certainty": "clear",
    }


@pytest.fixture
def recorder():
    """A side effect that records whether — and how often — it fired."""

    class Recorder:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> str:
            self.calls += 1
            return "side-effect-performed"

    return Recorder()
