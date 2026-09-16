# Human Escalation Policy

**Phase 0 — Business & Governance Foundation.**

The objective of this POC is **not** a fully autonomous system. It is controlled automation with
appropriate human oversight. This document defines when the AI must stop automated processing
and hand the claim to a person.

Two principles govern everything below, both taken from the source documents:

1. **A governance denial must not silently disappear.** The workflow must visibly route or stop.
2. **Human Review is a real workflow state**, rendered as a genuine review state in the UI —
   never swallowed, never shown to the customer as an error.

---

## 1. The three ways a claim reaches a human

| Route | Cause | Governance outcome | Exit |
| --- | --- | --- | --- |
| **Fallback** | A PreNode denies automation | Governance **working**. Verification = **SUFFICIENT** | Employee decides; automation is not suspended |
| **Escalation rule** | A deterministic business condition (value, complexity, risk, conflict, customer request) | No PreNode involved; the routing write is still gated | Employee decides |
| **Suspension** | An Invariant is violated | Governance **failed** for that action. Verification = **INSUFFICIENT**, TERMINAL entry written | **Only** a HUMAN_AUTHORISED_TRANSITION re-enables automation |

These three must remain visually and structurally distinct in the queue, the dashboard and the
ledger. Collapsing them into "escalated" destroys the thing the POC is meant to demonstrate.

---

## 2. Escalation triggers

Each trigger names the decision-table row that implements it and the reason string the employee
sees in UI-04.

| # | Trigger | Condition **[POC-PROPOSED values]** | Row | Mechanism | Queue reason |
| --- | --- | --- | --- | --- | --- |
| E-01 | **Low confidence** | Gamma < 1.1 at `DECISION_THRESHOLD = 0.80` (effective `p < 0.815`) | D-05 | **PreNode denial → fallback** | "Confidence below automation threshold" |
| E-02 | **High complexity** | Any high-complexity indicator present | D-06 | Escalation rule | "High complexity — {indicator}" |
| E-03 | **High-value claim** | Estimated value > NZD 10,000 | D-07 | Escalation rule | "High-value claim — NZD {value}" |
| E-04 | **Above automated authority** | Estimated value > NZD 20,000 with automation proposed | D-08 | **Invariant → TerminalState → suspension** | "Automated authority limit exceeded" |
| E-05 | **No cover basis** | Policy not in force at date of loss | D-03 | **Invariant → TerminalState → suspension** | "Policy not in force at date of loss" |
| E-06 | **Policy uncertainty** | An exclusion may be engaged, or cover is ambiguous | D-09 | **Invariant** (no auto-approval under exclusion) | "Policy exception — {exclusion code}" |
| E-07 | **Conflicting information** | Internal inconsistency the customer cannot resolve; or claim data contradicts the policy record | D-12 | Escalation rule | "Conflicting information — {detail}" |
| E-08 | **Missing information, unresolved** | Information Required loop unresolved after 2 requests, or no response in 10 days | D-01 → escalation | Escalation rule | "Outstanding information not supplied" |
| E-09 | **Risk indicators — medium** | One risk indicator triggered | D-10 | Escalation rule | "Risk indicator flagged for review" |
| E-10 | **Risk indicators — high** | Two or more, or one severe | D-11 | Escalation rule → specialist | "Specialist review — multiple risk indicators" |
| E-11 | **Emergency** | See §4.1 | D-13 | Priority pathway, evaluated first | "EMERGENCY — {signal}" |
| E-12 | **Vulnerable customer** | See §4.2 | D-14 | Supported pathway | "Vulnerable customer support" |
| E-13 | **Customer request** | Customer asks for a human at any point | D-15 | Escalation rule | "Customer requested a person" |
| E-14 | **Suspended claim** | Claim already in a TerminalState | D-16 | Gate returns `suspended` first | "Automation suspended — awaiting re-enablement" |
| E-15 | **Repeated automation denial** | The same claim denied twice by the same PreNode | — | Escalation rule **[POC-PROPOSED]** | "Repeated automation denial — manual assessment" |
| E-16 | **Governance or system error** | Gate or agent fails unexpectedly | — | Fail closed → human | "System could not complete automated assessment" |

**E-16 is the catch-all and it fails closed.** An unhandled error routes to a human; it never
falls through to the automated path. The guidance warns that `AutomationDeniedException` can be
swallowed by a bare `except Exception` and should be grepped for in CI — the same discipline
applies to every error path here.

### 2.1 Non-triggers

For clarity, these do **not** by themselves escalate: a customer being upset; a long or rambling
conversation; a claim near but under a value threshold; a single prior claim in history; a
document uploaded in an unusual format. Escalation is for genuine business reasons, not for
conversational friction.

---

## 3. What the employee receives

Every escalated claim arrives with (FR-08, FR-09, FR-11, UI-04):

