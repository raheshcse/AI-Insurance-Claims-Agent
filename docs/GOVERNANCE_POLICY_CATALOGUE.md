# X-Verba / VSL Governance Policy Catalogue

**Phase 0 — Business & Governance Foundation.**

> **This is a policy declaration, not an implementation.** No governance code is written in
> Phase 0. The `governance/` directory stays empty of implementation until Phase 4 is approved.

**Primary source:** *X-Verba — VSL Governance Spec for Agent Builds*, Super Semantics, v1.0.
Every construct, exception, ledger entry type and audit check named here comes from that
document. **No X-Verba construct has been invented.** Where this catalogue adds something, it
adds *insurance policy content* inside those constructs — never new constructs.

---

## 1. Which packages this project needs

The guidance gives a decision rule that must be applied before installing anything:

> *Is the agent built as a LangGraph StateGraph (i.e. the code calls `graph.add_node()` /
> `add_edge()` / `add_conditional_edges`)?*

For this project the answer is **YES** — the requirements mandate LangGraph orchestration.
Therefore:

| Package | Needed | Role |
| --- | --- | --- |
| **VSL-Core** | **Yes — always** | The governance primitives. Framework-agnostic, zero runtime dependencies |
| **VSL-LangGraph** | **Yes** | Adapter wiring the same primitives into a LangGraph `StateGraph` |

### 1.1 The three installation traps — recorded now so Phase 4 does not rediscover them

1. **`pip install vsl-core` is wrong.** That PyPI name is an unrelated 1 KB stub. The
   distribution name is **`super-semantics-vsl`**; the import name is **`vsl_core`**.
2. **No releases or tags.** Pin to a commit SHA.
3. **VSL-LangGraph declares a stale dependency URL** (`4vish/VSL-Core.git`). Requesting both
   packages normally gives `ResolutionImpossible`. Install it with `--no-deps` and list its
   dependencies explicitly.

The requirements file for Phase 4 therefore looks like this (from the guidance, verbatim in
shape):

```
# ---- Governance (X-Verba / VSL) ----
super-semantics-vsl @ git+https://github.com/supersemantics/VSL-Core.git@0f8d10ee6a1679dd1bedd06cebb7c23e09557329
langgraph>=0.2

# NOTE: vsl-langgraph pins its vsl-core dependency to a stale URL, which conflicts
# with the line above. Install it separately, after this file:
#   pip install --no-deps "vsl-langgraph @ git+https://github.com/supersemantics/VSL-Langgraph.git@d2f4b736c8e321d236e955622a71f7a9c02981ee"
```

Verification after install (the conformance suite must return empty / `CONFORMANT`):

```
python -c "from vsl_core.conformance.suite import run_conformance_suite; \
from vsl_core.conformance.reference_adapter import PlainPythonReferenceAdapter; \
print(run_conformance_suite(PlainPythonReferenceAdapter()) or 'CONFORMANT')"
```

**[Open: SHAs should be re-verified at the start of Phase 4 — they are pinned commits, not
releases, and the spec is v1.0.]**

---

## 2. The five constructs and how this POC uses them

| Construct | Meaning (guidance) | On failure (guidance) | Use in this claims POC |
| --- | --- | --- | --- |
| **PreNode** | Soft gate — "are we confident enough?" | `AutomationDeniedException` → reroute via Fallback | Automation eligibility when the claim is judged, not measured: assessment confidence |
| **Invariant** | Hard rule — "is this ever acceptable?" | `InvariantViolation` → straight to a TerminalState | Cover basis, automated authority limit, exclusions |
| **TerminalState** | Automation stops. No automated way out | — | `claim-automation-suspended`; exit only by human re-enablement |
| **VerbaLedger** | Hash-chained, append-only decision record | `LedgerIntegrityError` on a broken chain | The audit trail behind FR-12 and UI-05 |
| **Specification** | Versioned, proofed, authority-approved bundle | `ValueError` at construction/activation | The approved claims governance policy bundle |

