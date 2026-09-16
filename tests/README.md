# tests/ — Automated tests

The requirements call for automated tests covering **normal, denial, invariant violation, audit
and restart/recovery** cases. A governance layer tested only on the happy path is not evidence of
governance — the denial paths are the point.

## Where tests live

| Tests | Location | Runner |
| --- | --- | --- |
| Backend | `tests/backend/` | pytest |
| Frontend | `frontend/src/__tests__/` | vitest |

Frontend tests sit beside the code because that is the convention Vitest and Testing Library
expect; everything else lives here.

## Run them

```powershell
# Backend — from the project root
python -m pytest

# Frontend
cd frontend
npm test
```

## Current coverage — 178 tests, all passing (140 backend, 38 frontend)

### Phase 3 (67 tests)

**`tests/backend/test_routing.py` (28)** — all twelve required scenarios (low complexity,
high complexity, low confidence, high value, elevated risk, missing information, vulnerable
customer, emergency, queue retrieval, review detail, invalid claim, unexpected AI output)
plus: all applicable reasons collected rather than just the first, priority taken as the
strongest across reasons, every reason structured rather than generic, the explanation
naming observation/threshold/source, routing never recommending Approved/Completed, an
empty agent output never clearing a claim, a raising rule escalating rather than clearing,
missing information never outranking safety, emergency detected even when the workflow
short-circuits, vulnerability never becoming a risk indicator, and no fabricated governance
constructs.

**`tests/backend/test_review_api.py` (23)** — routing applying each of the three claim-state
transitions, the queue listing with reasons, urgent-first ordering, filtering, re-analysis
updating rather than duplicating an entry, review detail answering all six reviewer
questions, emergency and vulnerable flags, all four review actions, only-a-human-reaches
Approved/Completed, action history with `decision_source: human`, an unavailable action
refused with 409, both 404s, and no internal detail in errors.

**`frontend/src/__tests__/ReviewQueue.test.jsx` (16)** — the queue with reasons and
priority, counts, urgent-first ordering, filtering, safe error; the claim review screen's
six sections, every reason's evidence and AI/rule basis chip, never saying "AI decided",
both pathway banners, the decision boundary, recording an action, requiring a reviewer
name, what completing a review does and does not do, and internal content staying out of
the customer portal.

### Phase 2 (74 tests)

**`tests/backend/test_agents.py` (31)** — each agent individually: the facts/interpretation
split, missing policy, policy not in force, possible exclusion, address mismatch, inconsistent
estimate, value bands, unknown-value conservatism, emergency urgency, POC-floor reporting, a
parametrised check that risk language never accuses, indicators never customer-visible,
degradation without data, and contained agent failure.

**`tests/backend/test_workflow.py` (24)** — workflow starts and completes, agents run in order,
shared state accumulates, later agents see earlier results, trace timing; the six required
scenarios plus possible exclusion, agent failure failing closed, and an LLM failure changing no
decision; parametrised proof that no scenario performs an action; and that no governance module,
VSL package or ledger exists.

**`tests/backend/test_intelligence_api.py` (10)** — structured result, claim unchanged by
analysis, boundary fields, storage and reuse, forced re-analysis, read-back, both 404s, safe
reporting of a workflow crash, OpenAPI documentation.

**`frontend/src/__tests__/StaffConsole.test.jsx` (12)** — console is not the default view,
internal marking, running the workflow, the boundary note, all five agent panels, findings and
indicators, the POC assumption chip, employee-only marking, degraded warning, safe error,
reference required, and internal analysis absent from the customer portal.

All Phase 2 tests use the deterministic stub LLM. No test depends on a live model — decisions are
rule-derived by design, so a test needing a network call would be testing the wrong thing.

### Phase 1 (37 tests)

**`tests/backend/test_claims_api.py` (20)** — valid submission returns 201; claim ID format;
initial state is Submitted; the claim is not moved to Assessment; response structure; persistence
and read-back with no derived AI fields; reference uniqueness; missing field, empty body, invalid
email, zero damaged items, future date of loss and too-short description all rejected; a rejected
submission creates no claim; errors leak no internal detail; customer-safe 404; health.

**`tests/backend/test_claim_state.py` (7)** — the six official states and no others; the Phase 1
transition is allowed; lifecycle shortcuts are refused; Approved/Completed is terminal; official
states are disjoint from internal statuses; PreNode denial stays distinct from automation
suspension; claim reference format.

**`frontend/src/__tests__/ClaimWizard.test.jsx` (10)** — landing renders with a start action; the
customer can move through every step; empty required fields block progress with messages; an
invalid email is caught; the review page shows what was entered; edit-from-review round-trips a
correction; a successful submission shows claim ID, status and summary; the payload matches the
API contract with blank optionals as `null`; a backend outage shows a customer-safe message and
preserves the answers; the safety notice appears on urgent answers.

## Planned coverage

| Area | What it proves | Phase |
| --- | --- | --- |
| Agent unit tests | Each agent node's output shape and behaviour against synthetic inputs | **done (2)** |
| Graph tests | Conditional routing, shared-state updates | **done (2)** |
| Escalation routing tests | Queue placement, priority pathway, claim-state transitions | **done (3)** |
| Governance tests | PreNode pass; PreNode denial → human review fallback; Invariant violation → stop; Invariant violation → TerminalState | 4 |
| Audit tests | Ledger causal ordering, hash-chain integrity, PreNode denial distinguished from governance failure | 4 |
| Restart / recovery tests | Workflow and suspension state across restart (process-local state is a known POC limitation, productionised in Phase 6) | 4–6 |
| Scenario tests | End-to-end demonstration scenarios A–D | 5 |

See [`../docs/PROJECT_PLAN.md`](../docs/PROJECT_PLAN.md) §15, §21.9, §22.13 and §23.13.
