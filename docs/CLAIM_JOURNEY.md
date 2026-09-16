# Claim Journey & Claim State Model

**Phase 0 — Business & Governance Foundation.**
This is a **business workflow definition**. It is not implemented in LangGraph and must not be
until Phase 1+ is approved.

Sources: `AI_Insurance_Claims_Agent_Technical_Assessment.docx` (claim states, journey, phases)
and *X-Verba — VSL Governance Spec for Agent Builds* v1.0 (where governance sits).
Values not present in either are marked **[POC-PROPOSED]** and listed in
`PROJECT_PLAN.md` §21.

---

## 1. Target claim type

| Attribute | Value |
| --- | --- |
| Insurance type | **Home Insurance** |
| Claim scenario | **Storm Damage** |
| Trigger event | Severe weather damaging an insured residential property |
| Journey covered | First Notice of Loss (FNOL) through to governed routing |
| Jurisdiction assumed | New Zealand; currency NZD **[POC-PROPOSED]** |

### In scope for this POC

- A single named peril: storm damage to an insured home.
- One claim per customer interaction, lodged by the policyholder themselves.
- Damage to the dwelling and its immediate structures (roof, cladding, windows, fences,
  outbuildings) and to contents damaged as a consequence of that storm damage. **[POC-PROPOSED —
  the assessment says "Home Insurance / Storm Damage" without defining the damage boundary.]**
- Information collection, policy retrieval, validation, assessment, risk check and governed
  routing to either an automated path or human review.

### Out of scope for this POC

- Any other peril: fire, flood-only, earthquake, burglary, accidental damage, liability-only.
- Any other product: motor, contents-only, commercial, travel, life.
- Claims lodged by third parties, brokers or on behalf of another person.
- **Settlement, payment or reserve setting** — excluded by the assessment; a future governance
  decision point only.
- Repairer allocation, supplier dispatch, temporary accommodation booking.
- Claim withdrawal, dispute, complaint and recovery/subrogation workflows.
- Real customer, policy or claim data at any point.

---

## 2. End-to-end claim journey

