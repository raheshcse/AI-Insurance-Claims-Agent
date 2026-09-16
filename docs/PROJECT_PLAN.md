# Project Plan — AI-Powered Insurance Claims Agent (POC)

**Document status:** Phase 0 foundation + Phase 1 (§21), Phase 2 (§22) and Phase 3 (§23) implementation records
**Source of truth:** `AI_Insurance_Claims_Agent_Technical_Assessment.docx` (Technical Assessment &
Phased POC Requirements). Where this plan and that document differ, the document wins.
**Governance source of truth:** *X-Verba — VSL Governance Spec for Agent Builds*,
Super Semantics, v1.0 — **supplied**. All governance terminology, constructs, ledger semantics
and audit rules come from that document. No X-Verba construct has been invented.

Anything in this plan not traceable to one of those two documents is marked **[ASSUMPTION]** or
**[POC-PROPOSED]** and listed in §20 for confirmation before implementation.

### Document set

This plan is the hub. The detail lives in companion documents:

| Document | Contents |
| --- | --- |
| `CLAIM_JOURNEY.md` | Target claim type, POC scope, end-to-end business journey, six official claim states, internal statuses, transition matrix |
| `DECISION_TABLE.md` | Threshold framework, the 17-row decision table, recommendation vs action classification, values needing approval |
| `SYNTHETIC_DATA_SPEC.md` | Five required datasets plus reference data — fields, relationships, examples, workflow use |
| `COMMITMENT_POINTS.md` | The CP-01…CP-15 catalogue: what commits, why, recommendation or action, gate placement |
| `HUMAN_ESCALATION_POLICY.md` | Escalation triggers, the three routes to a human, emergency and vulnerable-customer pathway |
| `GOVERNANCE_POLICY_CATALOGUE.md` | PreNodes, Invariants, TerminalState, ledger entries, audit checks, package install traps, known constraints |
| `ROUTING_MODEL.md` | Phase 3 escalation rule catalogue, precedence, claim-state transitions, Phase 4 mapping |
| `API.md` | API reference — endpoints, request/response, validation behaviour, examples |

---

## 1. Business objective

The insurer gets **controlled AI claims automation**: agents can act quickly, but important
actions remain subject to explicit business governance, human escalation and an auditable
decision trail.

Stated business objectives:

- Reduce time required to lodge and triage claims.
- Reduce repetitive administrative workload for claims employees.
- Improve consistency of early-stage claim assessment.
- Identify missing information and documents earlier.
- Improve routing of standard, complex and potentially risky claims.
- Provide faster and clearer customer communication.
- Maintain explicit human oversight for significant decisions.
- Create evidence of how governed AI decisions were made.

## 2. Business problem

Claims teams handle high volumes of repetitive work — collecting information, checking policy
details, reviewing documents, classifying claims, assessing complexity, routing work and
communicating status. During severe weather events these volumes rise sharply. The business
needs automation that improves speed and capacity **without removing human control over
high-impact decisions**, and without creating an unauditable black box.

## 3. POC scope

The first demonstration covers a single end-to-end journey:

```
Home Insurance → Storm Damage → FNOL → Information Collection → Policy Retrieval
  → Validation → Assessment → Risk Check → Governed Routing
  → Automated Workflow  OR  Human Review
```

In scope:

- Customer web journey for lodging and checking a storm-damage home claim.
- Conversational FNOL intake with a structured claim-information panel.
- Policy retrieval from a synthetic policy knowledge base.
- Completeness/consistency validation, classification, complexity, urgency, confidence.
- Fraud/risk indicator detection and escalation routing.
- Human review queue with escalation reasons and AI case summaries.
- X-Verba/VSL governance on the execution path, with an auditable ledger.
- Governance dashboard and claim detail views for claims staff.
- Demonstration scenarios A–D (§13) and the associated metrics.

## 4. Out of scope

- **Fully autonomous claim settlement** — explicitly excluded from Phase 1.
- Financial settlement or payment initiation (named as a *future* governance decision point).
- A formal **A2A protocol** implementation. The POC is graph-based multi-agent orchestration
  with shared state; it must not be marketed as A2A unless a real A2A protocol is introduced
  later. The label "A2B" is not to be used at all.
- Enterprise integrations with policy administration, claims management, CRM, document and
  communications systems (Phase 6 planning only).
- Enterprise identity and access management, production database/object storage, centralised
  monitoring, load/resilience testing (Phase 6 planning only).
- Any real customer, policy or claims data.

## 5. Target users

| Persona | Primary need | POC interaction |
| --- | --- | --- |
| Customer / Policyholder | Lodge a claim quickly and understand next steps | Web claim portal + conversational assistant |
| Claims Employee | Review AI-collected claims and handle escalations | Claims review console |
| Claims Manager | Monitor volume, automation and governance outcomes | Operations + governance dashboard |

## 6. Planned implementation phases

| Phase | Focus | Outcome |
| --- | --- | --- |
| 0 | Business & Governance Foundation | Claim journey, synthetic data, business rules, decision points, governance policies defined |
| 1 | Customer Claims Experience | Web UI and conversational FNOL workflow |
| 2 | Claims Intelligence | Policy retrieval, validation, classification, assessment |
| 3 | Risk & Human Escalation | Fraud/risk indicators, triage, human review queue |
| 4 | X-Verba Enforcement | PreNodes, Invariants, TerminalState and VerbaLedger on governed execution paths |
| 5 | Demonstration & Evaluation | Normal, low-confidence and hard-rule scenarios demonstrated and measured |
| 6 | Production Readiness | Security, persistence, observability, testing, enterprise integrations |

### Phase 0 — Business & Governance Foundation

**Objective:** translate the claims business process into an explicit, governable workflow.

Requirements:

- Define the target claim type: Home Insurance / Storm Damage.
- Define synthetic customer, policy, claim, document and historical-claim datasets.
- Define claim states: **Draft, Submitted, Information Required, Assessment, Human Review,
  Approved/Completed**.
- Define business thresholds for low/high complexity, confidence, value and escalation.
- Identify commitment points that require governance before the action occurs.
- Define which outcomes are recommendations versus actions.
- Define the human escalation policy and emergency/vulnerable-customer path.

**Exit criteria:** a documented claim journey, decision table, synthetic dataset and governance
policy catalogue are approved for POC build.

#### Phase 0 deliverables — status

| # | Required artefact | Where it lives | Status |
| --- | --- | --- | --- |
| 1 | Claim journey | `CLAIM_JOURNEY.md` §2 | **Documented** |
| 2 | Decision table | `DECISION_TABLE.md` §4 | **Documented** — thresholds pending approval |
| 3 | Synthetic dataset definition | `SYNTHETIC_DATA_SPEC.md` | **Defined** — data not yet generated |
| 4 | Claim state model | `CLAIM_JOURNEY.md` §3–§6 | **Documented** |
| 5 | Business threshold framework | `DECISION_TABLE.md` §2 | **Documented** — all values [POC-PROPOSED] |
| 6 | Commitment point catalogue | `COMMITMENT_POINTS.md` | **Documented** |
| 7 | Recommendation vs action classification | `DECISION_TABLE.md` §3 | **Documented** |
| 8 | Human escalation policy | `HUMAN_ESCALATION_POLICY.md` §1–§3 | **Documented** |
| 9 | Emergency / vulnerable-customer path | `HUMAN_ESCALATION_POLICY.md` §4 | **Documented** |
| 10 | X-Verba governance policy catalogue | `GOVERNANCE_POLICY_CATALOGUE.md` | **Documented** |

#### Phase 0 summary of decisions

- **Target claim type:** Home Insurance / Storm Damage, FNOL through governed routing. Damage
  boundary, jurisdiction (NZ) and currency (NZD) are [POC-PROPOSED].
- **Claim states:** the six official states from the requirements, unchanged. Eleven *internal
  workflow statuses* are defined and kept explicitly distinct from them.
- **Thresholds:** a full framework for complexity, confidence, risk, value and urgency. The
  confidence gate follows the VSL Gamma model — `DECISION_THRESHOLD = 0.80` [POC-PROPOSED]
  against the library's `ROBUST_GAMMA_DEFAULT_THRESHOLD = 1.1`, giving an effective automation
  floor of `p ≥ 0.815`. The automated authority limit of NZD 20,000 [POC-PROPOSED] is the one
  threshold high confidence cannot override.
- **Commitment points:** fifteen identified (the requirements named seven candidates), each
  classified as recommendation or action with its gate placement.
- **Governance:** one PreNode confirmed plus one candidate; three Invariants confirmed plus one
  candidate; one TerminalState. Every gate declares `OUTPUT_LAYER` and therefore derives
  assurance **LOW** — stated plainly, per the guidance, rather than disguised.
- **Design call needing sign-off:** deterministic business conditions (missing information,
  value, complexity, risk bands, emergency, vulnerability) are handled as **workflow logic**
  whose side effects are gated, not as PreNodes — because a PreNode monitor returns a graded
  `GammaEstimate` and these are binary facts. See `GOVERNANCE_POLICY_CATALOGUE.md` §6.

**Phase 0 completion status:** all ten required artefacts are documented. Phase 0 cannot be
declared *complete* until the business approves the threshold values and resolves the open
questions in §20 — in particular the automated authority limit, the confidence boundary and the
vulnerable-customer definition. The documentation is ready for that review.

### Phase 1 — Customer Claims Experience

**Objective:** let a customer initiate and complete an initial claim conversation through a
professional web UI.

- Landing page with *Start New Claim* and *Check Existing Claim*.
- Conversational claims assistant.
- Structured claim-information panel updated during the conversation.
- Claim reference generation.
- Document upload area.
- Visible status and next-step messaging.
- Human assistance option.
- Responsive, desktop-first design suitable for an insurer demonstration.

**Exit criteria:** a customer can complete a representative storm-damage FNOL journey in the
browser.

**Status: implemented.** Full record in §21. Two requirements were deliberately deferred and
are recorded there as limitations: *Check Existing Claim* (the API endpoint exists, the screen
does not) and document upload (the FNOL records whether photos exist; it does not accept files).

### Phase 2 — Claims Intelligence

**Objective:** turn unstructured customer input into a structured, validated claim assessment.

- Policy retrieval against the synthetic policy knowledge base.
- Relevant coverage, conditions, excess and exclusions surfaced as context.
- Missing-information detection.
- Claim classification.
- Complexity and urgency assessment.
- Confidence score and recommendation.
- Automated claim summary for the employee console.

