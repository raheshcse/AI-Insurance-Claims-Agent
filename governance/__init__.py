"""The X-Verba / VSL governance layer.

Reading order for a newcomer: **policy → gates → ledger**.

    policy.py      WHAT is governed. Declarations only. Imports `vsl_core`
                   and the standard library, nothing else — a test enforces it.
    gates.py       HOW it is enforced. The single call site. The governed side
                   effect is passed *into* the gate and called once, after
                   every check, so a denial cannot reach it.
    ledger.py      PROOF. The hash-chained VerbaLedger.
    audit_cli.py   verify / audit / certify / conformance / summary, with real
                   exit codes.

Deliberately empty of re-exports. Importing `governance` must not pull in the
gates: `gates.py` compiles the adapter and opens the ledger at import time, and
the module that does that should be imported by the code that enforces, not as
a side effect of touching the package.
"""
