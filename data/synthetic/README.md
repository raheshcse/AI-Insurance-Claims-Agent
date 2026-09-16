# data/synthetic/ — Generated synthetic datasets

**SYNTHETIC DATA ONLY.** Every record here is fabricated. Names, addresses,
emails (`@example.invalid`) and phone numbers are deliberately non-real. No real
customer, policy or claim data may ever be added to this directory.

Structure and field definitions: [`../../docs/SYNTHETIC_DATA_SPEC.md`](../../docs/SYNTHETIC_DATA_SPEC.md).

## What exists now

| File | Records | Added | Purpose |
| --- | --- | --- | --- |
| `customers.jsonl` | 5 | Phase 1 | Policyholders, including one vulnerable customer with an accessibility need and one very recent customer |
| `policies.jsonl` | 5 | Phase 1 | Home policies, one per customer |
| `policy_wordings.jsonl` | 1 wording, 12 sections | Phase 2 | The Home/Storm knowledge base the Policy Agent retrieves from and cites |
| `historical_claims.jsonl` | 7 | Phase 2 | Prior claims per customer — the Fraud & Risk Agent's evidence base |
| `risk_rules.jsonl` | 8 | Phase 2 | Risk indicator definitions, as data rather than prompt text |

Each policy carries a `scenario_note` explaining which Phase 0 decision-table row
or demonstration scenario it is there to support — a clean policy for Scenario A,
a lapsed policy for Invariant INV-01, an exclusion-bearing policy for INV-03, a
high-sum-insured policy for the authority-limit Invariant, and a recently
incepted policy for the risk indicators.

## What is NOT here yet

Claims, documents, historical claims, policy wordings and risk rules are defined
in the spec but not generated. **Phase 1 does not read any of them** — the FNOL
comes from the customer, and policy retrieval is Phase 2. They are generated when
the phase that consumes them is built:

| Dataset | First needed in |
| --- | --- |
| Claims (seeded in each state) | Phase 3 — the human review queue |
| Documents | Phase 3+ — document analysis, if it is in scope |

## How the data is used

Phase 1 reads none of it — the backend accepts an FNOL and stores it.

Phase 2 reads all of it. The Policy Agent looks up `policies.jsonl` by the policy number the
customer typed and cites sections of `policy_wordings.jsonl`; the Fraud & Risk Agent evaluates
`risk_rules.jsonl` against the claim, the policy and `historical_claims.jsonl`.

Each policy carries a `scenario_note` naming the decision-table row it exists to exercise, so the
datasets can drive a demonstration rather than just fill a table:

| Policy | Exercises |
| --- | --- |
| `POL-HOME-20117` | Clean cover — the straightforward claim |
| `POL-HOME-20233` | Lapsed at the date of loss — Invariant INV-01 (D-03) |
| `POL-HOME-20349` | Recent inception + cover change + prior flagged claim — elevated risk |
| `POL-HOME-20455` | Maintenance and wear exclusions — Invariant INV-03 (D-09) |
| `POL-HOME-20512` | High sums insured — above the automated authority limit (D-08) |

Lodged claims are written to `../claims/claims.jsonl`, which is gitignored —
that is runtime state, not seed data.