- Claim ID and current official state.
- **Escalation reason**, in business language, naming the specific trigger.
- Which of the three routes brought it here — fallback, escalation rule, or suspension.
- AI-generated case summary (R-11).
- Risk indicators, if any — **employee-visible only**.
- Policy context with citations to the retrieved wording.
- Missing items and validation issues.
- Confidence, complexity, urgency and estimated value, with the thresholds they were measured
  against, so the employee can see *why* the number mattered.
- The governance trace: decision ID, which gates ran, which passed, which denied, and the
  ledger entries — FR-11, FR-12.
- Where automation is suspended: the terminal state name and what re-enablement requires.

The requirement is explainability: the employee should never have to ask "why is this here?"

---

## 4. Emergency and vulnerable-customer pathway

This pathway is **separate from the standard escalation flow**. It is evaluated first, it
bypasses the remaining assessment sequence, and it is never gated behind a confidence
calculation — a person in an unsafe home does not wait for a Gamma estimate.

### 4.1 Emergency

**Signals [POC-PROPOSED]** — any one triggers the pathway:

- The home is uninhabitable, or the customer says they cannot stay there.
- Anyone is injured.
- Damage is ongoing or the property is unsafe — structural damage, water entering, unsecured
  roof, live electrical hazard.
- Utilities are out: no power, water, heating or sanitation.
- The customer needs emergency accommodation tonight.
- The customer uses explicit distress language about their immediate safety.

**Behaviour:**

1. The claim is placed in the **priority human queue immediately**, from whatever state it is
   in — including mid-FNOL in Draft, before submission is complete.
2. Internal status `emergency_priority`. The official claim state is unchanged by the routing
   itself.
3. The customer is shown make-safe and emergency guidance immediately, and is told a person is
   being brought in. **[POC-PROPOSED — content must come from the insurer; the AI must not
   improvise safety advice.]**
4. The rest of the automated assessment continues in the background only to prepare the case
   summary. It never routes the claim.
5. **The automated route is unavailable for the remainder of this claim.** An emergency claim is
   never closed by automation in this POC.
6. Emergency detection is deliberately **over-inclusive**. A false positive costs a phone call;
   a false negative is a safety failure.

### 4.2 Vulnerable customer

**Signals [POC-PROPOSED]:**

- `vulnerability_flag` already set on the customer record.
- An accessibility need is recorded that affects how the claim must be handled.
- The customer discloses a circumstance during the conversation that makes self-service
  unreasonable — for example difficulty understanding the process, bereavement, or needing
  someone to act on their behalf.
- The customer asks for support, an advocate, or a different channel.
- Repeated inability to complete the FNOL despite clear prompts.

**Behaviour:**

1. Internal status `vulnerable_customer_support`; routed to Human Review with that reason.
2. Communication switches to the customer's recorded preferred channel and honours accessibility
   needs. No automated chase-up messages.
3. **The automated route is unavailable** for the remainder of the claim.
4. The AI does not diagnose, label or speculate about the customer's circumstances. It records
   an operational signal — "customer asked for support", "accessibility need on file" — and
   hands over. Sensitive personal circumstances are not stored in the claim record.
5. Vulnerability is **never** used as a risk or fraud indicator. These two pathways must not be
   allowed to touch.

### 4.3 Both together

If both trigger, emergency takes precedence for routing speed and the vulnerability status
travels with the claim, so the employee gets both flags.

---

## 5. Escalation precedence

The first match wins, exactly as in `DECISION_TABLE.md` §4.1:

```
E-14 suspension  →  E-11 emergency  →  E-04/E-05/E-06 Invariants  →  E-12 vulnerable
   →  E-10/E-09 risk  →  E-02/E-03 complexity & value  →  E-07/E-08 information
   →  E-01 confidence PreNode  →  E-13 customer request  →  automated route
```

The automated route is the last branch reached, never a default. A claim qualifies for it only
by surviving every check above.

---

## 6. What humans control that automation never does

- Every exit from Human Review.
- Re-enabling automation after a suspension (CP-17).
- Any decision on a claim above the automated authority limit.
- Any decision where a policy exclusion may apply.
- Any emergency or vulnerable-customer claim.
- Any decision to treat risk indicators as anything more than a prompt to investigate.

---

## 7. Open questions

| # | Item | Status |
| --- | --- | --- |
| 1 | Definition of "vulnerable customer" for this insurer | **Open** — must come from the insurer's own policy, not be invented here |
| 2 | Emergency guidance content shown to customers | **Open** — safety-critical wording must be supplied, not generated |
| 3 | E-08 timings: 2 requests, 10 days | **[POC-PROPOSED]** |
| 4 | E-15 repeated-denial rule | **[POC-PROPOSED]** — not in either source document |
| 5 | Whether emergency claims should page a person in real time, or queue with priority | **Open** — the POC assumes a priority queue; a real deployment may need paging |
| 6 | Who may re-enable a suspended claim — any claims employee, or a manager/authority holder | **Open** — the guidance requires a human authorised transition but does not define authority levels |
| 7 | Queue SLAs per escalation reason | **Open** |
| 8 | What vulnerability information may lawfully be recorded, and who may see it | **Open** — a privacy and compliance question for the insurer |
