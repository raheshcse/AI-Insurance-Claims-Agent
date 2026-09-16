# AI-Powered Insurance Claims Agent

A proof of concept for **governed AI claims automation**: LangGraph-orchestrated specialist
agents triage a home storm-damage claim, business rules decide where it should go, and an
X-Verba / VSL governance layer decides whether the system is *permitted* to make that happen —
enforced on the execution path, before the action, not reported afterwards.

> **This is a proof of concept using synthetic insurance data.** No real customer, policy or
> claim data is used at any point.
>
> **AI output is analysis and recommendation only. The system does not autonomously approve,
> decline or settle insurance claims.**
>
> **X-Verba / VSL governs whether configured automated actions are permitted; it does not make
> the insurance claim decision.** A person does.

**Status: Phase 4 complete** — X-Verba / VSL governance enforcement. Phases 5 and 6 not started.

The authoritative requirements are in `AI_Insurance_Claims_Agent_Technical_Assessment.docx`
(unmodified). Governance terminology and rules come from the supplied *X-Verba — VSL Governance
Spec for Agent Builds* v1.0 (Super Semantics).

---

## Contents

[Business problem](#1-business-problem) · [Objective](#2-project-objective) ·
[Use case](#3-insurance-claims-use-case) · [Capabilities](#4-key-capabilities) ·
[Architecture](#5-architecture) · [Technology stack](#6-technology-stack) ·
[Claims workflow](#7-claims-workflow) · [Agents](#8-ai-agent-architecture) ·
[LangGraph](#9-langgraph-orchestration) · [Human review](#10-human-review-workflow) ·
[Risk & escalation](#11-riskescalation-logic) ·
[Governance](#12-x-verba--vsl-governance-architecture) ·
[**Claims assistant**](#37-phase-5--conversational-ai-insurance-claims-assistant) ·
[Four authorities](#17-governance-vs-ai-vs-business-rules-vs-human-decision) ·
[Synthetic data](#18-synthetic-data) · [Structure](#19-project-structure) ·
[Install](#20-installation) · [API](#25-api-overview) · [Walkthroughs](#26-how-to-submit-a-claim) ·
[Tests](#30-how-to-run-tests) · [Scenarios](#32-example-permit-scenario) ·
[Limitations](#34-current-poc-limitations) · [Phases](#35-phase-progress)

---

## 1. Business problem

Home insurance claims arrive in volume after a weather event, and most of them are
straightforward. Handling every one manually is slow and expensive; handling them with
unconstrained automation is worse, because the failure mode is not "a slow claim" but "a claim
progressed on a lapsed policy", "a settlement above delegated authority", or "an exclusion
missed". Those are regulatory and conduct exposures, not service-level ones.

The gap this POC addresses is specific: **an AI system that is confident is not the same as an AI
system that is permitted.** Most agentic claims prototypes conflate the two — the model produces a
recommendation, the recommendation becomes an action, and the only thing standing between them is
application code that could be wrong. What is missing is a layer that decides whether a
consequential action may execute *at all*, that a person can audit afterwards, and that
technically prevents the action rather than advising against it.

## 2. Project objective

Demonstrate, end to end and with working code, that:

1. A multi-agent AI workflow can triage a real claim type usefully.
2. Business rules — not the model — decide where a claim goes.
3. A runtime governance layer decides whether the system may act, **before** it acts.
4. Every governance decision leaves an auditable, tamper-evident record.
5. A human being makes every claim decision.

Fully autonomous claim settlement is deliberately out of scope, in every phase.

## 3. Insurance claims use case

**Home insurance → storm damage → First Notice of Loss (FNOL) → triage.**

Chosen because it is high-volume, seasonal, mostly routine, and has clear failure modes worth
governing: cover in force at the date of loss, perils covered, exclusions (maintenance, wear),
excess, sums insured, and delegated authority limits. It also has a genuine duty-of-care
dimension — an uninhabitable home or an injured customer needs a person, fast.

The POC covers lodgement through triage, routing and human review. It does not settle, pay,
reserve, or contact a customer.

## 4. Key capabilities

| Capability | What it does |
| --- | --- |
| Customer FNOL portal | A guided six-step storm-damage claim, validated client- and server-side |
| Claims intelligence | Five specialist agents produce structured findings, not prose |
| Provider-independent LLM | Deterministic offline stub by default; **Google Gemini** or any OpenAI-compatible endpoint when configured |
| Rule-based routing | Twelve escalation rules decide automated path / human review / information required |
| Human review queue | Priority-ordered, with structured reasons and a real review workflow |
| **Runtime governance** | A VSL PreNode and three Invariants gate the consequential write |
| **Hash-chained ledger** | Every governance decision recorded, with causal links |
| **Audit CLI** | Real integrity, audit, certification and conformance checks, with real exit codes |
| Governance dashboard | What is enforced, what happened, and whether it holds up |

## 5. Architecture

```
Customer                                  Claims staff (internal)
   │                                              │
   ▼                                              ▼
React portal ─────────────► FastAPI ◄───────── React claims console
                              │
                              ▼
                     LangGraph StateGraph
                              │
   ┌──────────────────────────┴───────────────────────────┐
   │  for each of intake · policy · validation ·          │
   │  assessment · fraud_risk:                            │
   │                                                      │
   │      agent computes its structured result            │
   │                    │                                 │
   │                    ▼                                 │
   │      VSL GATE  ── CP-13 ── govern_llm_narration()    │
   │              │                    │                  │
   │           PERMIT                DENY                 │
   │              │                    │                  │
   │              ▼                    ▼                  │
   │      Gemini is called      Gemini NOT called         │
   │      (provider reached)    (no request, no key)      │
   │              │                    │                  │
   │              └────────┬───────────┘                  │
   │                       ▼                              │
   │              structured result + prose               │
   └──────────────────────────┬───────────────────────────┘
                              │
                              ▼
                    escalation (business rules)
                              │
                              ▼
                   governance_gate  ◄── PN-01, via VSL-LangGraph      [CP-11]
                        │        │
                   permitted   denied → governance_fallback
                              │
                              ▼
                ReviewService.apply_routing                    [CP-09 / CP-12]
                              │
            govern_automated_route(candidate, perform=<the write>)
                              │
      MONITOR → PN-01 → INV-01/02/03 → VERIFICATION → perform()
                    │          │
            human queue   TERMINAL STATE (automation suspended)
                              │
                              ▼
                         VerbaLedger
                              │
                   ┌──────────┴──────────┐
                   ▼                     ▼
        Governance dashboard        audit_cli
```

The layering rule that matters: **governance is separate from business logic and from AI
reasoning, and it sits on the execution path.** `governance/policy.py` imports only `vsl_core` and
the standard library — a test parses the module's own AST to enforce that. Nothing in `backend/`
embeds governance policy.

## 6. Technology stack

| Layer | Technology |
| --- | --- |
| Presentation | React 18 + Vite, hand-written CSS, no UI framework |
| API | FastAPI + Pydantic v2 |
| Orchestration | LangGraph `StateGraph` with typed shared state and reducers |
| Agents | Five specialist agents over a shared result contract |
| **Governance** | **VSL-Core (`super-semantics-vsl`) + VSL-LangGraph adapter** |
| LLM | Provider-independent; deterministic stub default, **Gemini (Interactions API)** or OpenAI-compatible optional |
| Storage | JSONL files (claims, analyses, queue, ledger) — a POC choice, not a production one |
| Tests | pytest (backend), vitest + Testing Library (frontend) |

## 7. Claims workflow

Six official claim states, and no others:

```
Draft → Submitted → Information Required ⇄ Submitted
                 → Assessment
                 → Human Review → Approved/Completed
```

Alongside each state sits an *internal status* (`assessment_complete`,
`awaiting_customer_response`, `governance_denied_prenode`, `automation_suspended`, …). Internal
statuses are **not** business claim states, and the distinction is enforced by a test.

Transitions are declared once, in `backend/app/domain/claim_state.py`, and a routing decision that
would need an impossible transition is **refused rather than forced**.

Only a reviewer's own action can reach Approved/Completed. Routing cannot; governance cannot.

## 8. AI agent architecture

| Agent | Produces | Never does |
| --- | --- | --- |
| **Intake** | Structures the FNOL: peril, dates, damage areas, missing information | Judge cover |
| **Policy** | Facts (from the record) and interpretation (the agent's reading), in separate fields | Decide cover |
| **Validation** | Completeness and internal consistency checks | Reject a claim |
| **Assessment** | Complexity band, urgency band, estimated value, value band, net of excess | Set a reserve |
| **Fraud & Risk** | Risk indicators as prompts to review, with evidence | Accuse anyone |

Three properties every agent has:

1. **It returns a contract, not free text.** `AgentResult` carries findings, a recommendation,
   reasons, a confidence and its basis. `is_recommendation_only` is `Literal[True]` — structural,
   not decorative.
2. **It cannot raise.** `run()` wraps `analyse()`; a failure becomes a `FAILED` result that points
   at a person. "The risk check crashed" never reads like "no risk found".
3. **The LLM contributes narrative only.** Every value a decision turns on is rule-derived from
   the Phase 0 decision table. A test runs the whole workflow with a broken LLM and asserts every
   band and every recommendation is unchanged.

Risk indicators are **never** customer-visible and are phrased as prompts for review. A
parametrised test asserts the language never accuses.

### Which model writes the prose

Three providers, one interface (`LLMProvider` in `backend/llm/base.py`), selected by
`LLM_PROVIDER`:

| `LLM_PROVIDER` | Provider | Key | Notes |
| --- | --- | --- | --- |
| `stub` *(default)* | `StubLLMProvider` | none | Deterministic, offline, reproducible |
| `gemini` | `GeminiLLMProvider` | `GEMINI_API_KEY` | Google Gemini, **Interactions API** |
| `openai` · `azure-openai` · `openai-compatible` · `http` | `HttpChatLLMProvider` | `OPENAI_API_KEY` | Any OpenAI-compatible `/chat/completions` |

**Why Gemini is its own provider rather than a base URL.** Gemini's current API is the
Interactions API, and it is not chat-completions-shaped in any respect — different path
(`/v1beta/interactions`), different auth header (`x-goog-api-key`, not `Authorization: Bearer`),
different body (`input` + `system_instruction` + `generation_config`, not `messages`), and the
text arrives at `steps[].content[].text` rather than `choices[0].message.content`. Four
differences, each of which would otherwise become an `if provider == "gemini"` branch inside a
class whose entire job is to speak one protocol.

Gemini *also* publishes an OpenAI-compatibility endpoint, and the existing HTTP provider reaches
it with configuration alone — `.env.example` documents how. It is not the default because Google
labels that layer beta and states that unsupported parameters are **silently ignored**, and
because a Gemini key living in a variable named `OPENAI_API_KEY` is an incident waiting to
happen. (Google's older `:generateContent` endpoint still works but is now documented as legacy;
this project targets the current API.)

**Selected is not the same as answering.** Every provider degrades to deterministic narration
when its key is missing or its endpoint is unreachable, and says so:

```
llm_provider   "gemini"              which provider was configured
llm_model      "gemini-3.8-flash"    which model answered
llm_degraded   false                 true when the fallback wrote the prose instead
```

Each agent also records `narrative_source` — `"gemini"` or `"gemini (degraded)"` — so a reader
can tell model prose from fallback prose at a glance. Substituting one for the other silently
would be the dishonest option.

To check which is actually happening, without printing your key:

```powershell
python -m llm.verify_cli --provider gemini
```

Exit **0** a live model answered · **1** the fallback answered · **2** the check could not run.

**Whatever answers, the decisions are identical.** A parametrised test runs the full workflow
three ways — stub, Gemini answering, Gemini returning HTTP 500 — and asserts that twelve
decision fields (routing outcome, next step, claim state, priority, reason codes, complexity,
urgency, value band, risk level, cover certainty, confidence, governance gate) are byte-identical
across all three, while the prose differs. `backend/routing/` and `governance/` import no LLM
module at all, and a test parses their ASTs to keep it that way.

## 9. LangGraph orchestration

A `StateGraph` over a `TypedDict` with reducers, so each node writes only its own slot and a re-run
cannot silently corrupt an earlier result.

```
intake → policy → validation → assessment → fraud_risk → escalation
       → governance_gate → [governance_fallback] → finalize
```

Two conditional short-circuits, each traceable to a Phase 0 decision row: no cover basis (D-03)
skips to routing, information outstanding (D-01) skips assessment. **Both still pass the governance
gate** — a short-circuited claim is exactly the kind that must not slip out ungoverned.

`trace` records every node that ran, when, and how it went. That is workflow execution. The
VerbaLedger records governance decisions. They are different things and stay separate.

## 10. Human Review workflow

Human Review is a workflow state with a queue behind it, not a label.

A claim routed to a person gets a queue entry with a priority, structured escalation reasons, and
the analysis. The queue is ordered urgent → high → standard, oldest first within a band — a queue
that buries the emergency claim under twenty routine ones is not doing its job, so the ordering is
part of the API contract rather than a UI concern.

The claim review screen answers six questions, in order: what the customer reported, what the
policy says, what the agents found, what risks were identified, why it was escalated, what the AI
recommends — and then, in its own bordered section below all six, **what the reviewer decides**.

Four POC review actions: `start_review`, `request_information`, `refer_to_specialist`,
`complete_review`. Every one records `decision_source: "human"`. `complete_review` is POC
bookkeeping — it does not approve a claim for payment, set a reserve, settle anything or notify
the customer, and the response says so in those words.

A fifth action exists only for suspended claims: **re-enable automation** (§16).

## 11. Risk/escalation logic

Twelve escalation rules (E-01…E-16), each traceable to a Phase 0 decision row, in
`backend/routing/rules.py`. Every applicable rule fires; the outcome comes from the first match in
Phase 0 precedence order; the priority is the strongest across all of them.

| Code | Trigger |
| --- | --- |
| E-01 | Confidence below the floor |
| E-04 | Above the automated authority limit |
| E-05 | Policy not in force at the date of loss |
| E-06 | A possible exclusion is engaged |
| E-11 | Emergency indicators |
| E-12 | Vulnerable customer |
| E-16 | Incomplete or degraded analysis |

Each reason names the observation, the threshold and the source, so a reviewer can see *why*
rather than being told the AI decided. Nothing in the module can produce "automated path" from a
failure: a raising rule, an empty agent output or a crashed agent all escalate.

Two pathway flags are operational only and carry no medical or personal detail: emergency
(priority handling) and vulnerable customer (supported contact by recorded preference).

---

## 12. X-Verba / VSL governance architecture

Full design: [`docs/GOVERNANCE_ENFORCEMENT.md`](docs/GOVERNANCE_ENFORCEMENT.md).
Policy catalogue: [`docs/GOVERNANCE_POLICY_CATALOGUE.md`](docs/GOVERNANCE_POLICY_CATALOGUE.md).

### The claim, in one sentence

When this system is about to commit to handling a claim automatically, a real `vsl_core` PreNode
and three real `vsl_core` Invariants run **first**, the irreversible write is passed **into** the
gate as a callable so no denial path can reach it, and every decision is recorded in a
hash-chained `VerbaLedger` that the framework's own `audit()` can check — and can fail.

### Three verdicts that must never be merged

A claim produces three separate answers, and reading any one as another is the
failure this architecture is built to prevent:

| | Business routing | LLM governance (CP-13) | Automated-action governance (CP-14) |
| --- | --- | --- | --- |
| Question | where should this claim go? | may we send these facts to a model? | may this claim be handled automatically? |
| Decided by | business rules (Phase 0 decision table) | INV-04 | PN-01 + INV-01/02/03 |
| Typical answer for a NZD 42,000 claim | `HUMAN_REVIEW_REQUIRED` | `PERMITTED` | `DENIED` |
| Consequence | the claim goes to a person | the model is called | the automated action never runs |

A VSL permission for an LLM call is **not** permission for the claim's
consequential action. The console prints them as three separate strips for that
reason, and `GovernanceOutcome` exposes `automated_action_allowed` as a distinct
field from `permitted` so no caller can read the gate returning as the action
being approved.

### The governed commitment points

The X-Verba spec §1 names what counts: *"whenever code commits to something it
cannot take back: **an LLM call**, a payment, a database write, an outbound
message, a deployment, a handover to another agent."*

| | CP-13 — the LLM call | CP-14 — the automated claim action | CP-09 / CP-12 — the claim-state write |
| --- | --- | --- | --- |
| Where | `agents/base.py :: narrate()` | `gates.py :: govern_automated_route()` | `review_service.py :: apply_routing()` |
| Gate | `govern_llm_narration(perform=…)` | the Invariant block, before `perform()` | `govern_automated_route(perform=…)` |
| What it protects | data leaving for a third party | handling a claim without a person | the irreversible write + queue placement |
| Rules | INV-04 + the TerminalState | INV-01/02/03 | PN-01 + the TerminalState |
| On denial | the provider is never reached | the automated action never runs | the write never happens |

CP-14 and CP-09/CP-12 are enforced by the same gate call, in that order: the
Invariants decide whether this claim may be handled automatically *at all*, and
only a claim that clears them reaches the write. All three share one
`TerminalState`, so a claim suspended at any point is refused at the others — an
LLM call is an automated step, and "no automated way out" means no automated
step, not "no writes".

### Routing and governance are separate concerns

The architecture this project does **not** implement:

```
NZD 42,000  ->  Human Review  ->  VSL: PERMITTED  ->  automated action
```

That reads "permitted" because the Invariants were asked about a route nobody
had proposed. It is a rubber stamp: governance answering a question that was
already settled, and reporting approval for an action it never examined.

What it implements instead:

```
NZD 42,000
   -> business rule: above the automated authority limit
   -> automated-action commitment point (CP-14)
   -> INV-02 evaluated on the claim's own facts
   -> DENIED  (observed 42,000 against a limit of 20,000)
   -> no automated action
   -> Human Review  /  TerminalState if it had been attempted
```

The Invariants are evaluated on the claim, always, never conditioned on what
routing proposed. `_policy_in_force`, `_within_automated_authority` and
`_no_auto_approval_under_exclusion` in `governance/policy.py` take the
candidate's own fields and nothing else.

What *does* change with routing is the **severity** of a denial, and the ledger
records both cases differently:

| | Routing already chose a person | The layer above attempted it anyway |
| --- | --- | --- |
| `automated_action_attempted` | `False` | `True` |
| Verification result | `SUFFICIENT` — governance worked | `INSUFFICIENT` — an incident |
| TerminalState | none | `claim-automation-suspended` |
| `SPECIFICATION_UPDATE` | not written | written |
| What a person owes | nothing | a root-cause analysis before re-enablement |

Recording a routine denial as `INSUFFICIENT` would demand a specification update
for every large claim, and audit check 4 would fail permanently on ordinary
traffic — the trap the spec names explicitly.

### The ordering, in the code

```python
# backend/agents/base.py -- the agent's own call site
outcome, result = asyncio.run(
    govern_llm_narration(
        candidate,
        perform=lambda: self._llm.narrate(request),   # handed IN, not called here
    )
)
```

```
agent  ->  VSL gate  ->  Gemini          NOT:   agent  ->  Gemini  ->  VSL
```

The provider call is passed **into** the gate. Inside `govern_llm_narration`,
`perform()` appears exactly once, on the last line of the proceed path, and
every denial path returns above it. On a denial nothing about the provider is
touched: no `NarrationRequest` goes anywhere, no `httpx` client is built, no
socket opens, and `GEMINI_API_KEY` is never read.

The gate is deliberately **not** inside the Gemini provider. A provider that
gated itself could stop gating itself, and the ordering would be invisible at
the one place a reviewer actually looks. Three tests enforce this: one reads the
gate's source and asserts the call site sits after every `await`, one reads
`narrate()` and asserts the gate appears before the provider, and one asserts no
LLM module mentions the gate at all.

### Proving a denial did not call the model

The difference between correct and incorrect governance is invisible in the
output — both produce a result that says "denied". The only proof is a count:

```
CASE A — VSL PERMIT
  governed LLM calls    5   permitted=5 blocked=0
  Gemini invocations    5
  HTTP requests to API  5  -> https://generativelanguage.googleapis.com/v1beta/interactions

CASE B — VSL DENY (INV-04 no-customer-data-egress)
  governed LLM calls    5   permitted=0 blocked=5
  Gemini invocations    0   <-- ZERO
  HTTP requests to API  0   <-- ZERO
    intake      vsl=DENIED    llm_call=BLOCKED
    policy      vsl=DENIED    llm_call=BLOCKED
    validation  vsl=DENIED    llm_call=BLOCKED
    assessment  vsl=DENIED    llm_call=BLOCKED
    fraud_risk  vsl=DENIED    llm_call=BLOCKED
  routing (unchanged)   AUTOMATED_PATH_RECOMMENDED
  claim went to         Human Review
```

Case B is produced by a bug injected into the layer *above* the gate — an agent
that starts putting the policyholder's name in the narration payload. No
threshold is changed to manufacture it. The first agent's violation enters the
TerminalState; the remaining four are refused because the claim is suspended.

The API publishes this as `llm_governance`, and each agent carries its own
`narration_governance` with the load-bearing field `llm_called`. The console
shows the two facts separately — **VSL governance: PERMITTED/DENIED** and **LLM
call: EXECUTED/BLOCKED** — because conflating them is exactly the failure this
refactor removed.

### Why "before the action" is structural, not a convention

```python
governance, _ = await govern_automated_route(
    _governance_candidate(claim, intelligence),
    perform=lambda: self._apply_outcome(claim, intelligence, routing, outcome),
)
```

`apply_routing` does not check governance and then decide whether to write. It hands the write in.
Inside `govern_automated_route`, `perform()` appears **exactly once**, on the last line of the
proceed path; every denial path returns above it. A denied action is therefore not "checked and
skipped" — the code that would take it is unreachable.

A test reads the function's own source and asserts that ordering, so the guarantee survives a
future edit.

### The module

```
governance/
├── __init__.py     deliberately empty of re-exports
├── policy.py       WHAT is governed — declarations only, vsl_core + stdlib only
├── gates.py        HOW it is enforced — the single call site
├── ledger.py       PROOF — the hash-chained VerbaLedger
└── audit_cli.py    verify / audit / certify / conformance / summary
```

Reading order for a newcomer: **policy → gates → ledger** (what, how, proof).

### Specification

`home-storm-claims-automation` **v0.4.0-poc**, approved by a named authority, bound with
`Proofing` and activated. `Specification.activate()` refuses without a `Binding`, and a `Binding`
refuses to exist without verified `Proofing` — the framework structurally enforcing "new versions
require proofing and approval before activation".

Marked `-poc` deliberately: the thresholds it binds are proposals awaiting business approval, so it
is **not** an insurer-approved specification and must not be presented as one.

## 13. PreNode

**PN-01 `automation-confidence`** — a soft gate: *is the system confident enough to proceed?*

| Property | Value |
| --- | --- |
| Maps from | escalation rule E-01 |
| Monitor | returns a real `GammaEstimate` |
| Γ threshold | `ROBUST_GAMMA_DEFAULT_THRESHOLD` = 1.1 |
| Decision boundary | 0.80 (POC-proposed) |
| **Effective confidence floor** | **0.8148** — derived, not chosen |
| Fallback | `ROUTE_TO_HUMAN_QUEUE` |
| `denial_key` | `vsl_denial__automation_confidence` |

Gamma is `(p/(1-p)) / (t/(1-t))` — **divided by the boundary odds, not by 0.5.** That division is
load-bearing: using the raw odds silently assumes a boundary of 0.5, and at our boundary of 0.80
the gate would wave through work it should stop, with no error raised anywhere. Γ = 1.0 means
"exactly on the boundary".

The floor is derived by solving Γ ≥ 1.1 at t = 0.80. It is *higher* than the boundary, because
robustness costs something.

**A PreNode denial is governance working, not governance failing.** It writes a **SUFFICIENT**
verification and reroutes to a person. Recording it as INSUFFICIENT would make audit check 4 demand
a specification update for every routine low-confidence claim, failing the audit permanently on
normal traffic — and everyone would learn to ignore it.

## 14. Invariants

Hard rules: *is this action ever acceptable?* A violation raises `InvariantViolation` — there is no
return value to ignore.

| ID | Name | From | `denial_key` |
| --- | --- | --- | --- |
| INV-01 | `policy-in-force` | E-05 | `vsl_denial__policy_in_force` |
| INV-02 | `automated-authority-limit` | E-04 | `vsl_denial__automated_authority_limit` |
| INV-03 | `no-auto-approval-under-exclusion` | E-06 | `vsl_denial__no_auto_approval_under_exclusion` |
| INV-04 | `no-customer-data-egress` | **new** — governs CP-13 | `vsl_denial__no_customer_data_egress` |

INV-01…03 govern the **automated claim action** (CP-14): may this claim be
handled without a person? INV-04 is checked immediately before the **LLM call**
(CP-13) and asks a different question, so the commitment points carry different
rule sets — running the authority limit against a narration payload would be
asking a money question about prose, and passing INV-04 says nothing whatever
about whether the claim may be settled automatically.

**INV-04 is new in this refactor and is not a Phase 0 escalation rule**, because
Phase 0 had no LLM commitment to govern: Phase 2 introduced the model and Phase
4A made it a real network call. It derives from the standing project constraint
that no real customer data enters this system and none leaves it. Flagged
explicitly so it can be rejected on review rather than absorbed silently.

Every gate has its **own** `denial_key`. Two gates sharing one makes the second router read the
first gate's denial — with four gates, exactly the conditions for that bug.

Two design decisions worth stating:

**They judge the claim, not the routing decision.** An earlier version
short-circuited to "permitted" whenever routing had not proposed the automated
path, which meant a NZD 42,000 claim produced a VSL verdict of PERMITTED — the
Invariants answering a question nobody had asked. They now evaluate the
candidate's own facts every time, and the *severity* of a denial is what depends
on routing: a denial on a claim nobody tried to automate is routine and written
`SUFFICIENT`; the same denial on an attempted action is an incident, written
`INSUFFICIENT`, and enters the TerminalState. Without that split, every
human-review claim would suspend automation and the terminal state would mean
nothing.

**An unknown value is not a violation.** INV-02 treats a missing estimate as acceptable. An
Invariant means "proceeding anyway is always wrong"; with no estimate we do not know that
proceeding is wrong, we know that we do not know — which is a review matter the business rules
already handle. An Invariant that fires on ignorance rather than on breach is not a hard rule, it
is noise.

### What the Invariants are actually for

They mirror rules the routing layer already enforces, so **in normal operation they never fire** —
and that is the point, not a weakness. They exist to catch the layer above being wrong: a bug, a
bad deploy, a threshold edited in the wrong file. A test breaks the routing layer deliberately so
it recommends the automated path for a NZD 240,000 claim; INV-02 stops the write anyway, suspends
automation and records why.

If an Invariant ever fires in production, the correct reading is **"the layer above is wrong"** —
which is why a violation writes an INSUFFICIENT verification *and* a `SPECIFICATION_UPDATE`
registering the active specification for review.

## 15. TerminalState

**`claim-automation-suspended`**, `requires_human_authorised_transition=True`.

```
Invariant violated → DENIED → TerminalState → no automated way out
```

A suspended claim returns `suspended` on every subsequent attempt, **before the PreNode even
evaluates**. Nothing lifts it on its own: no timeout, no retry, no confidence score, no successful
re-analysis. The claim itself is unaffected — it is handled by a person.

## 16. Human re-enablement — the only exit

`POST /api/review-queue/{claim_id}/re-enable-automation`, with a named authority, a root-cause
analysis and a specification-update proposal.

Routed through `vsl_core.governance.request_re_enablement`, which produces the successor `Instance`
and the `HumanAuthorisedTransition` **together**, so a caller cannot obtain one without the other.
`Evidence` is a validated type — an empty root-cause analysis is refused at construction, by the
framework.

The `HUMAN_AUTHORISED_TRANSITION` is written `caused_by` the `TERMINAL` entry it resolves, which is
what satisfies audit check 5.

**Re-enabling automation decides nothing about the claim.** The reviewer still holds it; only
future automated steps become permitted again. It is a review action on the claim, **not** a button
on the governance dashboard — a dashboard that can change governance state is a second, unaudited
enforcement path.

## 17. Governance vs AI vs business rules vs human decision

Four authorities, kept apart in the code, in the API and on screen:

| Authority | Answers | Where it lives | Recorded in |
| --- | --- | --- | --- |
| **AI agents** | "What do I observe about this claim?" | `backend/agents/` | the analysis result, marked recommendation-only |
| **Business rules** | "Where should this claim go?" | `backend/routing/` | the routing decision, with named reasons |
| **VSL governance** | "May the system take this action?" | `governance/` | the VerbaLedger |
| **Human reviewer** | "What happens to this claim?" | the review screen | the review action, `decision_source: "human"` |

The distinction the whole POC turns on:

| | Phase 3 — business-rule routing | Phase 4 — runtime governance |
| --- | --- | --- |
| Nature | a recommendation about handling | a permission to act |
| If wrong | the claim goes to the wrong queue | the system does something it must not |
| Bypassable? | it is advice; the layer above can ignore it | no — the side effect is inside the gate |
| Reviewable | read the reasons | `audit()`, `verify_integrity()`, a certificate |

**VSL never decides whether a claim is approved, declined or settled.** It decides whether an
automated *step* may proceed. Governance can only ever make an outcome more conservative — a test
sweeps the parameter space to confirm no combination turns a denial into an approval.

### The VerbaLedger

```
MONITOR ──caused_by──> PRE_NODE ──caused_by──> VERIFICATION
                                                    │
                                    (INSUFFICIENT)  ├──> TERMINAL ──> HUMAN_AUTHORISED_TRANSITION
                                                    └──> SPECIFICATION_UPDATE
```

- Append-only, hash-chained, `fsync=True` — a record lost in a page cache never happened, and a
  governance record that never happened is worse than one that says "denied".
- **`caused_by` on every entry after the first.** Without it, `audit()` falls back to a
  "same identity, later timestamp" heuristic that can match an unrelated PRE_NODE and report a
  **false pass** under concurrency. A claims queue is exactly that concurrency.
- A MONITOR is written for **every** request, not only for incidents, so audit check 1 has
  continuous evidence rather than only-on-incident evidence.

### `verify_integrity()` ≠ `audit()`

| | Question | Mechanism |
| --- | --- | --- |
| `verify_integrity()` | Were these records edited? | re-walks the hash chain |
| `audit()` | Do these records describe a governed process? | the five checks |

A ledger can be perfectly intact and describe a process with a terminal state nobody resolved. It
can also pass every structural check while having been rewritten. Reporting one as though it
answered the other is the easiest way to produce a governance claim that is false, so `certify`
requires both.

### The five audit checks

| # | Check | Meaning here |
| --- | --- | --- |
| 1 | `no_monitoring_gaps` | monitoring is continuous |
| 2 | `drift_flagged_monitor_has_pre_node` | every drift signal reached a gate |
| 3 | `pre_node_has_verification` | every gate decision was verified |
| 4 | `insufficient_verification_has_specification_update` | every governance failure was registered for review |
| 5 | `terminal_has_human_authorised_transition` | every terminal state was lifted by a person |

**An open terminal state fails check 5 by design, and the CLI exits 1.** That is the ledger telling
the truth about unfinished governance, not a defect.

Check 1 is reported as **NOT ASSERTED** unless you pass `--max-monitor-gap-seconds`. `vsl-core`
deliberately has no universal default for monitoring cadence, and passing `None` *skips* the check
while reporting it as passed; repeating that as "passed" would overstate what was checked, so the
CLI, the API and the dashboard all keep it separate — and the dashboard styles it visibly
differently from a pass.

### Derived assurance is LOW, and stays LOW

VSL will not let you assert an assurance level. You supply two facts and it derives one:

| Fact | Value | Meaning |
| --- | --- | --- |
| F1 — pre-commitment | `True` | the gate runs before the commitment |
| F2 — modification | `NONE` | the gate does not change the energy landscape |
| **Derived** | **LOW** | output-layer control |

LOW is the correct answer for this POC and is reported as LOW in the API, on the dashboard and in
the docs. It means the gates block a bad action; they do not change how the model decides. HIGH
would require a formation-layer change — loss function, feature space, training — which this POC
does not make. Claiming more would be a fabrication.

## 18. Synthetic data

**Synthetic only.** Every record is fabricated; emails use the reserved `@example.invalid` domain.
Spec: [`docs/SYNTHETIC_DATA_SPEC.md`](docs/SYNTHETIC_DATA_SPEC.md).

| File | Records | Purpose |
| --- | --- | --- |
| `customers.jsonl` | 5 | Policyholders, including one vulnerable customer with an accessibility need |
| `policies.jsonl` | 5 | Home policies, one per customer |
| `policy_wordings.jsonl` | 1 wording, 12 sections | What the Policy Agent retrieves from and cites |
| `historical_claims.jsonl` | 7 | The Fraud & Risk Agent's evidence base |
| `risk_rules.jsonl` | 8 | Risk indicator definitions, as data rather than prompt text |

Each policy carries a `scenario_note` naming the decision row it exists to exercise:

| Policy | Exercises |
| --- | --- |
| `POL-HOME-20117` | Clean cover — the straightforward claim |
| `POL-HOME-20233` | Lapsed at the date of loss — INV-01 (D-03) |
| `POL-HOME-20349` | Recent inception + cover change + prior flagged claim — elevated risk |
| `POL-HOME-20455` | Maintenance and wear exclusions — INV-03 (D-09) |
| `POL-HOME-20512` | High sums insured — above the automated authority limit (D-08) |

Lodged claims go to `data/claims/` and the ledger to `data/ledger.jsonl`; both are gitignored —
that is runtime state, not seed data.

## 19. Project structure

```
AI_Insurance_Claims_Agent/
├── README.md                    ← the only project README
├── requirements.txt  pytest.ini  .env.example  .gitignore
│
├── governance/                  X-Verba / VSL layer
│   ├── policy.py                WHAT is governed (vsl_core + stdlib only)
│   ├── gates.py                 HOW it is enforced (the single call site)
│   ├── ledger.py                the VerbaLedger
│   └── audit_cli.py             verify / audit / certify / conformance / summary
│
├── backend/
│   ├── app/
│   │   ├── main.py              app, CORS, customer-safe exception handlers
│   │   ├── config.py  errors.py
│   │   ├── api/                 health, assistant, claims, intelligence, review, governance
│   │   ├── schemas/             assistant, claim, intelligence, review, governance
│   │   ├── domain/              claim_state, thresholds, reference
│   │   ├── services/            assistant, claim, intelligence, review, governance
│   │   └── repositories/        claim, analysis, review_queue, reference_data
│   ├── agents/                  intake, policy, validation, assessment, fraud_risk,
│   │                            conversation (Phase 5) + contracts
│   ├── conversation/            Phase 5 — contracts, fields (validation), builder, store
│   ├── graph/                   builder, state, nodes, escalation, governed, finalize,
│   │                            conversation_graph (Phase 5)
│   ├── routing/                 rules, router, contracts
│   ├── bootstrap.py             loads .env before anything reads os.environ
│   └── llm/                     base, stub, gemini_provider, http_provider, factory, verify_cli
│
├── frontend/src/
│   ├── App.jsx                  shell; claims assistant ⇄ claim form ⇄ claims console
│   ├── api/client.js            the only place the UI talks to the backend
│   ├── assistant/               Phase 5 — the conversational claims assistant
│   ├── claim/                   the customer FNOL wizard and its six steps (kept)
│   ├── staff/                   INTERNAL — console, report, queue, review, governance
│   ├── components/              form controls, progress steps
│   └── __tests__/               vitest + Testing Library
│
├── data/
│   ├── synthetic/               seed datasets (tracked)
│   ├── claims/                  lodged claims + conversations (gitignored)
│   └── ledger.jsonl             the VerbaLedger (gitignored)
│
├── docs/                        PROJECT_PLAN · CLAIM_JOURNEY · DECISION_TABLE ·
│                                SYNTHETIC_DATA_SPEC · COMMITMENT_POINTS ·
│                                HUMAN_ESCALATION_POLICY · ROUTING_MODEL ·
│                                GOVERNANCE_POLICY_CATALOGUE · GOVERNANCE_ENFORCEMENT · API
│
└── tests/backend/               pytest (frontend tests live beside their components)
```

## 20. Installation

PowerShell shown; the equivalents work on macOS and Linux.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# VSL-LangGraph must be installed SEPARATELY with --no-deps.
# It pins its vsl-core dependency to a stale URL that conflicts with requirements.txt,
# so a normal install would fight the line already satisfied above.
pip install --no-deps "vsl-langgraph @ git+https://github.com/supersemantics/VSL-Langgraph.git@d2f4b736c8e321d236e955622a71f7a9c02981ee"

cd frontend; npm install; cd ..
```

Verify both governance packages resolved correctly:

```powershell
python -c "import vsl_core, vsl_langgraph; print('ok')"
python -m governance.audit_cli conformance      # expects CONFORMANT
```

### Governance dependency traps — each one fails quietly

| Trap | Consequence if missed |
| --- | --- |
| The distribution is `super-semantics-vsl`; the **import** is `vsl_core` | `pip install vsl-core` installs an unrelated PyPI stub, and every governance import resolves to the wrong package |
| There are no releases or tags | Without a pinned commit SHA the build is not reproducible |
| VSL-LangGraph pins a stale `vsl-core` URL | A normal install conflicts; it needs its own `--no-deps` command, which cannot be expressed per-package inside `requirements.txt` |

## 21. Environment configuration

Everything has a working default, so the POC runs with no configuration and no API key. To change
something, copy `.env.example` to `.env` (`Copy-Item .env.example .env`). `.env` is gitignored and
must never be committed.

| Variable | Default | Effect |
| --- | --- | --- |
| `LLM_PROVIDER` | `stub` | `gemini` for Google Gemini; `openai`/`http` for an OpenAI-compatible endpoint |
| `GEMINI_API_KEY` | _(empty)_ | Required for `gemini`. Without it, narration falls back and reports `llm_degraded` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Which Gemini model answers |
| `DECISION_THRESHOLD` | `0.80` | The decision boundary; the confidence floor is derived from it |
| `AUTOMATED_AUTHORITY_LIMIT_NZD` | `20000` | INV-02's limit |
| `CONFIDENCE_CALIBRATION_ERROR` | `0.10` | Feeds the `GammaEstimate` |
| `VSL_LEDGER_PATH` | `data/ledger.jsonl` | Where governance decisions are recorded |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Frontend origin |

Changing `DECISION_THRESHOLD` or `AUTOMATED_AUTHORITY_LIMIT_NZD` changes what governance enforces.
Both are POC proposals awaiting business approval, and neither should be changed silently.

### `.env` is loaded explicitly

`python-dotenv` being installed does **not** load `.env`. Nothing reads that file
until something calls `load_dotenv()`, and until then `os.environ.get("LLM_PROVIDER")`
returns `None` and the factory falls through to the stub — which is what made a
correctly-configured project report `provider: stub`.

`backend/bootstrap.py` owns that call. It is dependency-free so the app, the LLM
factory and the governance layer can all use it without an import cycle:

```python
from bootstrap import load_project_env
load_project_env()          # idempotent; resolves <project root>/.env
```

It is called at the top of `app/main.py` *before* any module reads `os.environ`,
and again inside `get_llm_provider()` so the CLI diagnostics and the tests take
the same path as the server. `load_dotenv(..., override=False)` — an exported
shell variable beats the file, which is what you want when overriding a single
setting for one run.

Verify the selection without starting the server:

```powershell
python -m llm.verify_cli                 # human-readable
python -m llm.verify_cli --json          # machine-readable; exit 0 = a live model answered
```

### Secret handling

The key is read from the environment and nowhere else. It is never hard-coded,
never written to a log, never placed in a `NarrationResult`, never returned by
the API, and never included in an exception message — provider failures are
logged by exception **class name** only, because an exception's string form can
carry a URL and a URL is one refactor away from carrying a key.

Diagnostics report *existence*, not value:

```
  GEMINI_API_KEY    configured: true  ****wxyz  (36 chars)
```

`.env` and `.env.*` are gitignored (`.env.example` excepted); `.env.example`
carries placeholders only.

A failure is reported, not hidden. When Gemini cannot answer, the provider keeps
reporting itself as `gemini` with `degraded: true` plus a fixed reason code —
`api_key_not_configured`, `transport_error`, `unusable_interaction_status` or
`empty_response_text` — which reaches the console beside the provider name.
Rewriting the provider to `stub` on failure is what made a configuration problem
look like a deliberate choice of provider.

## 22. Run the backend

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

- API: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>

## 23. Run the frontend

```powershell
cd frontend
npm run dev          # http://localhost:5173
```

The backend must be running. To point elsewhere, set `VITE_API_BASE_URL`.

## 24. Using it

Open <http://localhost:5173>. The customer portal is the default; the claims console is behind the
header switch. The customer view shows **nothing** internal — no risk indicators, no policy
interpretation, no confidence scores, no escalation reasons. A test asserts it.

## 25. API overview

Reference: [`docs/API.md`](docs/API.md).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness |
| `POST` | `/api/assistant/conversations` | Start a claims conversation. Creates no claim |
| `POST` | `/api/assistant/conversations/{id}/messages` | One customer turn. **Never creates a claim** |
| `GET` | `/api/assistant/conversations/{id}` | Read the structured conversation state |
| `POST` | `/api/assistant/conversations/{id}/confirm` | **The only conversational route to a claim** |
| `POST` | `/api/claims` | Lodge a storm-damage FNOL → `Submitted` |
| `GET` | `/api/claims/{id}` | Read a lodged claim |
| `POST` | `/api/claims/{id}/analyze` | Run the workflow (**internal**) |
| `GET` | `/api/claims/{id}/analysis` | Read the stored result (**internal**) |
| `GET` | `/api/review-queue` | Claims awaiting a person (**internal**) |
| `GET` | `/api/review-queue/{id}` | Everything a reviewer needs (**internal**) |
| `POST` | `/api/review-queue/{id}/action` | Record a POC review action (**internal**) |
| `POST` | `/api/review-queue/{id}/re-enable-automation` | Lift a TerminalState (**internal**) |
| `GET` | `/api/governance` | The governance dashboard (**internal**) |
| `GET` | `/api/governance/configuration` | The active specification (**internal**) |
| `GET` | `/api/governance/ledger` | Ledger entries, newest first (**internal**) |
| `GET` | `/api/governance/ledger/{id}` | One claim's governance trail (**internal**) |
| `GET` | `/api/governance/audit` | Integrity + the five checks (**internal**) |

Everything under `/api/governance` is **GET only** — a test reads the OpenAPI spec and asserts it.

Endpoints marked **internal** return policy interpretation, risk indicators and vulnerability
flags, none of which may reach a customer. There is no authentication in the POC; the separation is
architectural only, and Phase 6 enforces it.

## 26. How to submit a claim

1. Open <http://localhost:5173> and choose **Start a claim**.
2. Work through *Your details → Property → Storm damage → Review*. Use `POL-HOME-20117` as the
   policy number (a seeded synthetic policy).
3. The Review page has a *Change …* link for every section; submitting re-validates all three data
   steps, so a value edited from Review cannot slip through.
4. Note the claim reference on the confirmation screen.

The claim is now `Submitted`. Nothing has been analysed, routed or governed yet.

## 27. How to analyse a claim

Switch to the **Claims console**, paste the reference into *Analyse a claim*, and run it.

The five agents run, the twelve escalation rules decide where the claim should go, the governance
gate decides whether the system may make that happen, and the report shows all three: the routing
decision with its named reasons, the governance strip with the specification, the gate result, the
confidence against its floor and the derived assurance, and the agent panels beneath.

## 28. How Human Review works

If the claim was escalated, the **Review queue** tab lists it, urgent first, with its reasons and
priority. Open it for the full review screen — six sections of what is known, and then the
reviewer's own decision panel, visually and structurally separate.

If governance suspended automation, the row carries an **Automation suspended** chip, the review
screen shows which Invariant was violated and which terminal state was entered, and the
re-enablement form appears — requiring a name, a root-cause analysis and a specification-update
proposal.

## 29. How to view Governance

The **Governance** tab in the claims console. It shows:

- **Status** — ledger integrity, audit result, derived assurance
- **What governance did** — claims governed, decisions, drift signals, actions denied, PreNode
  denials vs Invariant violations, open terminal states, human transitions
- **Audit checks** — pass / fail / not asserted, each rendered differently
- **Suspended claims** — and how each one gets out
- **Actions governance stopped** — PreNode (rerouted) and Invariant (halted) kept distinct
- **What is enforced** — the specification, the PreNode, the Invariants, the thresholds
- **Ledger events** — newest first, with each entry's causal link

The screen is read-only and will not render a failing audit as a green tick.

## 30. How to run tests

```powershell
python -m pytest        # backend — 262 tests
cd frontend; npm test   # frontend — 59 tests
```

**Backend (333).**

| File | Tests | Covers |
| --- | --- | --- |
| `test_claims_api.py` | 17 | Lodgement, validation, customer-safe errors |
| `test_claim_state.py` | 10 | The six states, the transition matrix, internal statuses |
| `test_agents.py` | 29 | Each agent individually, including its failure behaviour |
| `test_workflow.py` | 23 | The graph, the six scenarios, failing closed |
| `test_intelligence_api.py` | 10 | The analysis endpoints and their boundaries |
| `test_routing.py` | 28 | The twelve routing scenarios and the rule catalogue |
| `test_review_api.py` | 23 | The queue, the review screen, the four actions |
| **`test_llm_providers.py`** | **50** | **Phase 4A — the Gemini provider, its boundary, and why it degraded** |
| **`test_llm_governance.py`** | **27** | **CP-13 — the LLM call as a governed commitment** |
| **`test_governance.py`** | **65** | **Phase 4 — governance, including CP-14 and the dashboard** |
| **`test_assistant.py`** | **51** | **Phase 5 — the conversational assistant and its governed call** |

The governance tests are organised around the ways a governance layer is usually faked — the
constructs are checked with `type(x) is vsl_constructs.PreNode` (a duck-typed mock would pass
`isinstance`); the enforcement ordering is checked by reading the function's own source; the hash
chain is checked by editing a payload on disk and watching `verify_integrity()` go False; the audit
is checked by making it fail and then pass.

**Frontend (78).** The customer wizard (10), the claims console (12), the review queue and claim
review (16), **governance (25, including the CP-13 permit/deny display and the three separate
verdicts on a NZD 42,000 claim)**, **the claims assistant (15)**.

The Phase 1–4 frontend tests were not rewritten when Phase 5 changed the default
customer view. They open the **Claim form** tab and then assert exactly what they
always asserted — a journey that still works should still be tested.

No existing test was deleted or weakened to accommodate governance. The Phase 2 test that asserted
governance did *not* yet exist was **inverted, not removed** — it now asserts the constructs are
genuine `vsl_core` types.

## 31. How to run governance conformance

```powershell
python -m governance.audit_cli conformance   # the framework's own adapter suite
python -m governance.audit_cli verify        # hash chain intact?
python -m governance.audit_cli audit         # the five checks
python -m governance.audit_cli certify       # a VerbaCertificate, or a refusal
python -m governance.audit_cli summary       # what happened, in numbers

python -m governance.audit_cli audit --json                            # machine-readable
python -m governance.audit_cli audit --max-monitor-gap-seconds 3600    # assert check 1
```

Exit codes: **0** passed, **1** failed, **2** could not run (no ledger, empty ledger, bad
arguments). Non-zero on failure is the point — an audit that only prints is an audit nobody
notices. This is what CI would run.

An **empty ledger is refused** for `audit` and `certify`. An empty ledger satisfies every check
vacuously; it is not evidence of governance.

There is **no `x-verba scan` tool** — neither distribution ships a console entry point or a
static-analysis module. No static Γ figure is reported anywhere, because computing one would mean
inventing it. `conformance` runs `vsl_core.conformance.suite.run_conformance_suite` against the
adapter compiling our gates, and reports **CONFORMANT** — a claim about the *adapter contract*, not
about the ledger and not about runtime Gamma. The three are kept separate.

## 32. Example permit scenario

A clean claim on `POL-HOME-20117`: policy in force, storm covered, ~NZD 3,200 estimate, no
exclusions. The workflow's confidence is the *lowest* any agent reported — a minimum, not a mean,
because an average lets a confident intake paper over an unconfident policy read, which is exactly
the claim you want a person on. Here that is 0.85.

```
routing      AUTOMATED_PATH_RECOMMENDED
PN-01        passed   (confidence 0.85 ≥ floor 0.8148)
INV-01/02/03 passed
governance   proceed  →  side effect PERFORMED
ledger       MONITOR → PRE_NODE → VERIFICATION (SUFFICIENT)
```

Note how little headroom that is: 0.85 against a floor of 0.8148. A slightly less certain policy
read and the same claim goes to a person.

The claim moves to `Assessment`. Still no approval, no settlement, no customer contact.

## 33. Example deny / escalation scenario

**PreNode denial — rerouted.** The same claim with confidence 0.55:

```
PN-01        DENIED   (0.55 below the 0.8148 floor)
governance   human_queue  →  side effect NOT performed
fallback     ROUTE_TO_HUMAN_QUEUE  →  claim in Human Review, on the queue
ledger       MONITOR → PRE_NODE (denied) → VERIFICATION (SUFFICIENT — governance worked)
```

**Automated action refused — routine.** NZD 42,000, above the authority limit,
and routing has already chosen a person:

```
business routing          HUMAN_REVIEW_REQUIRED
LLM governance (CP-13)    PERMITTED   5 calls, 5 permitted, 0 blocked
INV-02 (CP-14)            DENIED      observed 42,000 against a limit of 20,000
automated_action_allowed  False       attempted False   side effect NOT performed
terminal state            none        — routing and governance agree; nothing is suspended
claim state               Human Review
ledger                    MONITOR → PRE_NODE → VERIFICATION (SUFFICIENT,
                          outcome=automated_action_denied, observed/threshold recorded)
audit                     passes — a person owes nothing here
```

The claim reached a person *and* the automated action was independently refused.
Neither fact was inferred from the other.

**Invariant violation — halted.** An estimate of NZD 64,000 above the authority
limit, where the layer above proposed the automated route anyway:

```
INV-02       VIOLATED
governance   suspended  →  side effect NOT performed
terminal     claim-automation-suspended,  internal_status automation_suspended
ledger       MONITOR → PRE_NODE → VERIFICATION (INSUFFICIENT) → TERMINAL → SPECIFICATION_UPDATE
audit        check 5 FAILS, exit 1, no certificate   ← correct: governance is unfinished
retry        still suspended — before the PreNode even evaluates
exit         a named authority + root cause + proposal → HUMAN_AUTHORISED_TRANSITION
             → audit passes 5/5, certificate issued
```

Across a run of six governed calls — one pass, one PreNode denial, three Invariant violations and
one retry of a suspended claim — **the side effect fired exactly once.**

That is the sentence this POC exists to be able to say: *the system does not merely recommend a
safe action; governance technically prevents an unauthorised consequential action from executing.*

## 34. Current POC limitations

Written down rather than worked around.

1. **Suspension state lives in process memory.** It does not survive a restart and is not shared
   across workers. **This is not solved and is not pretended to be.** What exists is
   `rebuild_suspensions_from_ledger()` — the production re-derivation (a TERMINAL with no later
   HUMAN_AUTHORISED_TRANSITION is an open suspension), implemented and tested, so the move to Redis
   is a storage swap rather than a redesign. A test asserts both the loss and the recovery.
2. **Derived assurance is LOW** — output-layer control only.
3. **`Fallback`'s fields are declarative.** `vsl-langgraph` warns at import that `gated_node` does
   not consume `Fallback`; the warning is left visible rather than suppressed, and
   `ROUTE_TO_HUMAN_QUEUE` is implemented by us.
4. **`Proofing` is a documentation review, not a formal proof** — the specification says so.
5. **The governance authority is a POC placeholder.**
6. **Every threshold is a POC proposal**, not an insurer-approved rule.
7. **No authentication** on any internal endpoint, governance dashboard included.
8. **Storage is JSONL files.** The ledger uses `fsync=True`, but it is still a file.
9. **`verify_integrity()` detects tampering; it does not prevent it.** `current_checkpoint()`
   exposes the tip an external witness would need to anchor the chain; nothing transmits it.
10. **No document upload.** The FNOL records *whether* photos exist; it does not accept files.
11. **No customer communication** at any point.
12. **No claim locking.** Re-analysis can move a claim out of Human Review if the inputs change.
13. **`complete_review` is bookkeeping**, and deliberately does not model the real outcomes
    (accept, decline, part-settle) a claims system needs.
14. **No static governance scan**, because no such tool exists in either distribution.
15. **The Gemini integration has not been exercised against the live API from this repository.**
    It is built to the current Interactions API and its wire format is asserted at the transport
    layer — URL, `x-goog-api-key` header, body shape, response parsing, and every failure path —
    but no request has left this machine, because that needs a key. `python -m llm.verify_cli
    --provider gemini` is how you confirm a real call on a machine that has one, and it exits
    non-zero if the fallback answered instead.
16. **Gemini narration is not cached and not rate-limited.** One analysis makes five governed
    calls, one per agent — so five CP-13 gate evaluations and ten ledger entries per clean
    claim. Correct, and chattier than a real deployment would want.
17. **INV-04 matches identifiers literally**, not by general PII detection. It asks whether a
    known identifier for *this* claim appears verbatim in the outbound payload. A rule that
    guessed at PII would either fire on ordinary traffic and get switched off, or miss the real
    case and be theatre — but a reformatted identifier (spacing, partial, transliterated) would
    pass it.
18. **The CP-13 gate runs `asyncio.run` inside a synchronous agent.** The agents are sync by
    Phase 2 design and the VSL gates are async by framework contract. This works and is tested,
    but it means narration cannot currently run concurrently across agents.

## 35. Phase progress

| Phase | Focus | Status |
| --- | --- | --- |
| 0 | Business & governance foundation | **Documented** — thresholds awaiting approval |
| 1 | Customer claims experience (React FNOL + API) | **Complete** |
| 2 | Claims intelligence (LangGraph + five agents) | **Complete** |
| 3 | Risk & human escalation (routing + review queue) | **Complete** |
| 4 | X-Verba / VSL governance enforcement | **Complete** |
| 5 | Conversational AI claims assistant | **Complete** |
| 6 | Production readiness | Not started |

Full detail, including exit criteria and per-phase implementation records:
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

## 36. Future work

**Phase 4A follow-ups.** Confirm a live Gemini call with `llm.verify_cli` and a real key;
decide whether narration warrants caching or batching (five calls per analysis today); and decide
whether a live model belongs in a demonstration at all, given that it changes only the prose.

**Phase 5 — demonstration and evaluation.** End-to-end scenario scripts (a clean claim, a
low-confidence claim, an authority breach, an elevated-risk claim), a seeded demonstration dataset
with claims in every state, a scripted walkthrough, and evaluation against the success metrics in
`docs/PROJECT_PLAN.md` §16. Document analysis and the Communication Agent, if they are brought into
scope.

**Phase 6 — production readiness.** Authentication and authorisation on every internal endpoint;
durable suspension state (Redis) with the ledger re-derivation already written; a real database in
place of JSONL; external anchoring of the ledger checkpoint; a named governance authority with a
real escalation contact; business approval of every threshold; claim locking during review; and the
real claim outcomes a claims system needs.

---

## 37. Phase 5 — Conversational AI Insurance Claims Assistant

### The product

A customer reporting storm damage no longer meets a six-step form. They say what
happened, and the assistant asks for what it still needs, one question at a
time, until it can show a summary and ask them to confirm.

The form has **not** been deleted. It is behind the **Claim form** tab, it is
the accessible fallback, and every Phase 1–4 test still exercises it. Removing a
working journey to make a new one look like the only option is not an
improvement.

### The approved baseline architecture

```
Customer
   │
   ▼
Conversational Interface            React — frontend/src/assistant/
   │
   ▼
API Layer                           FastAPI — /api/assistant/*
   │
   ▼
LangGraph Orchestrator              graph/conversation_graph.py
   │
   ▼
Insurance Agents                    Conversation Agent (+ the existing five,
   │                                after the claim exists)
   ▼
VSL PreNode + Monitor               PN-02 conversation-extraction-confidence
   │
   ▼
Gamma evaluation / threshold        gamma ≥ 1.1 at the 0.80 boundary → p ≥ 0.8148
   │
   ├── DENY ──────────────► Human Review / deterministic path
   │                        NO GEMINI CALL
   ▼
ALLOW
   │
   ▼
Gemini                              llm/gemini_provider.py
   │
   ▼
Generated Output
   │
   ▼
VSL Invariant                       INV-05 no-fabricated-claim-values
   │                                INV-06 no-claim-decision-in-assistant-output
   ├── VIOLATION ─────────► TerminalState / Human Review
   │                        the output NEVER reaches downstream
   ▼
PASS
   │
   ▼
Business Rules / Action Router      conversation/fields.py validators,
   │                                then routing/ once the claim exists
   ▼
Automated Action  OR  Human Review
   │
   ▼
VerbaLedger                         written explicitly by governance/gates.py
```

This architecture is **frozen**. Later phases extend it; they do not redesign it.

### The conversational flow

```
start conversation           POST /api/assistant/conversations
   → customer describes the incident in their own words
   → assistant identifies what the message contains
   → asks the next required question
   → collects the answer
   → updates structured state
   → validates it deterministically
   → identifies what is still missing
   → repeats
   → claim information complete
   → claim summary
   → CUSTOMER CONFIRMATION       POST .../confirm   ← the only endpoint that creates
   → existing claim creation     ClaimService.submit_claim
   → real claim ID returned      CLM-2026-XXXXXX
```

### Conversation state

Structured, and authoritative. The chat transcript is presentation only.

| | |
| --- | --- |
| `conversation_id` | `CNV-…`, allocated at start |
| `claim_id` | **None until confirmation.** Set once, from the real claim |
| `current_stage` | START → CUSTOMER_INFORMATION → POLICY_INFORMATION → INCIDENT_INFORMATION → DAMAGE_INFORMATION → SAFETY_CHECK → MISSING_INFORMATION → REVIEW → READY_FOR_CONFIRMATION → CUSTOMER_CONFIRMATION → CLAIM_CREATED |
| `collected_information` | field → value, **with the customer's own words attached** |
| `missing_information` | derived from the field catalogue, never stored independently |
| `uncertain_information` | said but not pinned down — neither collected nor simply missing |
| `claim_ready` | every required field collected |
| `customer_confirmed` | the customer pressed Submit |
| `last_asked` | which field the last question was about |
| `messages` | the transcript. Nothing downstream reads a fact from here |

An LLM re-reading its own chat history and re-deciding what it knows is the
architecture this avoids: every turn would be a chance to forget a fact, invent
one, or quietly change one the customer already gave.

`last_asked` is **recorded, not derived**, and that cost a bug worth recording.
Deriving it as "the next required field" looks equivalent and is not: on the
opening turn the assistant has asked nothing, yet the next required field is
`full_name` — so *"A storm damaged my roof last night"* was accepted as the
customer's name. A reply can only answer a question that was actually put.

### The model proposes; the application decides

| Layer | Job | Can it write a claim value? |
| --- | --- | --- |
| Gemini | read a sentence, propose structured values | **No** |
| `conversation/fields.py` | validate each proposal deterministically | **Yes — the only writer** |
| INV-05 | reject output carrying values the customer never said | **No — it can only refuse** |
| the catalogue | derive what is still missing | **No** |

So the worst a broken, jailbroken or hallucinating model can do is propose
nonsense, which is rejected, or propose nothing, which leaves the field missing
and the assistant asking again.

Three specific refusals, each with a test:

- **"Sometime last week"** is not a date. It is recorded as *uncertain* and the
  assistant asks for a specific one, because a wrong date of loss can decide
  whether a policy was in force.
- **A policy number the customer never said** is rejected by INV-05 — the whole
  generated output is discarded, not just that field.
- **`claim_id` and `customer_confirmed`** have no route in at all. They are not
  in the extractable-field allow-list, so they are dropped before any validator
  sees them.

### Claim creation

```
POST /api/assistant/conversations/{id}/confirm   {"confirmed": true}
   → refuse if the claim already exists            409
   → refuse if the conversation is not ready       409
   → refuse if the FNOL will not build             409
   → ClaimService.submit_claim(...)   ← the SAME service the form uses
   → real claim ID
```

**There is no second claim store, no second ID scheme and no second workflow.**
A conversationally-lodged claim is indistinguishable downstream: the same
record, the same states, the same intelligence workflow, the same review queue,
the same governance.

Confirmation is a **separate endpoint** on purpose. A message endpoint that
created a claim when the model judged a reply affirmative would make claim
creation depend on a model reading the word "yeah". Typing *"yes submit my claim
now"* into the message endpoint creates nothing, and a test asserts it.

### Governance at the conversational commitment point

| | |
| --- | --- |
| Gate | `governance/gates.py :: govern_conversation_extraction` |
| Before Gemini | **PN-02** `conversation-extraction-confidence` + Monitor + Gamma |
| After Gemini | **INV-05** `no-fabricated-claim-values`, **INV-06** `no-claim-decision-in-assistant-output` |
| On PreNode denial | the provider is never reached; the deterministic path takes the turn |
| On Invariant violation | the output is discarded, the claim enters `claim-automation-suspended` |
| Derived assurance | **LOW** — output-layer control, as everywhere else in this POC |

Two structural properties, both asserted by tests that read the gate's own
source rather than trusting a comment:

1. `perform` — the Gemini call — is referenced **exactly once**, after the
   PreNode. Every denial path returns above it, so the network call is
   unreachable from a denial.
2. `result` is returned **exactly once**, after the Invariants. Every violation
   path returns `None` above it, so downstream cannot act on rejected output —
   not because the caller is trusted to check, but because it never receives it.

**PN-02, INV-05 and INV-06 are new in Phase 5 and are not Phase 0 escalation
rules**, because Phase 0 had no conversational interface to govern. They are
flagged as such at their definitions so they can be rejected on review rather
than absorbed silently.

**There is no PostNode.** The stage after Gemini is an ordinary
`vsl_core.constructs.Invariant`, compiled by the same `vsl-langgraph` adapter as
every other Invariant here, applied to the model's output before that output is
used. A test asserts that every construct in the active Specification is a real
`PreNode`, `Invariant` or `TerminalState`.

### What is NOT governed, and why

Updating in-memory conversation state, formatting the reply, computing which
fields are missing, and rendering the summary are deterministic and reversible.
They get no VSL gate. Governance invented for demonstration is worse than none:
it dilutes what a gate means and fills the ledger with noise.

The assistant's replies are **assembled, not generated** — from the catalogue's
questions and the validators' own sentences. That is a governance decision as
much as a design one: a generated reply would be model output reaching a
customer, needing its own commitment point and its own Invariant pass on every
turn, to convey information that was already decided.

### INV-02 has not moved

Phase 5 governs a model call. It has **nothing** to do with whether a claim may
be handled automatically — that is still INV-02, still at the automated-action
commitment point (CP-14), still evaluated on the claim's own value:

```
NZD 42,000, lodged conversationally
  business routing          HUMAN_REVIEW_REQUIRED
  CP-14 vsl action          action_denied
  automated_action_allowed  False
  invariant                 automated-authority-limit
  observed / threshold      42,000 / 20,000
  side effect performed     False
  claim state               Human Review
```

A test asserts that `conversation/`, `graph/conversation_graph.py` and the
assistant service cannot even reach `AUTOMATED_AUTHORITY_LIMIT_NZD` or
`govern_automated_route`. The separation is a fact about the import graph, not a
promise in a docstring.

### Human review

Unchanged, and reachable from here. The assistant collects and prepares; it does
not approve, decline or settle. Every conversation view carries the sentence the
customer actually sees:

> This assistant collects the information needed to report a claim. It does not
> approve, decline or settle a claim — a claims specialist decides that.

Human review is a deliberate insurance control, and the assistant never presents
it as an error.

### VerbaLedger

The application writes these entries. **Nothing intercepts anything.** Each
governed turn writes, in causal order with `caused_by` set on every entry:

```
MONITOR ──► PRE_NODE ──► VERIFICATION                      (permitted)
MONITOR ──► PRE_NODE ──► VERIFICATION (SUFFICIENT)         (PreNode denied — governance worked)
MONITOR ──► PRE_NODE ──► VERIFICATION (INSUFFICIENT) ──┬─► TERMINAL
                                                       └─► SPECIFICATION_UPDATE
                                                            (output rejected — an incident)
```

Recorded with each: the conversation id, the specification, the gate, the
observed confidence, the derived threshold, the denial key, the Invariant and
the fallback. **No secret is ever written**, and a test asserts it.

### Six authorities, kept apart

```
AI intelligence        ≠  reads a sentence and proposes values
LangGraph              ≠  orchestrates the turn
Business rules         ≠  validates values, decides eligibility and routing
VSL governance         ≠  enforces at defined commitment points
Human decision         ≠  decides the claim
Audit ledger           ≠  records what happened
```

None of these is a substitute for another. The model does not validate; the
validators do not decide the claim; governance does not route; routing does not
govern; and the ledger records rather than intercepts.

### The customer sees none of this

No VSL, PreNode, Invariant, Gamma, TerminalState, VerbaLedger, commitment point,
LangGraph or agent name appears in the customer interface. The turn response
carries a `governance` object for the claims console; the customer component
never reads it, and a test asserts the rendered page contains none of those
terms.

---

## Documentation

The root README is the project overview. These cover detail it deliberately does not:

| Document | Covers |
| --- | --- |
| [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) | All phases, FRs, per-phase implementation records, assumptions and open questions |
| [`docs/CLAIM_JOURNEY.md`](docs/CLAIM_JOURNEY.md) | The business journey, six claim states, the transition matrix |
| [`docs/DECISION_TABLE.md`](docs/DECISION_TABLE.md) | Thresholds, the 17-row decision table, recommendation vs action |
| [`docs/ROUTING_MODEL.md`](docs/ROUTING_MODEL.md) | The escalation rule catalogue, precedence, the Phase 4 gate mapping |
| [`docs/COMMITMENT_POINTS.md`](docs/COMMITMENT_POINTS.md) | CP-01…CP-15 — what commits, and where each gate goes |
| [`docs/GOVERNANCE_POLICY_CATALOGUE.md`](docs/GOVERNANCE_POLICY_CATALOGUE.md) | The declared governance policy, now executable |
| [`docs/GOVERNANCE_ENFORCEMENT.md`](docs/GOVERNANCE_ENFORCEMENT.md) | How governance actually runs — enforcement, ledger, `caused_by`, audit semantics, limitations |
| [`docs/HUMAN_ESCALATION_POLICY.md`](docs/HUMAN_ESCALATION_POLICY.md) | Escalation triggers, emergency and vulnerable-customer pathways |
| [`docs/SYNTHETIC_DATA_SPEC.md`](docs/SYNTHETIC_DATA_SPEC.md) | The datasets — fields, relationships, examples |
| [`docs/API.md`](docs/API.md) | Endpoints, requests, responses, validation, examples |

**No number in this documentation is an insurer-approved threshold.** Every proposed value is
tagged `[POC-PROPOSED]` and listed in `docs/DECISION_TABLE.md` §7 for approval.

## Ground rules

- **Synthetic data only.** No real customer, policy or claim data, at any phase.
- **Agents recommend; they never act.** Every result is marked recommendation-only, structurally.
- **The LLM is never the business authority.** It writes explanatory prose; every value a decision
  turns on is rule-derived.
- **Routing is rule-derived, not model-derived**, and every reason names the rule, the observation
  and the threshold.
- **Risk indicators are prompts to review** — never accusations, never customer-visible.
- **The gate holds the side effect, not a flag.** A denied action is unreachable, not skipped.
- **Governance can only be more conservative.** A gate can deny; it can never grant.
- **A PreNode denial is governance working.** Only Invariant violations write INSUFFICIENT.
- **Assurance is derived, never asserted** — and it is LOW.
- **Denials are never silent.** A denial visibly routes or stops the workflow.
- **Everything fails closed.** A crashed agent, a missing dataset or a raising rule escalates to a
  person. If governance itself fails, the action does not happen — a governance-system failure is
  never permission to act.
- **An open terminal state stays an audit failure** until a named person lifts it with evidence.
  Nothing times out, retries or recovers on its own.