**Exit criteria:** a submitted claim produces a structured claim record, policy context,
completeness result, classification and initial triage recommendation.

**Status: implemented.** Full record in §22. LangGraph orchestrates five specialist agents over
shared state and produces a structured claims intelligence result. The result is a
**recommendation**: no claim state changes, no customer is contacted, nothing is approved,
declined or settled.

### Phase 3 — Risk & Human Escalation

**Objective:** ensure potentially complex or risky cases reach the right human workflow.

- Fraud/risk indicator detection.
- High-value claim flagging.
- Low-confidence escalation.
- Policy exception escalation.
- Vulnerable-customer and emergency escalation paths.
- Human review queue with escalation reason.
- Claims employee review screen with AI-generated case summary.

**Exit criteria:** at least one normal automated route and one meaningful human-escalation route
can be demonstrated.

**Status: implemented.** Full record in §23, rule catalogue in `ROUTING_MODEL.md`. Twelve
escalation rules route every analysed claim to the automated path, human review or
information required; escalated claims move to Human Review and appear in a priority-ordered
queue with structured reasons. Routing can never reach Approved/Completed — only a
reviewer's action can.

### Phase 4 — X-Verba Governance Enforcement

**Objective:** make governance an executable control layer, not a dashboard-only feature.

- Governance layer separated from model logic and application logic.
- PreNode gates for soft decisions such as confidence and automation eligibility.
- Invariant checks for hard business rules that must never be bypassed.
- Fallback to human review when a PreNode denies automation.
- TerminalState when an Invariant is violated.
- VerbaLedger for hash-chained, append-only decision evidence.
- Governed side effects occur only after the required gates succeed.
- Every governed decision has a traceable decision ID and causal ledger relationship.
- Governance dashboard showing approved, denied, escalated and suspended outcomes.

**Exit criteria:** a live demonstration proves X-Verba can allow an action, reroute an action to
human review, and hard-stop an action.

### Phase 5 — Demonstration & Evaluation

- Scenario A: straightforward storm claim → governed automated route.
- Scenario B: low-confidence or incomplete claim → human queue.
- Scenario C: hard business-rule violation → Invariant failure and automation stop.
- Governance trace shown for each scenario.
- Measure processing time, automation rate, escalation rate and governance outcomes.
- Capture screenshots and a concise executive demonstration flow.

**Exit criteria:** stakeholders can see the complete customer journey and understand exactly
where and why AI is controlled.

### Phase 6 — Production Readiness

- Enterprise identity and access management.
- Persistent governance/suspension state rather than process-local state.
- Production-grade database and object storage.
- Centralised monitoring and alerting.
- Security, privacy and data-retention controls.
- Load, resilience and failure testing.
- Model evaluation, prompt/version management and regression testing.
- Enterprise integrations with claims, policy, CRM and communications systems.

**Exit criteria:** a production-readiness backlog, risk register and integration plan exist.

### Recommended build order (from the assessment)

1. Synthetic insurance data and the Home/Storm policy knowledge base.
2. Web customer claim flow.
3. LangGraph state and basic Intake Agent.
4. Policy, Validation and Assessment agents.
5. Fraud/Risk and Human Review flows.
6. X-Verba policy, gates and ledger around real commitment points.
7. Governance dashboard and audit trace.
8. Test scenarios for pass, soft denial and hard invariant violation.
9. Package with a polished demo script and measurable outcomes.

## 7. Functional requirements

| ID | Requirement | Acceptance intent | Phase |
| --- | --- | --- | --- |
| FR-01 | Claim initiation | Customer can start a new claim and provide policy/incident details | 1 |
| FR-02 | Conversational intake | AI asks relevant questions and collects missing information without unnecessarily repeating questions | 1 |
| FR-03 | Policy retrieval | System retrieves relevant policy context from approved policy content | 2 |
| FR-04 | Information validation | System identifies missing, incomplete or inconsistent claim information | 2 |
| FR-05 | Claim classification | System classifies the claim by insurance type and incident category | 2 |
| FR-06 | Claim triage | System estimates complexity, urgency and recommended route | 2 |
| FR-07 | Risk indicators | System identifies potential fraud/risk indicators without accusing the customer | 3 |
| FR-08 | Human escalation | System routes appropriate claims to a human review queue | 3 |
| FR-09 | Claim summary | System generates a concise structured summary for claims employees | 2–3 |
| FR-10 | Claim status | Customer can see the current claim stage and next step | 1 |
| FR-11 | Governance visibility | Claims staff can inspect the governance result and reason | 4 |
| FR-12 | Audit trail | Governed decisions and relevant outcomes are recorded for later verification | 4 |

*(Phase column is the mapping implied by the phase requirements; confirm if it differs from
business expectation.)* **[ASSUMPTION]**

## 8. Non-functional requirements

| Requirement | POC expectation |
| --- | --- |
| Security | Role-based access, secure secrets, least-privilege system access, protected customer information |
| Auditability | Governed decisions traceable to a decision ID and causal audit entries |
| Reliability | A governance denial must not silently disappear — the workflow must route or stop explicitly |
| Explainability | Employee-facing screens show why a claim was routed or escalated |
| Performance | Interactive customer interactions feel responsive; long-running work exposes status |
| Privacy | Synthetic data for the POC; production design defines retention, access and handling |
| Maintainability | Policy declarations, enforcement and model logic remain separated |
| Testability | Normal, denial, invariant violation, audit and restart/recovery cases have automated tests |

## 9. Proposed UI screens

| ID | Screen | Contents |
| --- | --- | --- |
| UI-01 | Customer Landing | Start New Claim; Check Existing Claim; insurer branding and trust messaging |
| UI-02 | Claims Assistant | Conversation panel; claim information panel; document upload; human assistance action |
| UI-03 | Claim Assessment | Classification; complexity; risk; confidence; missing information; recommended route |
| UI-04 | Human Review Queue | Claim ID; escalation reason; AI summary; risk indicators; review action |
| UI-05 | Governance Dashboard | Governed decisions; human escalations; Invariant violations; suspended actions; audit/ledger trace |
| UI-06 | Claim Detail | Customer/claim details; timeline; documents; AI decisions; governance events; human actions |

UI-01 and UI-02 are customer-facing; UI-03 to UI-06 are claims-staff-facing.

## 10. Proposed AI agents

| Agent | Primary responsibility | Typical output |
| --- | --- | --- |
| Intake Agent | Understand the customer conversation and collect structured claim information | Structured claim information |
| Policy Agent | Retrieve and interpret relevant policy context | Relevant policy context |
| Validation Agent | Check completeness, consistency and required information | Validation result + missing items |
| Assessment Agent | Classify the claim, determine complexity, urgency and confidence | Classification + triage recommendation |
| Fraud & Risk Agent | Identify risk indicators and recommend investigation/escalation | Risk level + indicators |
| Communication Agent | Prepare approved customer-facing messages and status updates | Customer-safe communication |

Design constraints:

- Each agent is a **node in the LangGraph state graph**; agents do not call each other directly.
- Agent outputs are **recommendations** until a governance gate converts them into an action.
- The LLM is never the business authority — policy content, validation rules and human review
  decide outcomes.
- The LLM provider is accessed through a provider-independent interface; OpenAI is the first
  implementation.

## 11. Proposed LangGraph workflow

Orchestration model: **LangGraph-based multi-agent orchestration with shared state.** Each
specialist is a node; the graph controls sequencing and conditional routing. Agent-to-agent
interaction exists only conceptually, through shared state.

Target graph shape for the first journey:

```
                    ┌────────────────────────────────────┐
   START ─────────► │ Intake Agent (conversational FNOL) │
                    └──────────────┬─────────────────────┘
                                   │ structured claim info
                                   ▼
                         ┌──────────────────┐
                         │   Policy Agent   │  synthetic policy KB
                         └────────┬─────────┘
                                  ▼
                        ┌────────────────────┐
                        │ Validation Agent   │
                        └─────────┬──────────┘
                     incomplete   │   complete
              ┌───────────────────┴──────────────┐
              ▼                                  ▼
    ┌──────────────────────┐          ┌────────────────────┐
    │ Information Required │          │ Assessment Agent   │
    │ (back to customer)   │          └─────────┬──────────┘
    └──────────────────────┘                    ▼
                                      ┌────────────────────┐
                                      │ Fraud & Risk Agent │
                                      └─────────┬──────────┘
                                                ▼
                                   ┌───────────────────────────┐
                                   │  Governance gate (Phase 4)│
                                   │  PreNode + Invariants     │
                                   └───┬───────────┬───────┬───┘
                            allowed    │   denied   │       │ invariant violated
                                       ▼            ▼       ▼
                          ┌───────────────────┐ ┌──────────────┐ ┌──────────────────┐
                          │ Automated Route   │ │ Human Review │ │ TerminalState    │
                          │ + Communication   │ │ Queue        │ │ automation       │
                          │   Agent           │ │              │ │ suspended        │
                          └─────────┬─────────┘ └──────┬───────┘ └────────┬─────────┘
                                    └─────────────┬────┘                  │
                                                  ▼                       ▼
                                                 END              human re-enablement
```

Shared state (to be defined in Phase 1, extended per phase) is expected to carry: claim
reference, claim state, customer/policy identifiers, collected claim fields, retrieved policy
context, validation result and missing items, classification, complexity, urgency, confidence,
risk level and indicators, routing decision, governance outcomes and decision IDs, and the
conversation transcript. **[ASSUMPTION — field list is a proposal, not stated in the document.]**

Claim states: **Draft → Submitted → Information Required → Assessment → Human Review →
Approved/Completed.**

## 12. Planned X-Verba / VSL governance integration

> **Superseded by `GOVERNANCE_ENFORCEMENT.md` (Phase 4).** This section is the *plan*, kept as
> written so the plan can be compared against what was built. Where the two disagree, the
> enforcement document and the code are correct. The §24 record lists what changed and why.

Governance is a **separate layer on the execution path**, not an observability dashboard, and is
kept apart from both model logic and application logic. The `governance/` directory is reserved
from Phase 0 and implemented in Phase 4.

> Detailed catalogue: **`GOVERNANCE_POLICY_CATALOGUE.md`**. This section is the summary.

### The five constructs (from the supplied VSL spec)