```
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 1 — Customer reports storm damage                       state: Draft   │
  │  Customer lands on the portal, chooses "Start New Claim".                     │
  │  Intake Agent opens a conversational FNOL.                                    │
  └───────────────────────────────┬──────────────────────────────────────────────┘
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 2 — FNOL information collected                          state: Draft   │
  │  Policy number, date/time of loss, address, what happened, what is damaged,   │
  │  whether the home is habitable, whether anyone is hurt, whether the damage    │
  │  is ongoing, photos/documents. Structured panel fills in as they talk.        │
  │  ⚠ Emergency / vulnerability signals are screened continuously from here on.  │
  └───────────────────────────────┬──────────────────────────────────────────────┘
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 3 — Claim submitted                                 state: Submitted   │
  │  Claim reference issued. Claim record written. Acknowledgement sent.          │
  │  ▣ Governed: claim-state write + claim reference + outbound communication.    │
  └───────────────────────────────┬──────────────────────────────────────────────┘
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 4 — Policy information retrieved                    state: Submitted   │
  │  Policy Agent retrieves the policy record and the relevant Home/Storm policy  │
  │  wording: cover, conditions, excess, exclusions, sums insured, in-force dates.│
  │  ▣ Governed: policy must have been in force at the date of loss (Invariant).  │
  └───────────────────────────────┬──────────────────────────────────────────────┘
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 5 — Information validated                           state: Submitted   │
  │  Validation Agent checks completeness, internal consistency and consistency   │
  │  against the policy record.                                                   │
  └──────────────┬──────────────────────────────────────────┬────────────────────┘
      incomplete │                                          │ complete
                 ▼                                          ▼
  ┌────────────────────────────────────┐   ┌───────────────────────────────────────┐
  │ STEP 5a — Information Required      │   │  STEP 6 — Damage assessed             │
  │ state: Information Required          │   │  state: Assessment                    │
  │ Specific missing items requested     │   │  Assessment Agent classifies the      │
  │ from the customer. Claim waits.      │   │  claim, estimates complexity,         │
  │ Returns to Submitted when supplied.  │   │  urgency and confidence, and          │
  │ ▣ Governed: state write + outbound   │   │  produces a claim summary.            │
  │   customer message.                  │   └──────────────┬────────────────────────┘
  └────────────────────────────────────┘                    ▼
                                          ┌───────────────────────────────────────┐
                                          │  STEP 7 — Risk / complexity evaluated │
                                          │  state: Assessment                     │
                                          │  Fraud & Risk Agent produces a risk    │
                                          │  level and indicators. Indicators are  │
                                          │  for investigation, never accusation.  │
                                          └──────────────┬─────────────────────────┘
                                                         ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 8 — Governance checks                              state: Assessment   │
  │  ▣ The single governed gate before the routing commitment:                    │
  │    (a) MONITOR entry written for every claim, drift-flagged or not            │
  │    (b) PreNodes — is automation confident enough?                             │
  │    (c) Invariants — is automation ever acceptable here?                       │
  │  Only after all gates pass may the routing side effect fire.                  │
  └───────┬──────────────────────────┬──────────────────────────┬────────────────┘
          │ all pass                 │ PreNode denial           │ Invariant violation
          ▼                          ▼                          ▼
  ┌──────────────────┐   ┌──────────────────────┐   ┌────────────────────────────┐
  │ STEP 9a          │   │ STEP 9b              │   │ STEP 9c                     │
  │ AUTOMATED ROUTE  │   │ HUMAN REVIEW         │   │ TERMINAL STATE              │
  │ state:           │   │ state: Human Review  │   │ state: Human Review         │
  │  Assessment →    │   │ Queued with the      │   │ + internal status            │
  │  Approved/       │   │ escalation reason,   │   │   automation_suspended       │
  │  Completed       │   │ AI summary and risk  │   │ No automated way out.        │
  │ Communication    │   │ indicators.          │   │ A human must re-enable —     │
  │ Agent sends the  │   │ Fallback, not        │   │ recorded as a HUMAN_          │
  │ outcome message. │   │ failure.             │   │ AUTHORISED_TRANSITION.       │
  └────────┬─────────┘   └──────────┬───────────┘   └─────────────┬───────────────┘
           │                        │ human decides              │ human re-enables
           │                        ▼                            ▼
           │              ┌──────────────────────────────────────────────────┐
           │              │  Human outcome: progress, request more info,      │
           │              │  refer to specialist, or complete the claim.      │
           │              └───────────────────────┬──────────────────────────┘
           ▼                                      ▼
  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  STEP 10 — Claim progresses toward Approved/Completed                         │
  │  state: Approved/Completed. POC ends here — settlement is out of scope.       │
  └──────────────────────────────────────────────────────────────────────────────┘
```

### Parallel pathway — emergency / vulnerable customer

Screened continuously from Step 2 onward. When triggered, the claim leaves the standard
sequence immediately and is placed in the priority human queue; it does **not** wait for
assessment or the governance gate to complete. See `HUMAN_ESCALATION_POLICY.md` §4.

---

## 3. Official claim states

These six are the **official business claim states**, taken directly from the requirements
document. No additional official states have been invented.

### 3.1 Draft

| | |
| --- | --- |
| **Meaning** | A claim is being assembled in conversation. It does not yet exist as a lodged claim. |
| **Entered when** | The customer starts a new claim and the Intake Agent opens the FNOL conversation. |
| **What can happen** | Information is collected and revised; the customer can abandon; the customer can request a human at any time. |
| **Exits to** | Submitted (customer confirms lodgement) · Human Review (emergency/vulnerable pathway, or the customer asks for a human) · abandoned (no state change; the draft simply expires) |
| **Human involvement** | Optional — the customer may request it. |
| **Automatable** | Yes. Conversational collection is the core automation of this POC. |
| **Governance before transition** | Yes, on exit: issuing a claim reference and writing the claim record is a commitment (CP-02). |

### 3.2 Submitted

