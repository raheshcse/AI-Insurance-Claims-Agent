# Business Thresholds, Decision Table & Recommendation vs Action

**Phase 0 — Business & Governance Foundation.**

> **Every numeric value in this document is a POC proposal, not an official insurance
> threshold.** Neither the requirements document nor the X-Verba/VSL guidance supplies numbers.
> Each is tagged **[POC-PROPOSED]** and every one is listed in §7 as requiring business approval
> before implementation. They exist so that Phase 1+ has something concrete and explicit to
> implement and argue with — not because they are authoritative.

---

## 1. Threshold design principles

1. **Thresholds are policy, not model internals.** Following the VSL guidance, the decision
   boundary lives in `governance/policy.py` and is read from the environment — never hard-coded
   into an agent or a prompt.
2. **A threshold is only useful if it changes a route.** Every threshold below maps to a
   specific branch in the decision table (§4).
3. **Graded vs binary matters.** Graded confidence belongs to a PreNode. Binary business facts
   belong to an Invariant or to deterministic workflow logic. See
   `GOVERNANCE_POLICY_CATALOGUE.md` §6.
4. **When in doubt, escalate.** An unresolvable or unmeasurable condition routes to human
   review; it never defaults to automation.

---

## 2. The threshold framework

### 2.1 Complexity

Complexity is a **derived band**, not a raw score. It is computed from the factors below and
used to decide whether the claim is a candidate for the automated route at all.

| Factor | Low-complexity indicator | High-complexity indicator |
| --- | --- | --- |
| Damage scope | One damaged element (e.g. roof tiles, a fence) | Three or more damaged elements, or whole-of-dwelling damage |
| Structural impact | Cosmetic or non-structural | Structural damage; home uninhabitable |
| Estimated value | ≤ NZD 5,000 **[POC-PROPOSED]** | > NZD 20,000 **[POC-PROPOSED]** |
| Cover clarity | Peril plainly covered; no exclusion engaged | Exclusion possibly engaged; cover ambiguous; policy wording needs interpretation |
| Parties | Policyholder only | Third-party damage, liability, shared/body-corporate property, multiple policies |
| Contents involvement | None, or a small number of clearly listed items | Specified/high-value items; large contents schedules |
| Information quality | Complete and internally consistent | Conflicting accounts, dates or amounts |
| Additional needs | None | Temporary accommodation; emergency make-safe; injury reported |

| Band | Rule **[POC-PROPOSED]** | Consequence |
| --- | --- | --- |
| **Low** | No high-complexity indicator present **and** estimated value ≤ NZD 5,000 | Eligible for the automated route, subject to confidence, risk and Invariants |
| **Medium** | Neither Low nor High | Eligible for the automated route **only** if confidence is above threshold and risk is Low; otherwise human review |
| **High** | Any one high-complexity indicator present | Human review. Automation is never the route for a High-complexity claim in this POC |

### 2.2 Confidence

Confidence follows the VSL guidance exactly and is **not** a plain percentage cut-off. Two
separate numbers are involved and they must not be confused:

| Number | What it is | Value |
| --- | --- | --- |
| `DECISION_THRESHOLD` | **Business policy.** The probability boundary at which the business considers the automated route warranted. Lives in `governance/policy.py`, read from env. | **0.80** **[POC-PROPOSED]** |
| `ROBUST_GAMMA_DEFAULT_THRESHOLD` | **Library constant.** The Gamma threshold a PreNode must clear. Shipped by VSL-Core. | **1.1** — not ours to change |

The PreNode monitor converts a model confidence `p` into a Gamma estimate as the odds of the
prediction **relative to the odds at the decision boundary** — the guidance is explicit that
dividing by a hard-coded 0.5 instead of the real boundary silently kills the feature:

```
gamma = (p / (1 - p)) / (t / (1 - t))        where t = DECISION_THRESHOLD
```

With `t = 0.80`, a PreNode passes when `gamma ≥ 1.1`, i.e.:

```
p / (1 - p) ≥ 1.1 × 4.0 = 4.4     →     p ≥ 0.8148
```

| Model confidence `p` | Gamma at `t = 0.80` | PreNode outcome |
| --- | --- | --- |
| 0.95 | 4.75 | Pass |
| 0.90 | 2.25 | Pass |
| 0.85 | 1.42 | Pass |
| 0.8148 | 1.10 | Pass — exactly at the boundary |
| 0.81 | 1.07 | **Deny → human review** |
| 0.70 | 0.58 | **Deny → human review** |
| 0.50 | 0.25 | **Deny → human review** |

So the effective automation confidence floor is **≈ 0.815**, which emerges from policy plus the
library constant rather than being asserted. **[POC-PROPOSED: `DECISION_THRESHOLD = 0.80`.]**

