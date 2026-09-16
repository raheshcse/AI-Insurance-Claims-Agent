"""PROOF. The hash-chained audit trail.

This is the VerbaLedger from `vsl_core` — an append-only, hash-chained record of
governance decisions with causal links between them. It is not an application
log with a governance-sounding name: `verify_integrity()` re-walks the hash
chain, and `audit()` runs the framework's own five checks over the entries.

`fsync=True` deliberately: a record lost in a page cache never happened, and a
governance record that never happened is worse than one that says "denied".
"""

from __future__ import annotations

import os
from pathlib import Path

from vsl_core.ledger import JsonlLedgerStore, VerbaLedger

LEDGER_PATH = Path(os.environ.get("VSL_LEDGER_PATH", "data/ledger.jsonl"))
LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)

ledger = VerbaLedger(JsonlLedgerStore(LEDGER_PATH, fsync=True))
"""The process-wide governance ledger."""


def build_ledger(path: Path | str) -> VerbaLedger:
    """A ledger at an explicit path — used by tests and by the audit CLI."""
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return VerbaLedger(JsonlLedgerStore(resolved, fsync=True))