| | |
| --- | --- |
| **Meaning** | The claim is formally lodged. A claim reference exists. The insurer now owns a duty to respond. |
| **Entered when** | The customer confirms lodgement from Draft, **or** a claim in Information Required receives the outstanding information. |
| **What can happen** | Policy retrieval; validation; acknowledgement to the customer. |
| **Exits to** | Information Required (validation finds gaps) · Assessment (validation passes) · Human Review (policy-basis Invariant fails, emergency, or customer request) |
| **Human involvement** | Not required on the happy path. |
| **Automatable** | Yes — retrieval and validation. |
| **Governance before transition** | Yes: state write (CP-09), acknowledgement message (CP-10), policy-in-force Invariant (CP-03). |

### 3.3 Information Required

| | |
| --- | --- |
| **Meaning** | The claim cannot progress until the customer supplies specific missing or clarifying information. |
| **Entered when** | Validation identifies missing mandatory fields, missing required documents, or an internal inconsistency the customer must resolve. |
| **What can happen** | A specific, itemised request goes to the customer; the customer responds; a reminder may be issued. |
| **Exits to** | Submitted (information supplied — revalidated) · Human Review (repeated non-response, conflicting information that the customer cannot resolve, or an escalation trigger) |
| **Human involvement** | Not required initially; required if the loop does not resolve. |
| **Automatable** | Yes — detection and the itemised request. |
| **Governance before transition** | Yes: state write (CP-09) and the outbound request to the customer (CP-10). |
| **Note** | Entering this state is a **fallback within the workflow**, not a PreNode denial. Missing information is a deterministic, checkable fact — see `GOVERNANCE_POLICY_CATALOGUE.md` §6. |

### 3.4 Assessment

| | |
| --- | --- |
| **Meaning** | A complete claim is being classified, triaged and risk-checked. This is where the AI's judgement is formed and where the governance gate sits. |
| **Entered when** | Validation passes on a Submitted claim. |
| **What can happen** | Classification; complexity, urgency and confidence estimation; risk indicator detection; claim summary generation; the governance gate. |
| **Exits to** | Approved/Completed (automated route, gates passed) · Human Review (PreNode denial, Invariant violation, high value, high risk, or policy uncertainty) · Information Required (assessment surfaces a gap validation missed) |
| **Human involvement** | Not required on the automated route; required on every escalation path. |
| **Automatable** | The assessment itself, yes. **The routing decision out of this state is the POC's principal governed commitment** (CP-11). |
| **Governance before transition** | **Yes — mandatory.** All PreNodes and Invariants run here, before the routing side effect. |

### 3.5 Human Review

| | |
| --- | --- |
| **Meaning** | A real workflow state in which a claims employee owns the claim. Required by both source documents: the UI must render it as a genuine review state, never swallow it. |
| **Entered when** | A PreNode denies automation (fallback), an Invariant is violated (with automation suspended), an escalation rule fires, the emergency/vulnerable pathway triggers, or the customer asks for a human. |
| **What can happen** | The employee reads the AI summary, escalation reason, risk indicators and governance trace, then decides. |
| **Exits to** | Approved/Completed (employee progresses the claim) · Information Required (employee requests more) · remains in Human Review (referred to a specialist) |
| **Human involvement** | **Required, by definition.** |
| **Automatable** | No. Exit from this state is always a human decision in this POC. |
| **Governance before transition** | Yes for any resulting system action (state write, outbound message). Where automation was suspended by a TerminalState, resuming requires a **HUMAN_AUTHORISED_TRANSITION** ledger entry — audit check 5 (CP-17). |

### 3.6 Approved/Completed

| | |
| --- | --- |
| **Meaning** | The POC journey is finished: the claim has been accepted for progression and the customer told what happens next. **This is not settlement** — settlement is out of scope. |
| **Entered when** | The automated route completes all governance gates, or a claims employee completes their review. |
| **What can happen** | Final outcome communication; the claim record closes for POC purposes. |
| **Exits to** | Terminal for the POC. |
| **Human involvement** | Only if reached via Human Review. |
| **Automatable** | Yes, via the governed automated route. |
| **Governance before transition** | Yes: final state write (CP-09) and the outcome communication to the customer (CP-10). |

---

## 4. Internal workflow statuses

These are **not** official business claim states. They are internal flags carried alongside the
official state so that the workflow, the governance dashboard and the review queue can describe
what is happening without inventing new business states. **[POC-PROPOSED — the assessment
permits internal statuses provided they are clearly distinguished from official states.]**