**The choosing rule, applied throughout this catalogue:** *if you can imagine a legitimate
business reason to proceed anyway, it is a PreNode. If proceeding anyway is always wrong, it is
an Invariant.*

### 2.1 Assurance is derived, never asserted

The guidance is unambiguous: you supply two facts and VSL computes the level. There is no
setter.

| Fact | Question |
| --- | --- |
| **F1** | Does the check run before commitment, with no side effect yet fired? |
| **F2** | Does it touch the mechanism producing the output (weights, loss, logits), or only what surrounds it? |

```
F1=False                         -> LOW
F1=True,  F2=FULL                -> HIGH
F1=True,  F2=PARTIAL or INDIRECT -> MEDIUM
F1=True,  F2=NONE                -> LOW
```

**Every gate in this POC declares `OUTPUT_LAYER` — F1 = True, F2 = NONE — and therefore derives
LOW.** That is correct, not a defect. LOW means output-layer control: it blocks a bad action but
does not change how the model decides. Reaching HIGH would require a formation-layer change
(loss function, feature space, training), which this POC does not do.

**This must be stated plainly in the demonstration.** Claiming HIGH assurance for a claims
triage gate would be false, and the pinned build raises `TypeError` on a non-bool
`f1_pre_commitment` or a non-`F2Modification` `f2_modification` anyway.

---

## 3. PreNodes

Placed at the automation-eligibility decision (CP-11), before the routing side effect.

### PN-01 · `automation-confidence`

| | |
| --- | --- |
| **Question** | Is the assessment confident enough to close this claim without a person? |
| **Why a PreNode** | There is a legitimate business reason to proceed on a borderline claim — a person can simply look at it. Denial is not a failure |
| **Monitor input** | Assessment Agent confidence (R-07) |
| **Gamma mapping** | `(p/(1-p)) / (t/(1-t))` where `t = DECISION_THRESHOLD`. **Must divide by the decision boundary, not 0.5** — the guidance warns that hard-coding 0.5 makes the PreNode deny everything and the feature dies silently with no error anywhere |
| **Gamma threshold** | `ROBUST_GAMMA_DEFAULT_THRESHOLD` = 1.1 (library constant) |
| **Decision boundary** | `DECISION_THRESHOLD = 0.80` **[POC-PROPOSED]** → effective floor `p ≥ 0.815` |
| **Calibration error** | `delta_estimation_error = 0.10` **[POC-PROPOSED]** |
| **Assurance basis** | `OUTPUT_LAYER` → derives **LOW** |
| **Fallback** | `on_failure = "ROUTE_TO_HUMAN_QUEUE"`, `max_retries = 0` |
| **On denial** | `AutomationDeniedException` → claim to Human Review, internal status `governance_denied_prenode`, verification **SUFFICIENT** |
| **Decision row** | D-05 · Escalation E-01 · **Demonstration Scenario B** |

**Known constraint, from the guidance:** `Fallback`'s `delta_factor`, `max_retries` and
`intervention` are **declarative only — no adapter consumes them.** The actual fallback
behaviour (writing the queue entry, setting the reason, updating state) must be implemented in
`gates.py`. Declaring the fallback does not perform it.

### PN-02 · `communication-safety-confidence` — **candidate, confirm in Phase 4**

| | |
| --- | --- |
| **Question** | Is the drafted customer message accurate enough to send without approval? |
| **Why a PreNode** | A borderline message can legitimately be sent after a human reads it |
| **Fallback** | `ROUTE_TO_HUMAN_APPROVAL` |
| **Status** | Proposed. Requires a defensible confidence signal for message accuracy, which does not exist yet. If one cannot be defined honestly, message approval should be a deterministic rule instead of a fake confidence number |

---

## 4. Invariants

Hard rules. Proceeding anyway is always wrong.

Each Invariant is evaluated on the **claim's own facts**, never conditioned on
what the routing layer proposed — an Invariant that skips its check when nobody
proposed the action is not enforcing anything, it is agreeing with the layer
above. What the routing decision changes is the **severity** of a denial:

- **Routing already chose a person.** Governance and the business rules agree.
  The automated action is refused, the verification is `SUFFICIENT` (governance
  worked, exactly as for a PreNode denial), and nothing is suspended.
- **The layer above attempted the action anyway.** That is an incident: the
  verification is `INSUFFICIENT`, the claim enters the TerminalState in §5, a
  `SPECIFICATION_UPDATE` is written, and only a named authority can re-enable
  automation.

Recording the first case as `INSUFFICIENT` would demand a root-cause analysis
for every claim over the authority limit, and audit check 4 would fail
permanently on ordinary traffic.

### INV-01 · `policy-in-force`

| | |
| --- | --- |
| **Rule** | The policy must have been `active` and within `inception_date … expiry_date` at the **date of loss** |
| **Why an Invariant** | Without cover at the time of loss there is no contractual basis for any automated claim outcome. There is no legitimate business reason to proceed automatically |
| **Input** | Policy record + `date_of_loss` |
| **Assurance basis** | `OUTPUT_LAYER` → LOW |
| **Commitment point** | **CP-14** — the automated claim action |
| **On violation** | Evaluated on the claim's own facts, always. If the automated action was **not** attempted: `action_denied`, VERIFICATION `SUFFICIENT`, no TerminalState. If it **was** attempted: `InvariantViolation` → VERIFICATION `INSUFFICIENT` → `claim-automation-suspended` → `SPECIFICATION_UPDATE` |
| **Decision row** | D-03 · Escalation E-05 |

### INV-02 · `automated-authority-limit`

| | |
| --- | --- |
| **Rule** | The automated route must not be taken where `estimated_claim_value > AUTOMATED_AUTHORITY_LIMIT_NZD` |
| **Why an Invariant** | An authority limit that high confidence can override is not an authority limit |
| **Input** | `estimated_claim_value`, `AUTOMATED_AUTHORITY_LIMIT_NZD = 20,000` **[POC-PROPOSED]** |
| **Assurance basis** | `OUTPUT_LAYER` → LOW |
| **Commitment point** | **CP-14** — the automated claim action |
| **On violation** | Evaluated on the claim's own facts, always. If the automated action was **not** attempted: `action_denied`, VERIFICATION `SUFFICIENT`, no TerminalState. If it **was** attempted: `InvariantViolation` → VERIFICATION `INSUFFICIENT` → `claim-automation-suspended` → `SPECIFICATION_UPDATE` |
| **Decision row** | D-08 · Escalation E-04 · **Demonstration Scenario C** |

### INV-03 · `no-auto-approval-under-exclusion`

| | |
| --- | --- |
| **Rule** | The automated route must not be taken where a policy exclusion is engaged or cover is flagged ambiguous |
| **Why an Invariant** | Automatically approving a claim a policy may not cover is never acceptable — it is a regulatory exposure, not a service-level trade-off |
| **Input** | Policy Agent exclusion flags and cover-certainty flag |
| **Assurance basis** | `OUTPUT_LAYER` → LOW |
| **Commitment point** | **CP-14** — the automated claim action |
| **On violation** | Evaluated on the claim's own facts, always. If the automated action was **not** attempted: `action_denied`, VERIFICATION `SUFFICIENT`, no TerminalState. If it **was** attempted: `InvariantViolation` → VERIFICATION `INSUFFICIENT` → `claim-automation-suspended` → `SPECIFICATION_UPDATE` |
| **Decision row** | D-09 · Escalation E-06 |

### INV-04 · `no-customer-data-egress` — **implemented in the governance refactor**

| | |
| --- | --- |
| **Rule** | No payload carrying a personal identifier may leave the system for a third-party model |
| **Why an Invariant** | Egress cannot be undone. Once a payload has been sent, no downstream handling retrieves it |
| **Input** | `payload_text` and `personal_identifiers` from the claim, as the gate sees them |
| **Commitment point** | **CP-13** — the LLM call |
| **Assurance basis** | `OUTPUT_LAYER` → LOW |
| **On violation** | `InvariantViolation` → `claim-automation-suspended`. The provider is never reached: no request is built, no socket opens, the API key is never read |
| **Status** | **Not a Phase 0 escalation rule.** Phase 0 had no LLM commitment to govern — Phase 2 introduced the model and Phase 4A made it a real network call. It derives from the standing constraint that no real customer data enters this system and none leaves it, and is flagged here so it can be rejected on review rather than absorbed silently |