`delta_estimation_error` (calibration error) is set to **0.10** **[POC-PROPOSED]** following the
guidance's default. It is a declared statement about how well-calibrated the confidence estimate
is, and should be revisited once there is evidence.

**Honest constraint, per the guidance:** these runtime gates derive assurance **LOW**
(F1 = True, F2 = NONE — output-layer control). That is correct and must be stated, not
disguised. LOW means the gate blocks a bad action; it does not change how the model decides.

### 2.3 Risk

| Band | Rule **[POC-PROPOSED]** | Consequence |
| --- | --- | --- |
| **Low** | No risk indicator triggered | No effect on routing |
| **Medium** | One risk indicator triggered | Human review — standard queue, flagged |
| **High** | Two or more indicators, or any single indicator marked *severe* in the risk rules | Human review — specialist referral |

Candidate risk indicators (defined as data, in `data/synthetic/risk_rules`, not in prompts):
claim lodged very soon after policy inception or a recent cover increase; date of loss not
matching a recorded weather event at that location; repeated similar claims in the customer's
history; estimated value inconsistent with the described damage; damage description inconsistent
between conversation turns or with supplied documents; documents dated before the loss.

**Framing rule, from the requirements:** indicators flag a claim for investigation. They never
assert fraud, and no customer-facing message may reference them.

### 2.4 Claim value

| Threshold | Value **[POC-PROPOSED]** | Meaning | Governance type |
| --- | --- | --- | --- |
| Low-value automation band | ≤ NZD 5,000 | Straightforward band; automation candidate | Complexity input |
| High-value review threshold | > NZD 10,000 | Human review required regardless of confidence | Escalation rule (deterministic) |
| **Automated authority limit** | **NZD 20,000** | The automated route must **never** be taken above this. Proceeding anyway is always wrong. | **Invariant → TerminalState** |

The automated authority limit is the rule that Demonstration Scenario C breaches. It is the one
threshold that is deliberately *not* overridable by high confidence.

Where the estimated value is unknown, the claim is treated as **above** the high-value review
threshold. Absence of evidence never buys automation.

### 2.5 Urgency

| Band | Rule **[POC-PROPOSED]** | Consequence |
| --- | --- | --- |
| **Emergency** | Home uninhabitable, injury reported, damage ongoing/unsafe, no power or water, vulnerable customer at risk | Immediate priority human queue; bypasses the standard sequence |
| **High** | Home habitable but weatherproofing compromised; make-safe needed soon | Normal flow, priority flag on the queue |
| **Standard** | Everything else | Normal flow |

### 2.6 Completeness

Binary and deterministic, not a confidence judgement. A claim is complete when every mandatory
FNOL field is present, every required document for the claim type is attached, and no internal
inconsistency is outstanding. Incomplete → **Information Required** (a workflow fallback, not a
PreNode denial).

---

## 3. Recommendation vs action

The distinction matters because **governance gates sit before actions**, and a recommendation
becomes an action the moment something downstream commits to it.

### 3.1 AI recommendations — outputs that state a view

| # | Recommendation | Produced by | Consequential only when… |
| --- | --- | --- | --- |
| R-01 | Extracted structured claim information | Intake Agent | It is written to the claim record |
| R-02 | Relevant policy context and cover interpretation | Policy Agent | Validation or assessment relies on it |
| R-03 | Completeness / consistency result and missing-item list | Validation Agent | It drives a state change or a customer request |
| R-04 | Claim classification (type, incident category) | Assessment Agent | It is used to route |
| R-05 | Complexity band | Assessment Agent | It is used to route |
| R-06 | Urgency band | Assessment Agent | It changes the queue |
| R-07 | Confidence score | Assessment Agent | It is fed to the PreNode |
| R-08 | Recommended route (automated / human) | Assessment Agent | The route is actually taken |
| R-09 | Risk level and indicators | Fraud & Risk Agent | They trigger referral |
| R-10 | Estimated claim value | Assessment Agent | It is compared against the authority limit |
| R-11 | Claim summary for the employee console | Assessment Agent | It is shown to a human making a decision |
| R-12 | Draft customer message | Communication Agent | It is sent |

A recommendation on its own changes nothing, can be regenerated, and can be overridden by a
human without consequence.

### 3.2 System actions — things that cannot be taken back

| # | Action | Irreversible because… |
| --- | --- | --- |
| A-01 | Issue a claim reference and write the claim record | The customer is told the reference; the insurer's duty to respond begins |
| A-02 | Change the official claim state | Downstream behaviour, SLAs and customer-visible status all follow from it |
| A-03 | Send any outbound customer communication | It cannot be unsent; it sets expectations the insurer must meet |
| A-04 | Take the automated route (close without human review) | A claim decision is made with no human in the loop |
| A-05 | Place the claim in the human review queue | Consumes human capacity; changes the customer's timeline |
| A-06 | Trigger specialist / fraud referral | Reputationally serious for the customer |
| A-07 | Commit an agent-to-agent handover that advances the workflow | The receiving agent acts on the handed-over state as established fact |
| A-08 | Write a ledger entry | Append-only and hash-chained by design |
| A-09 | Re-enable automation after suspension | Undoes a hard stop; only a human may do it |
| A-10 | *(Future, out of scope)* Initiate settlement or payment | Money moves |