| Construct | Meaning | On failure | This POC |
| --- | --- | --- | --- |
| PreNode | Soft gate — "are we confident enough?" | `AutomationDeniedException` → reroute via Fallback | `automation-confidence` (PN-01) |
| Invariant | Hard rule — "is this ever acceptable?" | `InvariantViolation` → TerminalState | `policy-in-force`, `automated-authority-limit`, `no-auto-approval-under-exclusion` |
| TerminalState | Automation stops; no automated way out | — | `claim-automation-suspended` |
| VerbaLedger | Hash-chained, append-only decision record | `LedgerIntegrityError` | `data/ledger.jsonl` |
| Specification | Versioned, proofed, authority-approved bundle | `ValueError` at construction | Draft until thresholds are approved |

**Assurance is derived, never asserted.** Two facts are supplied — F1 (does the check run before
commitment?) and F2 (does it touch the mechanism producing the output?) — and VSL computes the
level. Every gate here is `OUTPUT_LAYER` (F1 = True, F2 = NONE) and derives **LOW**. That is
correct: output-layer control blocks a bad action without changing how the model decides. Only a
formation-layer change reaches HIGH, and this POC does not make one. This is stated in the
demonstration rather than disguised.

**Choosing between the first two:** if a legitimate business reason to proceed anyway is
imaginable, it is a PreNode. If proceeding anyway is always wrong, it is an Invariant.

### Packages

The spec's decision rule: the agent **is** a LangGraph `StateGraph`, so both packages are
needed — **VSL-Core** (primitives, always required) and **VSL-LangGraph** (the `StateGraph`
adapter). Three installation traps are recorded in `GOVERNANCE_POLICY_CATALOGUE.md` §1.1: the
PyPI name `vsl-core` is an unrelated stub (the distribution is `super-semantics-vsl`, the import
is `vsl_core`); there are no releases, so pin a commit SHA; and VSL-LangGraph's stale dependency
URL forces a separate `--no-deps` install.

No X-Verba constructs beyond the five above are to be invented.

### Governance decision points

The assessment named seven candidates; Phase 0 expanded them into a fifteen-entry catalogue —
`COMMITMENT_POINTS.md`. The principal gate is **CP-11, taking the automated route**; every
claim-state write (CP-09) and every outbound customer message (CP-10) is also gated.

Each gate is placed **immediately before** the governed side effect. The spec is explicit that
this ordering *is* the pre-commitment property, not a style preference: the side effect is the
last thing the caller does and is unreachable from any denial path.

The gate sequence in `gates.py`:

```
MONITOR (every request) → suspension check → PreNodes → Invariants → VERIFICATION
                                                                      ↓
                                                             ┃ SIDE EFFECT ┃
```

### Governance outcomes

Three operationally distinct outcomes must be preserved and must not be collapsed into a
pass/fail pair:

| Outcome | Behaviour | Workflow result |
| --- | --- | --- |
| **PreNode denial** | Ordinary, expected soft-gate denial | Fallback → Human Review Queue (a real workflow state). Verification **SUFFICIENT** |
| **Invariant violation** | Hard business rule breached | Automated execution stops. Verification **INSUFFICIENT** |
| **Invariant violation naming a TerminalState** | Controlled automation stop | TerminalState entered; automation suspended until human re-enablement |

**The trap that breaks audits.** The spec forbids writing INSUFFICIENT on an ordinary PreNode
denial: INSUFFICIENT means governance itself failed, and audit check 4 then demands a
SPECIFICATION_UPDATE for every one — so the audit fails permanently on normal traffic. A PreNode
correctly denying a low-confidence claim is governance *working* → SUFFICIENT. In a claims
system, low-confidence claims are routine traffic, so getting this wrong would fail the audit
every day.

### Auditability

- Every governed decision carries a traceable `decision_id`.
- The VerbaLedger is append-only and hash-chained, at `data/ledger.jsonl` with `fsync=True`.
- **`caused_by` is mandatory on every entry.** Without it, `audit()` falls back to a "same
  identity, later timestamp" heuristic that, under the concurrency of a real claims queue, can
  match an unrelated PRE_NODE and report a **false pass**.
- Five audit checks must pass: no monitoring gaps; drift-flagged MONITOR has a PRE_NODE;
  PRE_NODE has a VERIFICATION; INSUFFICIENT VERIFICATION has a SPECIFICATION_UPDATE; TERMINAL
  has a HUMAN_AUTHORISED_TRANSITION.
- **`verify_integrity()` and `audit()` answer different questions** — whether records were
  edited, versus whether they describe a governed process. A tampered payload gives
  `integrity=False` while all five checks still pass. Run both.
- The governance dashboard (UI-05) surfaces approved, denied, escalated and suspended outcomes.
- X-Verba's Γ (static coverage ratio from `x-verba scan`) and VSL-Core's Gamma (runtime ratio
  judged against 1.1) are different quantities. They must not be conflated in the dashboard.

## 13. Human-in-the-loop requirements

- **Human review is a real workflow state**, not a UI label or a log entry.
- A PreNode denial falls back to human review rather than failing the workflow.
- An Invariant violation suspends automation; a human must re-enable it.
- The human review queue shows the claim ID, escalation reason, AI-generated case summary and
  risk indicators, and offers a review action.
- A **human assistance option** is available to the customer at any point in the assistant UI.
- Dedicated escalation paths exist for: low confidence, incomplete information, high-value
  claims, policy exceptions, fraud/risk indicators, **vulnerable customers** and **emergencies**.
- Fraud/risk findings are framed as indicators for investigation — never as accusations.
- High-impact decisions remain human-controlled in the early phases; no autonomous settlement.

### Demonstration scenarios

| Scenario | Example | Expected governed outcome |
| --- | --- | --- |
| A — Normal Claim | Storm damages roof; sufficient information; low risk; confidence clears the business threshold | PreNode passes → invariants pass → automated route proceeds |
| B — Low Confidence | Insufficient confidence or incomplete required information | PreNode denies → fallback → Human Review Queue |
| C — Hard Rule | Proposed action violates a non-negotiable rule, e.g. exceeding automated authority threshold | Invariant violation → TerminalState → automation suspended → human re-enablement |
| D — Potential Risk | Inconsistent or unusual indicators in the claim | Fraud/Risk Agent flags → governed routing → specialist review |

## 14. Synthetic data requirements

**Synthetic data only, at every phase.** No real customer, policy or claim data.

Datasets to be produced in `data/synthetic/`:

- **Customers** — policyholder records, including at least one vulnerable-customer case.
- **Policies** — home insurance policies with coverage, conditions, excess and exclusions,
  including at least one with an exclusion relevant to storm damage.
- **Claims** — in-flight claims across the defined claim states.
- **Documents** — placeholder claim documents/photos for the upload flow.
- **Historical claims** — prior claim history to support risk indicators.
- **Policy knowledge base** — Home/Storm policy content for retrieval by the Policy Agent.
- **Risk rules** — the risk indicator definitions used by the Fraud & Risk Agent.

The data must be rich enough to drive scenarios A–D, including a claim that breaches an
automated authority threshold and a claim with deliberately missing information.

Exact file formats and record schemas are a Phase 0 follow-up. **[ASSUMPTION — not specified in
the document.]**

## 15. Testing strategy

Automated tests are required for: **normal, denial, invariant violation, audit and
restart/recovery** cases.

| Layer | Coverage |
| --- | --- |
| Agent unit tests | Each agent node's output shape and behaviour against synthetic inputs |
| Graph tests | Routing decisions, conditional edges, claim state transitions |
| Governance tests | PreNode pass, PreNode denial → human review fallback, Invariant violation → stop, Invariant violation → TerminalState |
| Audit tests | Ledger causal ordering, hash-chain integrity, PreNode denial distinguished from governance failure |
| Restart/recovery tests | Workflow behaviour across restart; suspension state survives (process-local state is a known POC limitation to be productionised in Phase 6) |
| Scenario tests | End-to-end scenarios A–D |
| API tests | FastAPI endpoint contracts |
| UI tests | Customer FNOL journey and employee review journey |

Tests live in `tests/` and must include the denial paths explicitly — a governance layer tested
only on the happy path is not evidence of governance.

## 16. Success metrics

- Initial claim-processing time reduction.
- Customer effort / number of interaction steps.
- Percentage of eligible claims routed automatically.
- Percentage of claims correctly escalated to human review.
- Human claims workload reduction for repetitive intake/triage tasks.
- Customer satisfaction for the POC journey.
- Governance pass/deny/terminal outcomes.
- Audit completeness and integrity of governed decision traces.

## 17. Key risks and controls

| Risk | Control |
| --- | --- |
| Incorrect AI interpretation | Policy retrieval, validation and human escalation; never treat the LLM as the business authority |
| Over-automation | Explicit PreNodes and Invariants; high-impact decisions stay human-controlled in Phase 1 |
| Fraud false positives | Flag for investigation rather than accuse; require specialist review |
| Governance bypass | Gates immediately before governed side effects; test denial paths |
| Audit gaps | Record causal relationships; run governance audit and integrity verification |
| Restart / multi-worker state | Productionise suspension state outside process memory; re-derive state from the ledger |
| Sensitive customer data | Synthetic POC data; enterprise privacy/security controls before production |

## 18. Future production considerations

Carried from Phase 6 and the risk register:

- Enterprise identity and access management; role-based access for customer, employee, manager.
- Persistent governance and suspension state outside process memory, re-derivable from the
  ledger, safe across restarts and multiple workers.
- Production-grade database and object storage for claims, documents and the ledger.
- Centralised monitoring, alerting, agent tracing and governance metrics.
- Security, privacy and data-retention controls for real customer data.
- Load, resilience and failure testing.
- Model evaluation, prompt/version management and regression testing.
- Enterprise integrations: policy administration, claims management, CRM, document management,
  communications and identity systems.
- A production-readiness backlog, risk register and integration plan.

## 19. Proposed full project structure (target, end of Phase 5)

> **The structure as actually built is in the root `README.md` §19.** This remains the Phase 0
> target, kept for comparison. "Only the Phase 0 skeleton exists today" was true when written;
> Phases 1–4 are now built.

Only the Phase 0 skeleton exists today. This is the shape it is expected to grow into:

```
AI_Insurance_Claims_Agent/
├── frontend/                      # React app
│   └── src/
│       ├── pages/                 # UI-01 … UI-06
│       ├── components/
│       └── api/                   # Backend client
├── backend/
│   ├── app/                       # FastAPI app, routers, schemas, settings
│   ├── agents/                    # Intake, Policy, Validation, Assessment, Fraud/Risk, Communication
│   ├── graph/                     # StateGraph definition, state model, nodes, conditional routing
│   ├── llm/                       # Provider-independent LLM interface (OpenAI first)
│   └── services/                  # Policy retrieval, claim repository, document handling
├── governance/                    # Layout MANDATED by the VSL spec — flat, four files
│   ├── __init__.py
│   ├── policy.py                  # WHAT is governed. Declarations only. Imports only vsl_core
│   ├── gates.py                   # HOW it is enforced. The single call site
│   ├── ledger.py                  # PROOF. Hash-chained audit trail
│   └── audit_cli.py               # Verify / audit / certify. Exit 1 on failure
├── data/
│   ├── ledger.jsonl               # Append-only VerbaLedger. GITIGNORED
│   └── synthetic/                 # customers, policies, claims, documents, history, policy KB, risk rules
├── tests/                         # unit / graph / governance / audit / scenario / api
├── docs/                          # This plan + the five Phase 0 foundation documents + demo script
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

The `governance/` layout is **not a proposal** — it is prescribed by the supplied VSL spec,
along with three import rules that must be enforced: `policy.py` imports only `vsl_core`;
`backend/app.py` calls `governance.gates`, never the model directly for a governed action; and
nothing imports `gates.py` except the backend entry point. Reading order for a newcomer is
policy → gates → ledger.

The `backend/` and `frontend/` shapes are **[ASSUMPTION]** — the sources require only the
three-layer split.

## 20. Assumptions and open questions

### Assumptions made in this plan

1. The three-layer structure is realised as `frontend/`, `backend/` (with `agents/` and
   `graph/`) and `governance/`, with `data/`, `tests/` and `docs/` alongside.
2. FastAPI, React, Python and OpenAI are the concrete technology choices; the assessment names
   layers and LangGraph/X-Verba but not these specific technologies.
3. The FR-to-phase mapping in §7 is inferred from the phase requirement lists.
4. The shared-state field list in §11 is a proposal, not a stated requirement.
5. Synthetic data file formats and record schemas are open.
6. The target structure in §19 is a proposal for later phases.
7. Development environment is Windows/PowerShell; setup commands will be written accordingly.

8. Claim states are the six official ones only; eleven internal workflow statuses are added and
   kept explicitly distinct, as the assessment permits.
9. Jurisdiction New Zealand, currency NZD; the storm-damage boundary (dwelling, immediate
   structures, consequential contents) is a Phase 0 proposal.
10. Deterministic business conditions are handled as workflow logic with gated side effects
    rather than as PreNodes — see `GOVERNANCE_POLICY_CATALOGUE.md` §6.

Resolved since the first Phase 0 pass: the X-Verba/VSL spec has been supplied, so package
names, install traps, construct semantics, ledger entry types, the five audit checks, the
SUFFICIENT/INSUFFICIENT rule, the `caused_by` requirement, the governance directory layout, the
import rules and the LangGraph wiring are no longer assumptions — they are sourced.

### Proposed values requiring business approval

Full list with rationale: `DECISION_TABLE.md` §7. The ones that change system behaviour most:

| Value | Proposed | Effect if wrong |
| --- | --- | --- |
| `DECISION_THRESHOLD` | 0.80 → effective floor `p ≥ 0.815` | Too high: nothing automates. Too low: weak claims close unseen |
| **Automated authority limit** | NZD 20,000 | The hard stop. Sets what automation may never decide |
| High-value review threshold | > NZD 10,000 | Controls human workload |
| Low-value automation band | ≤ NZD 5,000 | Defines "straightforward" |
| Risk banding | 1 indicator = Medium, ≥ 2 or severe = High | Sets the false-positive rate against real customers |
| Calibration error | 0.10 | Declares how much the confidence number can be trusted |
| Emergency signals | `HUMAN_ESCALATION_POLICY.md` §4.1 | Safety-critical |
| Vulnerability definition | `HUMAN_ESCALATION_POLICY.md` §4.2 | Must come from the insurer's own policy |
| Mandatory FNOL fields | `SYNTHETIC_DATA_SPEC.md` §4.2 | Defines completeness |

### Open questions requiring business confirmation before implementation

1. **Threshold values** — every number above. Nothing here is an insurer-approved rule yet.
2. **Is the PreNode-vs-workflow-logic split correct?** Deterministic conditions are treated as
   workflow logic whose side effects are gated, with PreNodes reserved for graded confidence.
   This is the most consequential design decision in the Phase 0 documentation.
3. **Which of the fifteen commitment points are governed in Phase 4** versus documented for
   later. The assessment named seven candidates.
4. **TerminalState granularity** — one shared `claim-automation-suspended` (proposed), or one
   per Invariant.
5. **Vulnerable-customer definition and emergency guidance content** — both must come from the
   insurer. The AI must not improvise safety advice.
6. **Who may re-enable automation** after a suspension. The spec requires a human-authorised
   transition but defines no authority model.
7. **`max_monitor_gap_seconds`** for a system that may sit idle overnight — audit check 1 can
   fail from low traffic alone.
8. **Persistence for suspension state in the POC** — in-process does not survive a restart or a
   second worker; Redis plus ledger re-derivation is the production answer (Phase 6).
9. **Whether uploaded documents are analysed** by an agent or only stored and date-checked.
   Determines whether a vision/OCR step exists at all.
10. **Success metric baselines** — what is the comparison point for "reduction"?
11. **Claim reference format** — `CLM-2026-######` proposed.
12. **Pinned commit SHAs** for VSL-Core and VSL-LangGraph — re-verify at the start of Phase 4.
13. **PN-02 `communication-safety-confidence`** — keep as a PreNode, or make message approval
    deterministic? Only keep it if an honest confidence signal can be defined.
14. **Synthetic data volumes and formats** — `SYNTHETIC_DATA_SPEC.md` §8.

---

## 21. Phase 1 implementation record — Customer Claims Experience

**Status: complete.** Built 2026-09-13.
Architecture delivered: **React → FastAPI → synthetic claim data.** No LangGraph, no agents, no
governance runtime.

### 21.1 Objective

Allow a synthetic customer to report storm damage through a professional web interface and
successfully lodge a claim, producing a claim record with a claim ID and the state **Submitted**.

### 21.2 Implemented functionality

| Area | Delivered |
| --- | --- |
| Customer journey | Five-screen wizard: Start → Your details → Property → Storm damage → Review, then a confirmation screen |
| Claim creation | `POST /api/claims` creates a claim record, allocates a reference and sets the state |
| Claim lookup | `GET /api/claims/{id}` reads a lodged claim back |
| Validation | Client-side per step, authoritative server-side on submission |
| Error handling | Customer-safe messages for invalid input, backend unavailable, submission failure and unexpected errors |
| Synthetic data | 5 customers, 5 policies seeded in `data/synthetic/` |
| Tests | 27 backend (pytest), 10 frontend (vitest) — all passing |
| API documentation | `API.md` plus FastAPI's generated `/docs` |

### 21.3 Customer journey

```
Landing ──► Your details ──► Property ──► Storm damage ──► Review ──► Submit
   │            │               │              │              │          │
   │         name, email,   loss address,  date of loss,   full       POST
   │         phone, policy  habitable,     description,    summary,   /api/claims
   │         number,        temporary      damaged items,  edit any      │
   │         contact pref   accommodation  8 further Qs    section       ▼
   │                                                                Confirmation
   │                                                            claim ID + status
   └── progress indicator from step 2 onward; Back available throughout
```

The Review screen shows every answer with a *Change …* link per section, and re-validates all
three data steps on submit — a customer who edits an earlier step cannot slip an invalid value
through.

### 21.4 Frontend components

| File | Role |
| --- | --- |
| `src/App.jsx` | Shell: masthead, main, footer. Fictional insurer branding ("Northwind Home Insurance") |
| `src/claim/ClaimWizard.jsx` | Step state machine, validation gating, submission, error state |
| `src/claim/claimForm.js` | Form shape, API payload mapping, emergency-signal helper |
| `src/claim/validation.js` | Client-side rules, mirroring the backend |
| `src/claim/steps/StartStep.jsx` | Landing: what happens next, what you will need |
| `src/claim/steps/CustomerStep.jsx` | Name, email, phone, policy number, contact preference |
| `src/claim/steps/PropertyStep.jsx` | Loss address, habitability, temporary accommodation |
| `src/claim/steps/DamageStep.jsx` | Date/time, description, repeatable damaged items, 8 further questions, safety notice |
| `src/claim/steps/ReviewStep.jsx` | Per-section summaries with edit links |
| `src/claim/steps/ConfirmationStep.jsx` | Claim reference, status pill, next step, summary |
| `src/components/FormControls.jsx` | Field, TextInput, TextArea, Select, YesNo, CheckboxGroup, Alert |
| `src/components/ProgressSteps.jsx` | Step indicator |
| `src/api/client.js` | The only place the UI talks to the backend |
| `src/styles.css` | Hand-written stylesheet — no UI framework dependency |

### 21.5 Backend APIs

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness, so the UI can tell "backend down" from "form invalid" |
| `POST` | `/api/claims` | Validate → allocate reference → build record → persist → return claim |
| `GET` | `/api/claims/{claim_id}` | Return the stored claim, or a customer-safe 404 |

Module layout:

```
backend/app/
├── main.py                     app, CORS, three exception handlers
├── config.py                   environment-driven settings
├── errors.py                   ClaimsAppError hierarchy with customer-safe messages
├── api/health.py               health router
├── api/claims.py               claims router
├── api/dependencies.py         wiring — the one place the repository is chosen
├── schemas/claim.py            request/response models
├── domain/claim_state.py       ClaimState, InternalStatus, ALLOWED_TRANSITIONS
├── domain/reference.py         claim reference generation
├── services/claim_service.py   the single claim-creation call site
└── repositories/claim_repository.py   Protocol + in-memory + JSONL
```

### 21.6 Synthetic data usage

`data/synthetic/customers.jsonl` (5 records) and `data/synthetic/policies.jsonl` (5 records),
generated to the Phase 0 spec. Every policy carries a `scenario_note` naming the decision-table
row it supports: clean cover for Scenario A, a lapsed policy for INV-01, an exclusion-bearing
policy for INV-03, high sums insured for the authority-limit Invariant, and a recent inception
for the risk indicators.

**Phase 1 does not read this data.** The FNOL comes from the customer; policy retrieval is
Phase 2. It exists so a demonstrator can type a real synthetic policy number and so Phase 2 has
data waiting. Claims, documents, historical claims, policy wordings and risk rules are specified
but not generated — each is created by the phase that consumes it.