This replaces the earlier candidate `synthetic-data-only`, which proposed
checking that claim data *was* marked synthetic. That is better served by a
startup assertion than a runtime Invariant: it asks about the dataset, not about
an action, and an Invariant that cannot name the action it forbids is a
configuration check wearing a governance construct's name.

---

## 5. TerminalState

### TS-01 · `claim-automation-suspended`

| | |
| --- | --- |
| **Name** | `claim-automation-suspended` **[POC-PROPOSED — the guidance names the construct; the state names for this application are ours to define and approve]** |
| **Description** | Automated claim handling halted. Human re-enablement required |
| **Entry conditions** | `"policy-in-force violated"`, `"automated-authority-limit violated"`, `"no-auto-approval-under-exclusion violated"` |
| **Effect** | The claim moves to Human Review with internal status `automation_suspended`. Every subsequent governed call returns `suspended` before any other check runs (decision row D-16) |
| **Exit** | **Only** a HUMAN_AUTHORISED_TRANSITION ledger entry, `caused_by` the TERMINAL entry — audit check 5 |

`TerminalState` is a named construct with `entry_conditions`, not a boolean flag. One terminal
state covering all three Invariants matches the guidance's own example, which lists multiple
entry conditions on a single state. Splitting into per-Invariant terminal states is possible and
is left as an open question in §9.

---

## 6. What is *not* a governance construct

An honest catalogue has to say what stays out, or the governance layer becomes a dumping ground
and the demonstration loses its meaning.

**These are deterministic workflow logic, not PreNodes:**

- Missing mandatory information (→ Information Required).
- High complexity, high value below the authority limit, risk bands, conflicting information,
  customer request.
- Emergency and vulnerable-customer routing.

**Why.** A PreNode's monitor returns a `GammaEstimate` — a graded confidence signal. These
conditions are binary facts, not confidence judgements. Dressing a boolean up as a Gamma value
to force it through a PreNode would be inventing a mechanism the guidance does not describe and
would make the governance numbers meaningless.

**They are still governed** — every one of them results in an action (a state write, a queue
entry, a message), and every one of those actions sits behind a gate at CP-09/CP-10/CP-12. The
gate protects the side effect. The *reason* for routing is business logic.

**This reading needs confirmation in Phase 4** — see §9.

---

## 7. The ledger

### 7.1 Entry types used

| Entry type | Written when | `caused_by` |
| --- | --- | --- |
| `MONITOR` | **Every governed decision**, not only on incident — so audit check 1 has continuous evidence | — (chain head for the decision) |
| `PRE_NODE` | After each PreNode evaluation, denied or not | The MONITOR entry |
| `VERIFICATION` | After the PreNode outcome is resolved | The PRE_NODE entry |
| `TERMINAL` | On an Invariant violation | The INSUFFICIENT VERIFICATION entry |
| `SPECIFICATION_UPDATE` | After an INSUFFICIENT verification — required by audit check 4 | The VERIFICATION entry |
| `HUMAN_AUTHORISED_TRANSITION` | When a human re-enables suspended automation | The TERMINAL entry |

`drift_detected` on the MONITOR is set from the confidence-vs-decision-threshold comparison,
with the rounded confidence in `extra_payload` — so every decision leaves evidence whether or not
anything went wrong.

### 7.2 The SUFFICIENT / INSUFFICIENT rule — the trap that breaks audits

The guidance is explicit and this is the single easiest way to get the whole thing wrong:

> **MUST NOT write INSUFFICIENT on an ordinary PreNode denial.** INSUFFICIENT means governance
> itself failed, and check 4 then demands a SPECIFICATION_UPDATE for every one — so the audit
> fails permanently on normal traffic. A PreNode correctly denying a low-confidence action is
> governance **working** → SUFFICIENT. Reserve INSUFFICIENT for Invariant violations.