### 3.3 Classification table

| Outcome | Recommendation | Action | Governance before it? |
| --- | --- | --- | --- |
| Recommended claim complexity | ✔ | | Only when routed on (A-04/A-05) |
| Recommended next step | ✔ | | Only when executed |
| Recommended assessment result | ✔ | | Only when routed on |
| Recommended escalation | ✔ | | Only when the claim is actually queued |
| Confidence score | ✔ | | It is the PreNode's input, not a gated act itself |
| Risk indicators | ✔ | | Only when a referral is triggered |
| Draft customer message | ✔ | | Only on send |
| Updating the claim record | | ✔ | **Yes** |
| Changing claim state | | ✔ | **Yes** |
| Sending a customer communication | | ✔ | **Yes** |
| Taking the automated route | | ✔ | **Yes — the principal gate** |
| Queuing for human review | | ✔ | **Yes** |
| Specialist referral | | ✔ | **Yes** |
| Committing agent handover | | ✔ | **Yes** |
| Re-enabling suspended automation | | ✔ | **Yes — human only** |

Rule of thumb used throughout: *if undoing it requires telling the customer something changed,
it is an action.*

---

## 4. The decision table

Read left to right. `Claim condition → AI assessment → Threshold → Rec/Action → Governance →
Automated path → Human path`. This is the reference Phase 1+ implements against.

| ID | Claim condition | AI assessment / recommendation | Threshold applied | Rec or Action | Governance requirement | Automated path | Human escalation path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **D-01** | FNOL in progress, mandatory fields missing | Validation: incomplete + itemised missing list (R-03) | Completeness = binary | Action: state → Information Required (A-02) + request (A-03) | Gate before state write and outbound message (CP-09, CP-10). Not a PreNode — deterministic | — | Only if the loop fails to resolve |
| **D-02** | Information supplied | Validation: complete (R-03) | Completeness = binary | Action: state → Assessment (A-02) | Gate before state write (CP-09) | Proceed to assessment | — |
| **D-03** | Policy not in force at date of loss | Policy Agent: cover basis absent (R-02) | Binary fact | Action: stop automation (A-04 blocked) | **Invariant `policy-in-force`** → TerminalState | **Never** | Human Review, `automation_suspended` |
| **D-04** | Complete, Low complexity, Low risk, value ≤ NZD 5,000, confidence ≥ 0.815 | Classification + triage: automated route (R-04…R-08) | Complexity Low; Gamma ≥ 1.1 at t = 0.80; value ≤ authority limit | Action: automated route (A-04), state → Approved/Completed (A-02), outcome message (A-03) | PreNodes pass → Invariants pass → side effect fires. SUFFICIENT verification written | **Yes — Scenario A** | — |
| **D-05** | Complete, but confidence < 0.815 | Triage with low confidence (R-07, R-08) | Gamma < 1.1 | Action: route to human (A-05) | **PreNode `automation-confidence` denies** → Fallback `ROUTE_TO_HUMAN_QUEUE`. **SUFFICIENT** — governance working, not failing | — | **Human Review — Scenario B**, reason "confidence below automation threshold" |
| **D-06** | Complete, High complexity | Complexity = High (R-05) | Any high-complexity indicator | Action: route to human (A-05) | Deterministic escalation rule, gated before the routing write | — | Human Review, reason "high complexity" |
| **D-07** | Estimated value > NZD 10,000, ≤ NZD 20,000 | Value estimate (R-10) | High-value review threshold | Action: route to human (A-05) | Deterministic escalation rule, gated | — | Human Review, reason "high-value claim" |
| **D-08** | Estimated value > NZD 20,000 **and automation proposed** | Recommended automated route (R-08) | **Automated authority limit** | Action blocked (A-04 refused) | **Invariant `automated-authority-limit`** → TerminalState → suspension. **INSUFFICIENT** verification written | **Never** | **Human Review — Scenario C**, `automation_suspended`, human re-enablement required |
| **D-09** | Exclusion possibly engaged / cover ambiguous | Policy Agent: cover uncertain (R-02) | Binary: exclusion flag present | Action: route to human (A-05); automated approval refused | **Invariant `no-auto-approval-under-exclusion`** → TerminalState | **Never** | Human Review, reason "policy exception" |
| **D-10** | One risk indicator (Medium risk) | Risk level Medium + indicators (R-09) | Risk band Medium | Action: route to human (A-05) | Deterministic escalation rule, gated | — | Human Review, flagged; indicators shown to the employee only |
| **D-11** | Two or more indicators, or a severe indicator | Risk level High (R-09) | Risk band High | Action: specialist referral (A-06) | Deterministic escalation rule, gated | — | **Specialist review — Scenario D**, `specialist_referral` |
| **D-12** | Conflicting information the customer cannot resolve | Validation: inconsistency (R-03) | Binary | Action: route to human (A-05) | Deterministic escalation rule, gated | — | Human Review, reason "conflicting information" |
| **D-13** | Emergency signal (uninhabitable, injury, ongoing damage, no utilities) | Urgency = Emergency (R-06) | Emergency band | Action: priority queue (A-05) immediately | Gated before the routing write; **bypasses the remaining assessment sequence** | — | **Priority human queue**, `emergency_priority` |
| **D-14** | Vulnerable-customer signal | Vulnerability flagged (R-06) | Vulnerability band | Action: supported human pathway (A-05) | Gated before the routing write | — | Human Review, `vulnerable_customer_support` |
| **D-15** | Customer asks for a human at any point | — | None | Action: route to human (A-05) | Gated before the routing write | — | Human Review, reason "customer request" |
| **D-16** | Claim already suspended by a TerminalState | — | — | All automated actions refused | Gate returns `suspended` before any other check | **Never** | Stays in Human Review until a **HUMAN_AUTHORISED_TRANSITION** is recorded |
| **D-17** | Employee completes review | — | — | Action: state → Approved/Completed (A-02) + message (A-03) | Gated before the writes; human decision recorded | — | Human decision |

