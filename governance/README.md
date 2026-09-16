# governance/ — X-Verba / VSL governance layer

**Status: IMPLEMENTED — Phase 4.**

This directory was reserved from the start so that governance would never be retrofitted into
model or application logic. Phase 4 filled it, and no governance policy is written anywhere
else.

- **What is governed** — `docs/GOVERNANCE_POLICY_CATALOGUE.md`
- **How it is enforced** — `docs/GOVERNANCE_ENFORCEMENT.md`

Everything below this line was written in Phase 0 as the constraints the implementation would
have to satisfy. It has been left as written, because it is the more useful document that way:
the notes marked *"known constraints to carry into Phase 4"* are now findings, and each one
turned out to matter. See the closing section for what actually happened to each.

## Mandated layout (from the supplied VSL spec)

The spec prescribes this structure. It is not a proposal.

```
governance/
├── __init__.py
├── policy.py      WHAT is governed. Declarations only.
├── gates.py       HOW it is enforced. The single call site.
├── ledger.py      PROOF. Hash-chained audit trail.
└── audit_cli.py   Verify / audit / certify. Exit 1 on failure.
```

Reading order for a newcomer: **policy → gates → ledger** (what, how, proof).

## Import rules — MUST be enforced

- `policy.py` imports **only `vsl_core`**. Never FastAPI, never the model, never an SDK. A rule
  needing those belongs in `gates.py`.
- `backend/app.py` calls `governance.gates`, **never** `backend/model.py` directly for a
  governed action.
- **Nothing imports `gates.py` except the backend entry point.**

## The five constructs

| Construct | Role | This POC |
| --- | --- | --- |
| **PreNode** | Soft gate — "are we confident enough?" | `automation-confidence` |
| **Invariant** | Hard rule — "is this ever acceptable?" | `policy-in-force`, `automated-authority-limit`, `no-auto-approval-under-exclusion` |
| **TerminalState** | Automation stops; no automated way out | `claim-automation-suspended` |
| **VerbaLedger** | Hash-chained, append-only decision record | `data/ledger.jsonl` (gitignored) |
| **Specification** | Versioned, authority-approved bundle | Draft until thresholds are approved |

Choosing between the first two: *if a legitimate business reason to proceed anyway is
imaginable, it is a PreNode. If proceeding anyway is always wrong, it is an Invariant.*

No X-Verba constructs beyond these five are to be introduced.

## Packages

This project **is** a LangGraph `StateGraph`, so the spec's decision rule gives **VSL-Core +
VSL-LangGraph**. Three install traps apply — the PyPI name `vsl-core` is an unrelated stub (use
`super-semantics-vsl`, import `vsl_core`), there are no releases so pin a SHA, and VSL-LangGraph
needs a separate `--no-deps` install. Details and the exact requirement lines:
`docs/GOVERNANCE_POLICY_CATALOGUE.md` §1.

## Principles that constrain the implementation

1. **On the execution path, not a dashboard.** Every `await gate(...)` precedes what it guards;
   the side effect is the last thing the caller does and is unreachable from any denial path.
   That ordering *is* the pre-commitment property.
2. **Three distinct outcomes, never two.** PreNode denial, Invariant violation, and Invariant
   violation naming a TerminalState stay distinguishable in the ledger, the queue and the
   dashboard.
3. **A PreNode denial is governance working → SUFFICIENT.** Writing INSUFFICIENT on an ordinary
   denial makes audit check 4 demand a SPECIFICATION_UPDATE for every one, failing the audit
   permanently on normal traffic. INSUFFICIENT is for Invariant violations only.
4. **`caused_by` on every entry.** Without it, `audit()` falls back to a timestamp heuristic
   that can report a false pass under concurrency.
5. **Assurance is derived, never asserted.** Every gate here is `OUTPUT_LAYER` and derives
   **LOW**. That is honest output-layer control — say so rather than claiming HIGH.
6. **Unique `denial_key` per gate** when wiring `gated_node` / `route_on_denial`; sharing one
   makes the second router read the first gate's denial.
7. **No silent denials.** The UI must render `human_queue` as a real review state.
8. **Policy declaration, enforcement and model logic stay separated.**

## Known constraints to carry into Phase 4

- `Fallback`'s `delta_factor`, `max_retries` and `intervention` are declarative only — implement
  fallback behaviour yourself in `gates.py`.
- In-process suspension state does not survive a restart or a second worker. Production answer:
  Redis, re-derived at startup by scanning for a TERMINAL with no later
  HUMAN_AUTHORISED_TRANSITION.
- `AutomationDeniedException` can be swallowed by a bare `except Exception` — grep in CI.
- `verify_integrity()` cannot detect truncation.
- X-Verba's Γ (static coverage) ≠ VSL-Core's Gamma (runtime ratio vs 1.1).

## What happened to each Phase 0 constraint

Every one bit. None was theoretical.

| Constraint written in Phase 0 | What Phase 4 found |
| --- | --- |
| `Fallback`'s fields are declarative only | Confirmed — `vsl-langgraph` emits a `UserWarning` at import saying `gated_node` does not consume `Fallback`. The warning is left visible, not suppressed. `ROUTE_TO_HUMAN_QUEUE` is implemented in `gates.py` and `graph/governed.py`. |
| In-process suspension does not survive a restart | Confirmed and **not solved**. `rebuild_suspensions_from_ledger()` is the production re-derivation, implemented and tested; a test asserts both the loss and the recovery. |
| `AutomationDeniedException` can be swallowed | Structural answer instead of a grep: the side effect is passed *into* the gate, so swallowing the exception still cannot reach it. |
| `verify_integrity()` cannot detect truncation | Carried into `docs/GOVERNANCE_ENFORCEMENT.md` §11 as a stated limitation, with `current_checkpoint()` named as the anchoring value an external witness would need. |
| Static Γ ≠ runtime Gamma | Sharper than expected: **there is no `x-verba scan` tool at all** — no console entry point, no static-analysis module. No static Γ figure is reported anywhere, because computing one would mean inventing it. `audit_cli conformance` runs the framework's real adapter suite instead. |
| SUFFICIENT vs INSUFFICIENT (constraint 3 above) | Exactly the trap described. A PreNode denial writes SUFFICIENT; only an Invariant violation writes INSUFFICIENT. |
| Unique `denial_key` per gate (constraint 6) | Implemented as `policy.DENIAL_KEYS`, one per gate. |
| Gamma vs the decision boundary | The one that would have failed silently: dividing by the raw odds assumes a boundary of 0.5. Ours is 0.80, so the gate would have waved through work it should stop, with no error anywhere. |

Still outstanding, unchanged: the threshold values (`docs/DECISION_TABLE.md` §7) remain POC
proposals awaiting business approval, and the pinned commit SHAs should be re-checked before
any deployment.