| Outcome | Verification result | Rationale |
| --- | --- | --- |
| PreNode passes | `SUFFICIENT`, outcome `approved` | Automation authorised |
| **PreNode denies** | **`SUFFICIENT`**, outcome `routed_to_human_queue` | **Governance worked.** Scenario B produces SUFFICIENT |
| **Invariant violated** | **`INSUFFICIENT`** + TERMINAL + SPECIFICATION_UPDATE | Governance failed for that action. Scenario C |

Scenario B writing INSUFFICIENT would fail the audit on every ordinary low-confidence claim —
which, in a claims system, is routine traffic.

### 7.3 `caused_by` is mandatory

> **MUST always set `caused_by`.** Without it, `audit()` falls back to a "same identity, later
> timestamp" heuristic. Under any concurrency that heuristic can match an unrelated PRE_NODE to
> your MONITOR and report a **false pass**.

A claims system processing several claims at once is exactly that concurrency. A false pass is
worse than a failure — it is an audit that says the system is governed when it is not.

### 7.4 The five audit checks

| # | Check | Satisfied by |
| --- | --- | --- |
| 1 | `no_monitoring_gaps` | MONITOR entries within `max_monitor_gap_seconds` |
| 2 | `drift_flagged_monitor_has_pre_node` | Every MONITOR with `drift_detected=True` has a PRE_NODE `caused_by` it |
| 3 | `pre_node_has_verification` | Every PRE_NODE has a VERIFICATION `caused_by` it |
| 4 | `insufficient_verification_has_specification_update` | Every INSUFFICIENT VERIFICATION has a SPECIFICATION_UPDATE `caused_by` it |
| 5 | `terminal_has_human_authorised_transition` | Every TERMINAL has a HUMAN_AUTHORISED_TRANSITION `caused_by` it |

Check 5 is why re-enablement (CP-17) is a first-class part of this design and not an
afterthought: a suspended claim that nobody ever re-enables leaves the audit failing.

### 7.5 Integrity vs audit

`verify_integrity()` and `audit()` answer different questions — the first asks whether records
were **edited**, the second whether they **describe a governed process**. A tampered payload
gives `integrity=False` while all five checks still pass. **Run both.**

`verify_integrity()` also **cannot detect truncation**; if that matters, anchor
`current_checkpoint()` externally.

Ledger location: `data/ledger.jsonl`, append-only, **gitignored**, `fsync=True` — the guidance's
reasoning is that a record lost in a page cache never happened.

---

## 8. Where the governance layer lives

The guidance mandates a three-layer structure and a specific `governance/` layout. This project
follows it exactly.

```
governance/                <-- X-Verba layer. MUST exist.
├── __init__.py
├── policy.py              WHAT is governed. Declarations only.
├── gates.py               HOW it is enforced. The single call site.
├── ledger.py              PROOF. Hash-chained audit trail.
└── audit_cli.py           Verify / audit / certify. Exit 1 on failure.

data/ledger.jsonl          Append-only. Gitignored.
```

### 8.1 Import rules — MUST be enforced

- `governance/policy.py` imports **only `vsl_core`**. Never FastAPI, never the model, never an
  SDK. A rule needing those belongs in `gates.py`.
- `backend/app.py` calls `governance.gates`, **never** `backend/model.py` directly for a
  governed action.
- **Nothing imports `gates.py` except the backend entry point.**

Reading order for a newcomer: **policy → gates → ledger** (what, how, proof).

### 8.2 Gate call sequence

The order in `gates.py`, from the guidance:

```
(a) MONITOR written — for EVERY request
(b) suspension check — a suspended claim returns immediately
(c) PreNodes — denial reroutes, never silently drops; SUFFICIENT written
(d) Invariants — non-bypassable; violation writes INSUFFICIENT + TERMINAL and suspends
(e) SUFFICIENT verification written
──────────────────────────────────────────────────────────────
    only now may the caller fire the side effect
```