### 4.1 Precedence

When several rows apply, the first match in this order wins:

1. **D-16** suspension — nothing else runs.
2. **D-13** emergency — safety before process.
3. **D-03 / D-08 / D-09** Invariants — hard stops.
4. **D-14** vulnerable customer.
5. **D-11 / D-10** risk.
6. **D-06 / D-07** complexity and value.
7. **D-05** confidence PreNode.
8. **D-04** automated route — reached only when nothing above applies.

The automated route is deliberately the **last** branch, not the default.

---

## 5. Scenario mapping

| Scenario (requirements §11) | Decision table row | Expected governed outcome |
| --- | --- | --- |
| A — Normal claim | D-04 | PreNodes pass → Invariants pass → automated route proceeds |
| B — Low confidence | D-05 | PreNode denies → fallback → Human Review Queue |
| C — Hard rule | D-08 | Invariant violation → TerminalState → suspension → human re-enablement |
| D — Potential risk | D-10 / D-11 | Risk flagged → governed routing → specialist review |

---

## 6. How Phase 1+ should consume this table

- Thresholds are **configuration**, sourced from `governance/policy.py` via environment
  variables — never literals inside agents, prompts or the graph.
- Deterministic rows (D-01, D-02, D-06, D-07, D-10…D-15) are **workflow logic** evaluated
  before the governance gate; they still pass through a gate before their side effect fires.
- Graded rows (D-04, D-05) are the **PreNode**.
- Hard rows (D-03, D-08, D-09) are **Invariants**.
- Each row's decision must be traceable to a `decision_id` in the ledger.

---

## 7. Values requiring business approval

| Item | Proposed | Why it needs approval |
| --- | --- | --- |
| `DECISION_THRESHOLD` | 0.80 | Sets the effective automation confidence floor (≈ 0.815). Directly controls automation rate |
| Calibration error `delta_estimation_error` | 0.10 | Declares how trustworthy the confidence estimate is |
| Low-value automation band | ≤ NZD 5,000 | Defines "straightforward" |
| High-value review threshold | > NZD 10,000 | Forces human review regardless of confidence |
| **Automated authority limit** | **NZD 20,000** | The hard stop. The single most consequential number here |
| Low-complexity damage-element count | 1 | Scope definition |
| High-complexity damage-element count | ≥ 3 | Scope definition |
| Risk band rules | 1 indicator = Medium; ≥ 2 or severe = High | Sets the false-positive rate |
| Risk indicator list and severities | See §2.3 | Must come from claims/fraud specialists |
| Emergency band definition | See §2.5 | Safety-critical |
| Vulnerability signals | See `HUMAN_ESCALATION_POLICY.md` §4 | Must come from the insurer's vulnerable-customer policy |
| Currency and jurisdiction | NZD, New Zealand | Affects wording, thresholds and regulatory expectations |
| Unknown-value handling | Treat as above the review threshold | Conservative default; confirm |
| Mandatory FNOL field list | See `SYNTHETIC_DATA_SPEC.md` §4 | Defines completeness |

None of these should be presented to a stakeholder as an insurer-approved rule until it is one.