Lodged claims are written to `data/claims/claims.jsonl` (gitignored runtime state).

### 21.7 Claim-state transition

Phase 1 implements exactly one transition: **Draft → Submitted**.

Draft is conceptual — it is the claim being filled in, and is not persisted. On submission the
service asserts the transition against `ALLOWED_TRANSITIONS` before writing, so the state model
stays authoritative rather than implicit. The full six-state map is declared in
`domain/claim_state.py` for Phase 2+ to extend; every other transition is unreachable today.

`internal_status` is `null` on a submitted claim: no internal status applies until something has
processed it.

### 21.8 Validation

| Layer | What it checks |
| --- | --- |
| Frontend, per step | Required fields, email format, phone and postcode length, at least one damaged item with area/item/description, description ≥ 20 chars, date of loss not in the future, no negative estimates |
| Frontend, on submit | Re-validates all three data steps and jumps back to the first with a problem |
| Backend, Pydantic | The same rules, authoritatively, plus `extra="forbid"` so an unknown field fails loudly |
| Backend, handler | Converts Pydantic errors into per-field plain-language messages |

Deliberately absent: completeness against a policy, cross-field consistency, plausibility. Those
need judgement and belong to the Validation Agent in Phase 2.

### 21.9 Testing

**Backend — 27 tests, all passing** (`tests/backend/`): valid submission returns 201; claim ID
format; initial state is Submitted; the claim is *not* moved to Assessment; response structure;
persistence and read-back with no derived AI fields present; reference uniqueness across
submissions; missing field, empty body, invalid email, zero damaged items, future date of loss,
too-short description all rejected; a rejected submission creates no claim; errors leak no
internal detail; unknown claim returns a customer-safe 404; health endpoint. Plus the state
model: the six official states and no others, the Phase 1 transition allowed, lifecycle
shortcuts refused, official states disjoint from internal statuses, and PreNode denial distinct
from automation suspension.

**Frontend — 10 tests, all passing** (`frontend/src/__tests__/`): landing renders with a start
action; the customer can move through every step; empty required fields block progress with
messages; an invalid email is caught; the review page shows what was entered; edit-from-review
round-trips a corrected value; a successful submission shows claim ID, status and summary; the
payload is in the shape the API expects with blank optionals sent as `null`; a backend outage
shows a customer-safe message and preserves the answers; the safety notice appears when the
answers suggest an urgent situation.

Also verified manually: `vite build` succeeds, and a live `uvicorn` instance returns 201 with a
claim ID for a valid FNOL and 422 with per-field messages for an invalid one.

### 21.10 Phase 1 limitations

1. **No *Check Existing Claim* screen.** `GET /api/claims/{id}` works; the UI for it does not.
2. **No document upload.** The FNOL records *whether* photos exist. Accepting files is Phase 2.
3. **No policy lookup.** Any well-formed policy number is accepted; `policy_id` and
   `customer_id` stay null.
4. **No authentication.** Anyone reaching the API can lodge or read a claim. Phase 6.
5. **File-backed store.** JSONL, full-file scan on read, in-process lock only — fine for a POC,
   replaced in Phase 6.
6. **The emergency safety notice is display-only.** It does not route, prioritise or classify
   anything — Phase 3 owns that. Its wording is a placeholder pending the insurer's approved
   emergency guidance.
7. **`peril` is fixed to `storm`.** Widening it is a later decision, not an oversight.
8. **No claim status view for the customer beyond confirmation.** FR-10 is partially met.
9. **Not accessibility-audited.** Labels, roles, focus outlines and `aria-invalid` are in place;
   no formal audit has been run.

### 21.11 Preparation for Phase 2

| Seam | How Phase 2 uses it |
| --- | --- |
| `ClaimService.submit_claim` | The single place a claim is created. The LangGraph invocation goes after persistence; the governance gate goes before it |
| `ClaimRepository` Protocol | Agents read and write claims through this, not through a file |
| `ALLOWED_TRANSITIONS` | Submitted → Assessment and the rest are already declared and tested |
| `InternalStatus` | `policy_retrieved`, `validated`, `assessment_complete` are defined and unused |
| Claim record shape | Matches `SYNTHETIC_DATA_SPEC.md` §4; derived AI fields are simply absent, not stubbed |
| Router-per-concern | `api/claims.py` stays about intake; policy, validation and assessment get their own routers |
| `api/dependencies.py` | One place to inject the graph, the agents and later the gates |
| `data/synthetic/` | Customers and policies are already seeded for the Policy Agent |

### 21.12 Confirmations

- **LangGraph and the specialist agents were NOT implemented.** `backend/agents/` and
  `backend/graph/` contain only `.gitkeep`; `langgraph` is not installed and is commented out in
  `requirements.txt`.
- **X-Verba/VSL runtime governance was NOT implemented.** `governance/` contains only its
  README. No `policy.py`, `gates.py` or `ledger.py`. No VSL package is installed. **No fake
  governance check was added** — the service layer carries a comment marking where the real gate
  goes, and nothing more.
- **Phase 2 was NOT started.** No policy retrieval, validation agent, classification,
  assessment, confidence scoring or risk analysis exists.

---

## 22. Phase 2 implementation record — Claims Intelligence & Multi-Agent Workflow

**Status: complete.** Built 2026-09-13.
Architecture delivered: **React → FastAPI → LangGraph → five specialist agents → synthetic data.**
No governance runtime. No autonomous claim action.

### 22.1 Objective

Turn a submitted claim into an AI-assisted claims intelligence result: policy context,
validation, damage assessment, risk indicators and a structured recommendation — produced by
specialist agents orchestrated through a LangGraph `StateGraph` over shared state.

### 22.2 Agent architecture

Five agents, each a node in the graph. Agents never call one another; they exchange information
through shared state, which is what the requirements mean by "graph-based multi-agent
orchestration with shared state" rather than A2A.

| Agent | Responsibility | Key payload |
| --- | --- | --- |
| **Intake** | Interpret the FNOL, structure it for everything downstream, note obvious gaps and urgency signals | `IntakePayload` |
| **Policy** | Retrieve the synthetic policy, state its facts, offer a reading of cover, cite wording | `PolicyPayload` (facts / interpretation, kept apart) |
| **Validation** | Check completeness and consistency — within the claim and against the policy | `ValidationPayload` |
| **Assessment** | Classify, band complexity, urgency and value, report confidence | `AssessmentPayload` |
| **Fraud & Risk** | Evaluate risk rules against claim, policy and history; report indicators | `RiskPayload` |

**Three properties every agent has**, enforced in `agents/base.py`:

1. It returns a contract, never free text.
2. It cannot raise. `run()` wraps `analyse()`; an exception becomes a FAILED result whose
   recommendation points at a person. An agent crash never looks like permission to act.
3. It narrates through the LLM boundary *after* its structured result exists.

### 22.3 Agent output contracts

Shared envelope `AgentResult`: `agent`, `status`, `findings[]`, `recommendation`, `reasons[]`,
`confidence`, `data_references[]`, `next_step`, `narrative`, `narrative_source`, `error`, and
`is_recommendation_only: Literal[True]` — structural, not decorative.

`Finding` carries `code`, `summary`, `severity`, `detail`, `data_reference` and — importantly —
`assumption`, set whenever a finding rests on a POC-proposed threshold. That marker travels all
the way to a "POC assumption" chip in the UI, so an unapproved number can never be read as an
insurer rule.

`AgentStatus` is about the agent's own run (`complete`, `incomplete`, `degraded`, `failed`), never
about the claim's fate.

### 22.4 LangGraph architecture

```
START → intake → policy ─┬→ validation ─┬→ assessment → fraud_risk → finalize → END
                         │              │                               ↑
                         └──────────────┴───────────────────────────────┘
                              (two conditional short-circuits)
```

Conditional routing is used **only** where the Phase 0 decision framework calls for it. There are
exactly two branches, each mapped to a documented decision row:

| Branch | Condition | Row | Behaviour |
| --- | --- | --- | --- |
| After **policy** | Policy not found, or no cover basis at the date of loss | D-03 | Skip to finalize — validating against a policy that does not respond produces misleading confidence |
| After **validation** | Required information outstanding | D-01 | Skip to finalize, which recommends Information Required |

The workflow deliberately does **not** branch on risk or complexity. Those shape the
recommendation; routing on them is Phase 3's job.

### 22.5 Shared state

`ClaimsWorkflowState` (`graph/state.py`), a TypedDict with reducers so agents accumulate rather
than overwrite:

| Key | Purpose |
| --- | --- |
| `claim_id`, `claim` | Inputs, written once before the run |
| `results` | agent name → `AgentResult` (merge reducer) |
| `payloads` | agent name → structured payload (merge reducer) |
| `trace` | Execution record per node (append reducer) |
| `errors` | Agent failures (append reducer) |
| `halt`, `halt_reason` | Early termination, the shape a fallback route needs |
| `intelligence` | The finalize node's output |

Five design constraints drove it: each agent writes only its own slot; results stay traceable;
governance can be inserted later without redesign; human review can arrive without redesign; no
field exists that nothing reads.

### 22.6 LLM integration

`backend/llm/` — a boundary, not an SDK wrapper.

| Piece | Role |
| --- | --- |
| `base.py` | `LLMProvider` protocol. One method: `narrate()`. It MUST NOT raise |
| `stub.py` | Deterministic, offline, rule-composed narration. **The default** |
| `http_provider.py` | Any OpenAI-compatible `/chat/completions` endpoint, over `httpx` |
| `factory.py` | `LLM_PROVIDER` selects; unknown values fall back to the stub |

**The division that matters:** the model contributes *narrative*. Every value a decision could
turn on — status, band, flag, confidence — is derived by rule from the Phase 0 decision table, in
the agent. A test asserts this directly: with a deliberately broken LLM, every band, risk level
and recommendation is identical. An LLM outage degrades the prose and nothing else.