A `CompiledGate` is simply `async (candidate) -> None`, raising on denial. That is the whole
protocol. Gates compile once at import.

### 8.3 LangGraph wiring — Phase 4

`policy.py` does not change when LangGraph is introduced. Only the wiring does:

- `LangGraphAdapter` compiles the same PreNode and Invariant objects.
- `gated_node(...)` calls the gate immediately before the wrapped node and, on denial, returns a
  **state update instead of raising** — so a conditional edge routes the run rather than
  crashing the graph.
- `route_on_denial(...)` on a conditional edge sends denied runs to the human-queue node.
- **Each gate MUST have its own `denial_key`.** Two gates sharing a key makes the second router
  read the first gate's denial. With three Invariants and at least one PreNode, this project has
  exactly the conditions for that bug.

### 8.4 Frontend obligation

> The UI **MUST** render `human_queue` as a real review state, not swallow it — the whole point
> of a soft gate is that denial reroutes rather than discards.

This is a frontend requirement, not just a backend one, and it maps directly to UI-04.

---

## 9. Specification bundle

The **Specification** is the versioned, authority-approved bundle of the above. For this POC it
comprises: PN-01 (and PN-02 if confirmed), INV-01…INV-03 (and INV-04 if confirmed), TS-01, the
assurance bases, and the threshold values from `DECISION_TABLE.md` §7.

It cannot be considered *authority-approved* until the business signs off the thresholds. Until
then it is a **draft specification**, and the demonstration should say so.

A `SPECIFICATION_UPDATE` entry is also a ledger requirement (audit check 4) after every
INSUFFICIENT verification — so specification change is part of the runtime flow, not only a
governance-committee activity.

---

## 10. Pre-ship checklist — carried forward to Phase 4

From the guidance, to be satisfied before any demonstration:

- ☐ `governance/` exists with `policy.py`, `gates.py`, `ledger.py`
- ☐ `policy.py` imports only `vsl_core`
- ☐ `confidence_gamma` divides by the decision boundary, **not 0.5**
- ☐ Every gate is awaited **before** the side effect
- ☐ `caused_by` set on every PRE_NODE and VERIFICATION write
- ☐ INSUFFICIENT used **only** for Invariant violations
- ☐ Conformance suite returns empty
- ☐ `audit()` passes on clean traffic
- ☐ Frontend renders `human_queue` as a review state
- ☐ `.env` and `data/ledger.jsonl` are gitignored
- ☐ Each gate has a unique `denial_key`
- ☐ CI greps for bare `except Exception` that could swallow `AutomationDeniedException`

---

## 11. Known constraints — to be stated, not papered over

The guidance asks for these to be declared honestly. They are:

1. **Most runtime gates derive LOW assurance.** That is output-layer control, and it is honest.
2. **`Fallback`'s `delta_factor`, `max_retries` and `intervention` are declarative only.** No
   adapter consumes them. Fallback behaviour must be implemented in `gates.py`.
3. **In-process suspension state does not survive a restart or a second worker.** Before
   production: move it to Redis and re-derive at startup by scanning the ledger for a TERMINAL
   with no later HUMAN_AUTHORISED_TRANSITION. This is a Phase 6 item and a live risk in the
   requirements' risk register.
4. **`AutomationDeniedException` can be swallowed by a bare `except Exception`.** Grep for it
   in CI.
5. **`verify_integrity()` cannot detect truncation.** Anchor `current_checkpoint()` externally
   if that matters.
6. **Two different quantities are both called Gamma.** X-Verba's Γ is a static coverage ratio
   (governed ÷ total decision points, 0–1) from `x-verba scan`. VSL-Core's Gamma is a runtime
   governance-to-drift ratio judged against 1.1. **Same word, different measure — they must not
   be conflated in the dashboard or the demonstration.**

### 11.1 Optional build scanning

`x-verba` (on PyPI, unlike `vsl-core`) finds decision points with no safeguard and scores
coverage:

```
pip install x-verba
x-verba scan .                    # writes .verba/governance.yaml
x-verba scan . --save-baseline
x-verba qa . --schema .verba/governance-baseline.json   # CI, exit 1 on regression
```

Proposed for Phase 4 CI, as evidence that the commitment-point catalogue in
`COMMITMENT_POINTS.md` matches what the code actually guards.

---

## 12. Open questions

| # | Item | Status |
| --- | --- | --- |
| 1 | Threshold values (`DECISION_THRESHOLD`, authority limit, calibration error) | **Business approval required** — `DECISION_TABLE.md` §7 |
| 2 | TerminalState naming — one shared state or one per Invariant | **[POC-PROPOSED]** — one shared state, as in the guidance's own example |
| 3 | Is the §6 reading correct — deterministic conditions as workflow logic, PreNodes reserved for graded confidence? | **Needs confirmation.** It is the single most consequential design decision in this catalogue |
| 4 | PN-02 `communication-safety-confidence` — keep, or make message approval deterministic? | **Open** — depends on whether an honest confidence signal exists |
| 5 | INV-04 `synthetic-data-only` — runtime Invariant or startup assertion? | **Open** |
| 6 | Which of the 15 commitment points are governed in Phase 4 vs documented for later | **Open** — the requirements list 7 candidates |
| 7 | `max_monitor_gap_seconds` for a system that may be idle overnight | **Open** — audit check 1 can fail simply from low traffic |
| 8 | Who may authorise re-enablement after suspension | **Open** — the guidance requires a human transition but not an authority model |
| 9 | Pinned commit SHAs still current? | **Verify at the start of Phase 4** |
| 10 | Persistence approach for suspension state in the POC | **Open** — in-process is a known limitation; Redis is the production answer |

---

## 13. Related documents

- `COMMITMENT_POINTS.md` — where the gates go and what they guard
- `DECISION_TABLE.md` — the thresholds these constructs enforce
- `CLAIM_JOURNEY.md` — the workflow they sit inside
- `HUMAN_ESCALATION_POLICY.md` — what happens on the denial paths
- `GOVERNANCE_ENFORCEMENT.md` — how these constructs are enforced at runtime
- `../README.md` — the project overview

---

## Phase 4 status — this catalogue is now executable

Everything above was a declaration. As of Phase 4 it runs.

| Catalogue entry | Implemented as | File |
| --- | --- | --- |
| PN-01 | `vsl_core.constructs.PreNode` `automation-confidence` | `governance/policy.py` |
| INV-01 | `vsl_core.constructs.Invariant` `policy-in-force` | `governance/policy.py` |
| INV-02 | `vsl_core.constructs.Invariant` `automated-authority-limit` | `governance/policy.py` |
| INV-03 | `vsl_core.constructs.Invariant` `no-auto-approval-under-exclusion` | `governance/policy.py` |
| TerminalState | `vsl_core.constructs.TerminalState` `claim-automation-suspended` | `governance/policy.py` |
| Ledger | `vsl_core.ledger.VerbaLedger` over a hash-chained JSONL store | `governance/ledger.py` |
| Enforcement | `govern_automated_route(perform=...)` | `governance/gates.py` |
| Audit | `verify_integrity()` + `audit()` + CLI | `governance/audit_cli.py` |

Two changes this catalogue should record, both documented rather than silent:

1. **The thresholds moved here.** `DECISION_THRESHOLD`,
   `AUTOMATED_AUTHORITY_LIMIT_NZD` and the calibration error now live in
   `governance/policy.py`, as this catalogue said they should from Phase 4. The
   application reads them from governance rather than the other way round.

2. **The confidence floor is derived, not chosen.** The catalogue proposed a
   decision boundary of 0.80. The floor PN-01 actually enforces is **0.8148** —
   the confidence at which γ reaches the robust threshold of 1.1 at that
   boundary. The boundary is the business proposal; the floor is what robustness
   costs.

No mapping was changed. No construct was invented.

See `GOVERNANCE_ENFORCEMENT.md` for how each of these is enforced, what the
ledger records, which audit checks apply, and the limitations of this POC.