| Internal status | Sits alongside | Meaning |
| --- | --- | --- |
| `intake_in_progress` | Draft | Conversation open, FNOL incomplete |
| `awaiting_customer_response` | Information Required | Request issued, nothing back yet |
| `policy_retrieved` | Submitted | Policy context attached to the claim |
| `validated` | Submitted | Completeness and consistency checks passed |
| `assessment_complete` | Assessment | Classification, triage and risk output available |
| `governance_passed` | Assessment | All gates cleared; automated route authorised |
| `governance_denied_prenode` | Human Review | PreNode denial — normal fallback, governance working |
| `automation_suspended` | Human Review | Invariant violated; TerminalState entered; human re-enablement required |
| `emergency_priority` | any | Emergency pathway active |
| `vulnerable_customer_support` | any | Vulnerable-customer pathway active |
| `specialist_referral` | Human Review | Referred to fraud/risk or technical specialist |

`governance_denied_prenode` and `automation_suspended` must remain distinguishable everywhere —
in the ledger, the dashboard and the queue. They are different outcomes with different exits.

---

## 5. Transition matrix

| From | To | Trigger | Automatable? | Governance before? |
| --- | --- | --- | --- | --- |
| — | Draft | Customer starts a claim | Yes | No — no commitment yet |
| Draft | Submitted | Customer confirms lodgement | Yes | **Yes** — CP-02, CP-09, CP-10 |
| Draft | Human Review | Emergency/vulnerable trigger, or customer requests a human | Yes (the routing) | **Yes** — CP-12 |
| Submitted | Information Required | Validation finds gaps | Yes | **Yes** — CP-09, CP-10 |
| Submitted | Assessment | Validation passes | Yes | **Yes** — CP-09 |
| Submitted | Human Review | Policy-in-force Invariant violated | No — hard stop | **Yes** — Invariant, TerminalState |
| Information Required | Submitted | Customer supplies the information | Yes | **Yes** — CP-09 |
| Information Required | Human Review | Loop unresolved, or escalation trigger | Yes (the routing) | **Yes** — CP-12 |
| Assessment | Approved/Completed | Automated route; all gates pass | Yes | **Yes** — the principal gate, CP-11 |
| Assessment | Human Review | PreNode denial, Invariant violation, or escalation rule | Yes (the routing) | **Yes** — CP-12 |
| Assessment | Information Required | Gap surfaced during assessment | Yes | **Yes** — CP-09, CP-10 |
| Human Review | Approved/Completed | Employee decision | **No** — human only | Yes for the resulting writes |
| Human Review | Information Required | Employee requests more information | **No** — human only | Yes for the resulting writes |
| Human Review (suspended) | any | Human re-enables automation | **No** — human only | **Yes** — HUMAN_AUTHORISED_TRANSITION, CP-17 |

Every transition that changes the claim record or reaches the customer is preceded by a
governance gate. No transition is performed before its gate returns.

---

## 6. Which transitions may eventually be automated

**Automatable in this POC:** Draft → Submitted; Submitted → Information Required; Submitted →
Assessment; Information Required → Submitted; Assessment → Approved/Completed (governed);
Assessment → Human Review; routing into the emergency/vulnerable pathway.

**Never automated in this POC:** every exit from Human Review; re-enablement after a
TerminalState; anything involving settlement, payment or reserve.

**Deliberately not automated yet, though technically possible:** closing a claim without any
human ever seeing it where value or risk is material — the value ceiling for hands-off
automation is the automated authority limit in `DECISION_TABLE.md` §2.4.

---

## 7. Related documents

- `DECISION_TABLE.md` — thresholds, the decision table, recommendation vs action
- `COMMITMENT_POINTS.md` — the CP-xx catalogue referenced throughout this document
- `HUMAN_ESCALATION_POLICY.md` — escalation rules and the emergency/vulnerable pathway
- `GOVERNANCE_POLICY_CATALOGUE.md` — PreNodes, Invariants, TerminalState, ledger and audit
- `SYNTHETIC_DATA_SPEC.md` — the datasets that drive this journey
- `PROJECT_PLAN.md` — the hub document