Configuration is environment-driven (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`,
`OPENAI_API_KEY`, `LLM_TEMPERATURE`, `LLM_REQUEST_TIMEOUT_SECONDS`). No key is hard-coded, logged
or returned. The default is `stub` deliberately: a POC that only runs with a paid API key is a
POC nobody can run.

`httpx` rather than a vendor SDK keeps provider independence real and adds no dependency — the
project already had it.

### 22.7 Claims intelligence result

`ClaimIntelligenceResult` carries claim context, all five agent results, the four structured
payloads, and the overall recommendation: `recommended_next_step`, `recommendation_summary`,
`recommendation_reasons[]`, `overall_confidence`, `recommended_claim_state`, plus `trace`,
`errors`, `degraded` and `llm_provider`.

`recommended_next_step` is a closed enum, and none of its values is an action:

| Value | Meaning |
| --- | --- |
| `information_required` | Ask the customer for something |
| `manual_review_recommended` | A claims specialist should handle it |
| `specialist_review_recommended` | Risk indicators warrant a specialist |
| `standard_processing_candidate` | Nothing argues against ordinary handling — **not an approval** |

Precedence in `finalize.py` mirrors decision table §4.1, with two differences that keep Phase 2
inside its boundary: nothing routes (it recommends), and **any failed or degraded agent forces a
human recommendation**. "The risk check crashed" must never read the same as "no risk found".
`standard_processing_candidate` is the last branch reached, never a default.

Overall confidence is the **minimum** agent confidence, not the mean — an average lets a
confident intake paper over an unconfident policy read, which is exactly the claim a person
should see.

### 22.8 The recommendation / action boundary

Asserted in the workflow output itself, not only in the API schema:

```
is_recommendation_only : true      (Literal, cannot be set otherwise)
action_taken           : "none"    (Literal)
claim_state_changed    : false     (Literal)
```

Concretely, Phase 2 does not: change `claim_state`, write to the claim record, send any customer
communication, approve, decline or settle anything, or touch an external system. The analysis is
written to its **own store** (`data/claims/analyses.jsonl`) precisely so running the workflow
cannot mutate a claim by accident. `recommended_claim_state` is a suggestion; applying it is
commitment point CP-09, a governed write.

### 22.9 API integration

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/claims/{claim_id}/analyze` | Run the workflow, return the result |
| `GET` | `/api/claims/{claim_id}/analysis` | Read the stored result |

Both are **internal, claims-staff endpoints** — they return policy interpretation and risk
indicators, which must never reach a customer. Phase 6 adds the authentication that enforces
that; in Phase 2 the separation is architectural only, and that is stated rather than glossed
over. Full reference: `API.md`.

### 22.10 Frontend

A second view, deliberately separated from the customer portal: a **claims console** with its own
folder (`src/staff/`), its own visual treatment, an "Internal view — claims staff" banner, and a
statement that no authentication protects it in the POC.

The report shows the recommendation, band tiles, one panel per agent with findings and
confidence, the policy facts/interpretation split with its caveat, risk indicators marked
"Employee only", and a collapsible workflow trace. The boundary note sits at the top, not buried.
The customer confirmation screen is unchanged and shows none of this — a test asserts the
internal content is absent from the customer view.

### 22.11 Observability

`claims.workflow` logs `agent.start` / `agent.finish` with agent, claim id, status, next step and
duration; `workflow.short_circuit` with the reason; `workflow.start` / `workflow.complete` /
`workflow.failed`. `claims.agents` logs agent exceptions with traceback, server-side only.
`claims.llm` logs provider failures by exception class — never the key, never the payload.

Claim contents are not logged. The execution trace is carried in the result for the UI.

**This is not the VerbaLedger.** A trace records what ran; the ledger records governance
decisions with hash-chained causal ordering. They are different artefacts and Phase 2 builds only
the first.

### 22.12 Error handling

| Failure | Behaviour |
| --- | --- |
| Claim not found | 404, customer-safe |
| Policy not found | Agent finding, workflow short-circuits, human recommended |
| Agent raises | FAILED result, workflow completes, `degraded: true`, human recommended |
| LLM unavailable | Degraded narration; **no decision changes** |
| Synthetic dataset missing | Agent returns DEGRADED, explicitly refusing to let absence read as "nothing found" |
| Graph crashes | 503 `claim_analysis_failed`, message says nothing about the claim has changed |
| Unexpected error | 500, no stack trace, no internal detail |

A test asserts no Python exception text, traceback or internal path reaches a response.

### 22.13 Testing

**Backend — 89 tests, all passing** (62 new for Phase 2).

- `test_agents.py` (31): each agent individually, including the facts/interpretation split,
  missing policy, policy not in force, possible exclusion, address mismatch, inconsistent
  estimate, value bands, unknown-value conservatism, emergency urgency, POC-floor reporting, a
  parametrised check that risk language never accuses, indicators never customer-visible,
  degradation without data, and contained agent failure.
- `test_workflow.py` (24): workflow starts and completes, agents run in order, shared state
  accumulates, later agents see earlier results, trace timing; the six required scenarios
  (normal, missing information, policy mismatch, policy not in force, high complexity, elevated
  risk) plus possible exclusion, agent failure failing closed, and an LLM failure changing no
  decision; parametrised proof that no scenario performs an action; and that no governance module,
  VSL package or ledger exists.
- `test_intelligence_api.py` (10): structured result, claim unchanged by analysis, boundary
  fields present, storage and reuse, forced re-analysis, read-back, both 404s, safe reporting of a
  workflow crash, OpenAPI documentation.

**Frontend — 22 tests, all passing** (12 new): console is not the default view, internal marking,
running the workflow, the boundary note, all five agent panels, findings and indicators, the POC
assumption chip, employee-only marking, degraded warning, safe error, reference required, and
internal analysis absent from the customer portal.

All tests use the deterministic stub LLM. No test depends on a live model — the decisions are
rule-derived by design, so a test needing a network call would be testing the wrong thing.

### 22.14 Safety boundaries

The AI does not: settle, approve or decline claims; progress a claim's state; send customer
communications; make fraud accusations; touch a real system; or use real data. Risk language is
constrained by design and tested by a parametrised assertion. Every threshold used is tagged as a
POC proposal end to end.

### 22.15 X-Verba boundary

**Not implemented, and not faked.** No `governance/policy.py`, `gates.py`, `ledger.py` or
`audit_cli.py`. No VSL package installed — the requirement lines stay commented out in
`requirements.txt` with the three install traps recorded. No PreNode, Invariant, TerminalState or
ledger record exists, and no placeholder pretends to be one. A test asserts all of this.

Agent findings do *explain* that a rule becomes an Invariant in Phase 4. That is documentation for
a reader, not a construct — and the test checks for the artefacts, not the vocabulary.

**Seams prepared for Phase 4:**

| Seam | How Phase 4 uses it |
| --- | --- |
| `graph/nodes.py :: agent_node` | Where `gated_node` wraps a node; on denial it returns a state update rather than raising |
| Conditional edges already present | Where `route_on_denial` attaches — each gate needs its own `denial_key` |
| `ClaimIntelligenceService.analyse` | Single call site before the analysis write |
| `ClaimService.submit_claim` | Single call site for CP-02 / CP-09 |
| `app/domain/thresholds.py` | Moves to `governance/policy.py`; agents read through the module, not inline numbers |
| `Confidence.clears_poc_threshold` | Already reports the PreNode floor the gate will enforce |
| `state.halt` / `halt_reason` | The shape a denial route needs |

### 22.16 Phase 3 preparation

Phase 3 adds fraud/risk triage, escalation routing and the human review queue. What is waiting:
risk indicators with severities already produced; escalation-relevant signals (emergency,
vulnerable customer, high value, exclusions, inconsistencies) already detected and surfaced but
deliberately not routed on; `InternalStatus` values for the queue already defined and unused;
`recommended_claim_state` ready to become an actual transition once it is governed.

### 22.17 Known limitations

1. **No document analysis.** The FNOL records whether photos exist; nothing reads them.
2. **Policy retrieval is structured lookup**, not semantic search — honest and reproducible for
   one synthetic wording; a vector store is a later decision.
3. **The exclusion screen is keyword-based** and labelled as such in the output.
4. **Classification is keyword-based**, not a trained classifier.
5. **Confidence is heuristic** — a deterministic starting value reduced per missing input. It is
   not calibrated, and `CONFIDENCE_CALIBRATION_ERROR` remains a declared assumption.
6. **No authentication on the internal endpoints or console.** Phase 6.
7. **Thresholds live in `app/domain/thresholds.py`**, not `governance/policy.py`, because the
   governance module may not exist yet. Phase 4 moves them.
8. **The claims console has no queue, assignment or actions** — that is Phase 3.
9. **No claims/documents datasets generated yet** — Phase 2 needed policies, wordings, history and
   risk rules; the rest are generated by the phase that consumes them.
10. **The LLM contributes no decision.** That is deliberate for Phase 2, but it does mean the
    demonstration's intelligence is mostly rule-based; widening the model's role is a decision to
    take with governance in place, not before it.

### 22.18 Confirmations

- **No autonomous settlement, approval or denial.** Structurally impossible in the result
  contract, and asserted by parametrised tests across every scenario.
- **X-Verba/VSL runtime governance NOT implemented.** No governance module, no VSL package, no
  gate, no ledger, no fake constructs.
- **Phase 3 NOT started.** No escalation routing, no human review queue, no priority pathway, no
  queue UI, no claim-state progression.

---

## 23. Phase 3 implementation record — Risk & Human Escalation

**Status: complete.** Built 2026-09-13.
Architecture delivered: **React → FastAPI → LangGraph (5 agents + escalation) → routing
decision → claim-state transition + human review queue.** No governance runtime.

Detailed rule catalogue: **[`ROUTING_MODEL.md`](ROUTING_MODEL.md)**.

### 23.1 Objective

Decide whether an AI-analysed claim is suitable for continued automated processing or
needs a person — and when it needs a person, make that a real workflow state with
structured reasons, a queue, and a review experience.

### 23.2 Risk evaluation and routing

A new `backend/routing/` module: `contracts.py` (the models), `rules.py` (the escalation
rule catalogue), `router.py` (evaluation). Twelve rules, each traceable to a Phase 0
decision row or escalation trigger, evaluated deterministically over the Phase 2 agent
payloads. No new business policy was invented — Phase 3 implements Phase 0.

Three outcomes: `AUTOMATED_PATH_RECOMMENDED`, `HUMAN_REVIEW_REQUIRED`,
`INFORMATION_REQUIRED`. How the router decides:

- **All** applicable rules fire, so "why was this escalated?" gets a list, not a guess.
- The **outcome** comes from the first match in Phase 0 precedence order.
- The **priority** is the strongest across every reason.
- `AUTOMATED_PATH_RECOMMENDED` is what is left when nothing fires — never a default.

`RoutingDecision.decision_authority` is the fixed literal `"business_rules"`. The model
supplies findings; rules decide routes.

### 23.3 Escalation reasons

Every reason carries code, label, detail, **basis** (`ai_finding` or `business_rule`),
priority, outcome, rule reference, observed value, threshold value, POC-assumption
marker and source agent. A test asserts no reason's detail contains "AI decided".

The twelve rules, in precedence order: emergency · incomplete analysis · no cover basis ·
vulnerable customer · policy uncertainty · conflicting information · risk indicators ·
above automated authority · high value · high complexity · missing information · low
confidence. Full table in `ROUTING_MODEL.md` §2.

### 23.4 Human review queue

`ReviewQueueRepository` (Protocol + in-memory + JSONL), `ReviewService`, and three
endpoints. One entry per claim — re-analysing updates it rather than duplicating it.

The queue sorts **urgent → high → standard, oldest first within a band**, in the API
rather than the UI: a queue that buries the emergency claim is worse than no queue.

Each row carries the claim ID, state, priority, review type, primary reason and reason
count, customer, policy, date of loss, estimated value, complexity, risk level and
confidence. The full entry adds every structured reason, the explanation lines, the
vulnerable/emergency flags and the action history.

### 23.5 Human review workflow

`GET /api/review-queue/{claim_id}` returns everything needed to answer the six reviewer
questions the requirements list, in that order, with the reviewer's decision kept
structurally apart from all six.

Four POC actions:

| Action | Effect |
| --- | --- |
| `start_review` | Assigns the claim. No claim-state change |
| `request_information` | → Information Required, entry closed |
| `refer_to_specialist` | Stays in Human Review, `specialist_referral`, review type becomes specialist |
| `complete_review` | → Approved/Completed |

`complete_review` is **POC bookkeeping**: `ReviewActionResponse.poc_note` states that it
does not approve a claim for payment, set a reserve, settle anything or notify the
customer, and `decision_source` is the fixed literal `"human"`.

An action the queue state does not permit is **refused with 409**, not forced.

### 23.6 Vulnerable-customer path

Resolved in the escalation node from the synthetic customer record via the policy.
Carries forward **operational fields only** — support flag, accessibility need, contact
preference. Rule `E-12_VULNERABLE_CUSTOMER`, high priority, human review; the pathway
banner tells the reviewer to use the recorded contact preference and send no automated
chase-ups.

Two tests guard the boundary: the reason contains no medical or diagnostic vocabulary,
and **vulnerability never appears in the risk assessment**. Those two pathways must not
touch.

### 23.7 Emergency path

Rule `E-11_EMERGENCY`, highest precedence, `urgent` priority, `priority_review`.

Read from the **FNOL directly**, not only from the assessment — so a claim that
short-circuits before the Assessment Agent runs is still caught. A test covers exactly
that: no policy found *and* an injury reported still produces an urgent route.

The UI shows make-safe guidance marked explicitly as placeholder wording; Phase 0
requires the insurer's own approved emergency content and forbids the AI improvising
safety advice.

### 23.8 Claim-state transitions

Routing applies the transition — this is the phase where Human Review stops being a
label. Full table in `ROUTING_MODEL.md` §6. Two constraints:

1. Every transition is checked against `ALLOWED_TRANSITIONS` first. One that would need
   an impossible transition is **refused and logged**, not forced.
2. **Routing can only reach states where a person or the customer holds the claim.**
   Approved/Completed is reachable only by a reviewer's action, and a test asserts no
   routing outcome ever recommends it.

### 23.9 LangGraph changes

One new node, no redesign:

```
START → intake → policy → validation → assessment → fraud_risk
                   |           |                        |
                   +-----------+------------------------+
                               v
                        escalation → finalize → END
```

Both short-circuits now land on **escalation** rather than finalize. That is the change
that matters: routing always runs, so a claim that skipped assessment is still routed and
an unsafe customer still reaches a person.

`finalize` was **simplified**, not extended: the precedence logic it carried in Phase 2
moved into `routing/rules.py`, and finalize now presents the routing decision rather than
forming a second opinion about it. Two copies of a precedence order drift, and the one
that drifts silently is the one deciding whether a claim reaches a person.

### 23.10 API changes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/review-queue` | The queue, filterable by status and priority |
| `GET` | `/api/review-queue/{claim_id}` | Everything a reviewer needs |
| `POST` | `/api/review-queue/{claim_id}/action` | Record a POC review action |

`POST /api/claims/{id}/analyze` now also applies the routing decision and reports
`routing`, `claim_state_changed` and `routing_applied`.

### 23.11 Frontend changes

The claims console gained tabs — **Analyse a claim** and **Review queue** — plus two new
screens: `ReviewQueue.jsx` (priority-ordered list with filters and counts) and
`ClaimReview.jsx` (the six reviewer questions, then the decision panel). A shared
`EscalationReasons.jsx` renders each reason with its evidence and an **AI finding** or
**Business rule** chip, used on both the queue detail and the analysis report.

The decision panel is visually separated — its own border, its own heading, and the line
"Everything above is an AI recommendation. What you record here is the decision."
Choosing an action shows exactly what it will do before it is taken.

A test asserts none of this appears in the customer portal.

### 23.12 Observability

`claims.routing` logs the decision with outcome, priority, every reason code and the
recommended state. `claims.review` logs queue creation and updates (with the vulnerable
and emergency flags), every claim-state transition with its source (`routing` or
`human`), and every review action with the reviewer. `claims.workflow` logs the
escalation node's start and finish, and short-circuits now name their target.

Claim contents are not logged. **No VerbaLedger** — that is Phase 4 and a different
artefact.

### 23.13 Testing — 178 tests, all passing

```
Backend   140 passed   (51 new for Phase 3)
Frontend   38 passed   (16 new for Phase 3)
```

`test_routing.py` (28) covers all twelve required scenarios plus the properties that
matter more than any one scenario: all applicable reasons collected, priority taken as
the strongest, reasons structured rather than generic, explanation naming observation,
threshold and source, routing never recommending Approved/Completed, an empty agent
output never clearing a claim, a raising rule escalating rather than clearing, and no
fabricated governance constructs.

`test_review_api.py` (23) covers routing applying each of the three transitions, the
queue listing with reasons, urgent-first ordering, filtering, re-analysis updating rather
than duplicating, review detail answering the six questions, both pathway flags, all four
review actions, only-a-human-reaches-Approved/Completed, action history, refusal with 409,
and both 404s.

`ReviewQueue.test.jsx` (16) covers the queue, ordering, filtering, the six reviewer
sections, reason evidence with its basis chip, both pathway banners, the decision
boundary, recording an action, requiring a reviewer name, and internal content staying
out of the customer portal.

### 23.14 Safety boundaries

The system does not settle, approve or decline claims; does not accuse anyone of fraud;
sends no customer communications; touches no real system; uses no real data. Routing
moves a claim towards a person and cannot complete one. `complete_review` is labelled POC
bookkeeping in the response itself. Every failure path escalates rather than clears.

### 23.15 X-Verba boundary

**Not implemented, not faked.** No `governance/policy.py`, `gates.py`, `ledger.py` or
`audit_cli.py`; no VSL package installed; no PreNode, Invariant, TerminalState or ledger
record. Tests assert the modules and packages are absent, and that no fabricated
governance verdict appears in any output.

Seams prepared: the escalation node for CP-11, `ReviewService.apply_routing` for CP-09 and
CP-12, `ReviewService.perform_action` for CP-09. `ROUTING_MODEL.md` §9 maps each Phase 3
rule to the Phase 4 construct that replaces it — and is explicit that the difference is
not cosmetic: today these *route*, in Phase 4 the Invariants *stop* automation and require
human re-enablement.

### 23.16 Known limitations

1. **No authentication** on the internal endpoints or console. Phase 6.
2. **No assignment model** — `assigned_to` records the last actor, there are no teams,
   capacity or SLAs.
3. **Emergency means priority queueing, not paging.** Whether a real deployment needs
   paging is an open Phase 0 question.
4. **Emergency guidance wording is placeholder** pending the insurer's approved content.
5. **No customer communication** at any point — a claim moved to Information Required
   does not tell the customer. The Communication Agent is still unbuilt.
6. **Thresholds still live in `app/domain/thresholds.py`**, not `governance/policy.py`.
   Phase 4 moves them.
7. **Re-analysis can move a claim back** out of Human Review if the inputs change; there
   is no lock while a reviewer holds it.
8. **The queue is a JSONL log.** Fine for a POC; Phase 6 replaces it.
9. **`complete_review` is bookkeeping only** and deliberately does not model the real
   outcomes (accept, decline, part-settle) a claims system needs.

### 23.17 What remains for Phase 4

Install VSL-Core and VSL-LangGraph per the recorded traps; build `governance/policy.py`,
`gates.py`, `ledger.py`, `audit_cli.py`; convert `E-01` into PreNode PN-01 with a real
fallback and `E-04`/`E-05`/`E-06` into Invariants INV-02/01/03 with a TerminalState and
human re-enablement; write the VerbaLedger with `caused_by` on every entry; make the five
audit checks pass; and build the governance dashboard (UI-05).

### 23.18 Confirmations

- **No autonomous settlement, approval or denial.** Routing cannot reach
  Approved/Completed; only a reviewer's action can, and it is labelled POC bookkeeping.
- **X-Verba/VSL runtime governance NOT implemented**, and no construct faked.
- **Phase 4 NOT started.**

---

## 24. Phase 4 implementation record — X-Verba / VSL Governance Enforcement

**Status: complete.** Phase 5 not started.

Built directly in the connected local folder `AI_Insurance_Claims_Agent`. No ZIP,
no export, no copy. Phases 0–3 preserved; nothing was rebuilt.

Companion document: **`docs/GOVERNANCE_ENFORCEMENT.md`** — the full enforcement
design, the ledger contract, the audit semantics and the stated limitations.
This section is the phase record.

### 24.1 The distinction this phase exists to establish

This is the most important paragraph in the document.

| | Phase 3 — business-rule routing | Phase 4 — runtime governance enforcement |
| --- | --- | --- |
| **Question it answers** | "Where should this claim go?" | "May this system take this action?" |
| **Nature** | A recommendation about handling | A permission to act |
| **If it is wrong** | The claim goes to the wrong queue | The system does something it must not |
| **Can it be bypassed?** | It is advice — the layer above can ignore it | No: the side effect is inside the gate |
| **Where it lives** | `backend/routing/` | `governance/` + the call site in `ReviewService` |
| **Recorded in** | the analysis result | a hash-chained VerbaLedger |
| **Reviewable how?** | read the reasons | `audit()`, `verify_integrity()`, a certificate |

Phase 3 decides *what should happen*. Phase 4 decides *whether the system is
permitted to make it happen*, and physically prevents it when not. A system with
only Phase 3 has governance-shaped documentation. A system with Phase 4 has a
denied action that cannot execute.

The three Invariants deliberately mirror Phase 3 rules E-04, E-05 and E-06. That
is defence in depth, not duplication: **the Invariants exist to catch the routing
layer being wrong.** In normal operation they never fire. `test_an_invariant_
catches_the_routing_layer_being_wrong` breaks the routing layer on purpose and
shows INV-02 stopping a NZD 240,000 claim the business rule let through.

### 24.2 Packages

| Package | Distribution | Import | Version |
| --- | --- | --- | --- |
| VSL-Core | `super-semantics-vsl` | `vsl_core` | 0.1.0 |
| VSL-LangGraph | `vsl-langgraph` | `vsl_langgraph` | installed `--no-deps` |

Traps navigated, as the guidance warned: the distribution name is **not** the
import name; `pip install vsl-core` fetches an unrelated stub and was not used;
VSL-LangGraph carries a stale dependency URL, so it was installed with
`--no-deps` against the already-satisfied `vsl_core`.

`vsl_core.conformance.suite.run_conformance_suite(LangGraphAdapter())` returns
`[]` — **CONFORMANT**. Exposed as `python -m governance.audit_cli conformance`.

### 24.3 Files created

```
governance/policy.py                         WHAT is governed (declarations only)
governance/gates.py                          HOW it is enforced (the single call site)
governance/ledger.py                         the VerbaLedger
governance/audit_cli.py                      verify / audit / certify / conformance / summary
backend/graph/governed.py                    VSL-LangGraph wiring (CP-11)
backend/app/schemas/governance.py            dashboard models
backend/app/services/governance_service.py   read-only ledger reader
backend/app/api/governance.py                GET-only dashboard endpoints
frontend/src/staff/GovernanceDashboard.jsx   the governance screen
tests/backend/conftest_phase4.py             ledger isolation, suspension reset
tests/backend/test_governance.py             56 governance tests
frontend/src/__tests__/Governance.test.jsx   16 governance UI tests
docs/GOVERNANCE_ENFORCEMENT.md               this phase's design document
```

### 24.4 Files modified

```
backend/app/services/review_service.py    the enforcement site; apply_routing is now async
backend/app/services/intelligence_service.py   async through to the gate
backend/app/api/intelligence.py           async endpoint
backend/app/api/review.py                 + re-enable-automation
backend/app/schemas/review.py             + GovernanceDecision, ReEnablement*, automation_suspended
backend/app/schemas/intelligence.py       + governance, governance_gate
backend/app/main.py                       + governance router
backend/graph/builder.py                  + governance_gate, governance_fallback nodes
backend/graph/state.py                    + governance_gate; NODE_ORDER
backend/graph/finalize.py                 workflow_version phase-4
frontend/src/api/client.js                + 3 governance calls
frontend/src/staff/StaffConsole.jsx       + Governance tab
frontend/src/staff/ClaimReview.jsx        + GovernancePanel, ReEnablementForm
frontend/src/staff/IntelligenceReport.jsx + governance strip
frontend/src/staff/ReviewQueue.jsx        + automation-suspended chip
frontend/src/styles.css                   governance styling
tests/backend/conftest.py                 imports the Phase 4 fixtures
tests/backend/conftest_phase2.py          ainvoke; shared review_client
tests/backend/test_workflow.py            phase-4 trace and version
tests/backend/test_routing.py             ainvoke
tests/backend/test_review_api.py          review_client moved to conftest
docs/PROJECT_PLAN.md                      this section
docs/API.md                               governance endpoints
```

### 24.5 Commitment points governed

From `docs/COMMITMENT_POINTS.md`, and deliberately **not** every computation:

| CP | Where | Governed how |
| --- | --- | --- |
| CP-11 | the graph committing to the automated branch | `gated_node` + `route_on_denial` (`graph/governed.py`) |
| CP-09 | the claim-state write | `govern_automated_route(perform=...)` |
| CP-12 | queue placement | same gate, same call |

Not governed, with reasons: agent LLM calls produce narrative only and cannot
authorise anything (the narrative is discarded on failure and no decision
changes); reading synthetic reference data is not a commitment; writing the
analysis record does not change the claim. Governing those would add ledger
noise and dilute the meaning of a gate.

### 24.6 The enforcement property, stated precisely

```python
governance, _ = await govern_automated_route(
    _governance_candidate(claim, intelligence),
    perform=lambda: self._apply_outcome(claim, intelligence, routing, outcome),
)
```

Inside `govern_automated_route`, `perform()` is referenced **exactly once**, on
the last line of the proceed path. Every denial path returns above it. A denied
action is therefore not "checked and skipped" — the code that would take it is
unreachable.

This is asserted structurally, not just in prose:
`test_the_side_effect_is_referenced_once_and_only_after_every_gate` reads the
function's own source and checks that the single `perform()` call sits after the
last gate `await` and after every `return outcome, None`.

### 24.7 Gates

| ID | Construct | Name | From | Behaviour on failure |
| --- | --- | --- | --- | --- |
| PN-01 | PreNode | `automation-confidence` | E-01 | `ROUTE_TO_HUMAN_QUEUE` |
| INV-01 | Invariant | `policy-in-force` | E-05 | TerminalState |
| INV-02 | Invariant | `automated-authority-limit` | E-04 | TerminalState |
| INV-03 | Invariant | `no-auto-approval-under-exclusion` | E-06 | TerminalState |

Mapping unchanged from `docs/ROUTING_MODEL.md` §9. Each gate has its own
`denial_key` (`governance.policy.DENIAL_KEYS`) — two gates sharing one makes the
second router read the first gate's denial, and with four gates those are exactly
the conditions for that bug.

Derived assurance: **LOW** for every gate (F1=True, F2=NONE → output-layer
control). Reported as LOW in the API, on the dashboard and in the docs. HIGH
would require a formation-layer change this POC does not make.

Confidence floor: **0.8148**, derived by solving γ ≥ 1.1 at a decision boundary
of 0.80. Gamma divides by the boundary odds, not by 0.5 — the alternative is a
silent failure in which the gate governs less than it appears to.

### 24.8 Ledger and caused_by

```
MONITOR ──> PRE_NODE ──> VERIFICATION ──(INSUFFICIENT)──> TERMINAL ──> HUMAN_AUTHORISED_TRANSITION
                                      └──────────────────> SPECIFICATION_UPDATE
```

`caused_by` is set on **every** entry after the first. Without it `audit()` falls
back to a same-identity/later-timestamp heuristic that can match an unrelated
PRE_NODE and report a **false pass** under concurrency — and a claims queue is
exactly that concurrency.

A MONITOR is written for every request, not only for incidents.

A PreNode denial records **SUFFICIENT** (governance worked); only an Invariant
violation records **INSUFFICIENT** (governance failed), which is what makes audit
check 4 meaningful instead of permanently red on routine traffic.

### 24.9 Results

```
verify_integrity()   True   (and False after one payload byte is edited on disk)

audit() — clean run, no open terminal state
  PASS  drift_flagged_monitor_has_pre_node
  PASS  pre_node_has_verification
  PASS  insufficient_verification_has_specification_update
  PASS  terminal_has_human_authorised_transition
  N/A   no_monitoring_gaps   (skipped unless --max-monitor-gap-seconds is given)
  → all_passed True; VerbaCertificate issued

audit() — with an open terminal state
  FAIL  terminal_has_human_authorised_transition
  → exit 1, certificate refused. Correct: governance is unfinished.

audit() — after human re-enablement
  → all_passed True; certificate issued

conformance   CONFORMANT (run_conformance_suite → [])
```

Tests: **196 backend** (140 pre-existing + 56 new), **54 frontend** (38
pre-existing + 16 new). No existing test was deleted or weakened; the Phase 2/3
tests that changed were updated to the new *correct* behaviour (the trace now
ends in `governance_gate`; `workflow_version` is `phase-4`). The Phase 2 test
asserting governance did not yet exist was **inverted, not removed** — it now
asserts the constructs are genuine `vsl_core` types.

### 24.10 Failure safety

If governance itself fails, the action does not happen. The gate is `await`ed
inside `apply_routing`; an exception propagates and reaches the FastAPI handler,
which returns a handled error — `perform()` is never called, because reaching it
requires completing every gate first. **A governance-system failure is not
permission to act.** The claim stays where it was and a person can pick it up.

### 24.11 Limitations

Fully stated in `docs/GOVERNANCE_ENFORCEMENT.md` §11. The headline one:

**Suspension state lives in process memory.** It does not survive a restart and
is not shared across workers. This is *not* solved and is not pretended to be.
What exists is `rebuild_suspensions_from_ledger()` — the production re-derivation
(a TERMINAL with no later HUMAN_AUTHORISED_TRANSITION is an open suspension),
implemented and tested, so the move to Redis is a storage swap rather than a
redesign. A test asserts the loss *and* the recovery.

Others: assurance is LOW; `Fallback`'s fields are declarative and the adapter's
warning is left visible rather than suppressed; `Proofing` is a documentation
review, not a formal proof; the authority is a POC placeholder; every threshold
is a proposal; no authentication anywhere; the ledger is a JSONL file;
`verify_integrity()` detects tampering but does not prevent it.

### 24.12 Confirmations

- **No autonomous settlement, approval or denial** was introduced. Governance can
  only make an outcome more conservative — a test sweeps the parameter space to
  confirm a gate never turns a denial into an approval.
- **No real insurance system** is connected. **No real customer data** exists.
- **An AI recommendation is still not an insurance decision**, and governance
  does not change that: it decides whether an *automated step* may proceed.
- **X-Verba is not faked.** The constructs are `vsl_core` types (asserted with
  `type(x) is`), the adapter passes the framework's own conformance suite, the
  gates run before the side effect (asserted structurally), the ledger is
  hash-chained (asserted by tampering with it), and the audit fails when it
  should.
- **Phase 0–3 functionality preserved.** 140 pre-existing backend tests and 38
  pre-existing frontend tests still pass.
- **Phase 5 NOT started.**
