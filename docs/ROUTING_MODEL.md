# Risk Routing & Escalation Model

**Phase 3.** The rule catalogue that turns claims intelligence into a routing
decision, and the reference for anyone asking "why did this claim get escalated?"

Implementation: `backend/routing/rules.py` (the catalogue), `backend/routing/router.py`
(evaluation), `backend/graph/escalation.py` (the graph node).

Every rule traces to a row in [`DECISION_TABLE.md`](DECISION_TABLE.md) or a trigger in
[`HUMAN_ESCALATION_POLICY.md`](HUMAN_ESCALATION_POLICY.md). Nothing here is new
business policy — Phase 3 implements Phase 0, it does not extend it.

> **Every threshold below is a POC proposal awaiting business approval.** Reasons that
> rest on one carry an `assumption` marker that survives into the API response and
> renders as a "POC assumption" chip in the UI.

---

## 1. The three outcomes

| Outcome | Meaning | Claim state | Queued? |
| --- | --- | --- | --- |
| `AUTOMATED_PATH_RECOMMENDED` | No escalation rule fired | Assessment | No |
| `HUMAN_REVIEW_REQUIRED` | A claims specialist must handle it | Human Review | Yes |
| `INFORMATION_REQUIRED` | The customer must supply something first | Information Required | No — the customer holds it |

`AUTOMATED_PATH_RECOMMENDED` is **not an approval.** It means no rule objected. Whether
such a claim may ever complete without a person is a Phase 4 governance question,
answered by PreNode PN-01 and the Invariants — none of which exist yet.

**No routing outcome can reach Approved/Completed.** That state is reachable only by a
reviewer's own action.

---

## 2. The rule catalogue

Listed in precedence order. **Every applicable rule fires** — a claim that is both
high-value and risky says both — but the **outcome** comes from the first match and the
**priority** is the strongest across all of them.

| # | Rule | Code | Fires when | Basis | Priority | Outcome | Phase 0 source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Emergency | `E-11_EMERGENCY` | Home not liveable, injury, ongoing damage, or utilities out | AI finding | **urgent** | Human review | HEP §4.1 · D-13 |
| 2 | Incomplete analysis | `E-16_INCOMPLETE_ANALYSIS` | Any agent failed or degraded | Business rule | high | Human review | HEP §2 E-16 |
| 3 | No cover basis | `E-05_POLICY_NOT_FOUND` `E-05_POLICY_NOT_IN_FORCE` `E-05_PERIL_NOT_COVERED` | Policy missing, lapsed at the date of loss, or peril not listed | AI finding | high | Human review | D-03 |
| 4 | Vulnerable customer | `E-12_VULNERABLE_CUSTOMER` | Support flag or accessibility need on the customer record | Business rule | high | Human review | HEP §4.2 · D-14 |
| 5 | Policy uncertainty | `E-06_POLICY_UNCERTAINTY` | An exclusion may be engaged, or cover is uncertain | AI finding | standard | Human review | D-09 |
| 6 | Conflicting information | `E-07_CONFLICTING_INFORMATION` | Validation found inconsistencies | AI finding | standard | Human review | D-12 |
| 7 | Risk indicators | `E-10_ELEVATED_RISK` / `E-09_RISK_INDICATOR` | Risk band high / medium | AI finding | high / standard | Human review (specialist if high) | D-11 / D-10 |
| 8 | Above authority | `E-04_ABOVE_AUTOMATED_AUTHORITY` | Estimate > NZD 20,000 | Business rule | high | Human review | D-08 · INV-02 in Phase 4 |
| 9 | High value | `E-03_HIGH_VALUE` / `E-03_VALUE_UNKNOWN` | Estimate > NZD 10,000, or no estimate at all | Business rule | standard | Human review | D-07 · §2.4 |
| 10 | High complexity | `E-02_HIGH_COMPLEXITY` | Any high-complexity factor | Business rule | standard | Human review | D-06 · §2.1 |
| 11 | Missing information | `E-08_MISSING_INFORMATION` | Validation status `information_required` | AI finding | standard | **Information required** | D-01 |
| 12 | Low confidence | `E-01_LOW_CONFIDENCE` / `E-01_NO_CONFIDENCE` | Workflow confidence below the POC floor (≈ 0.815), or no confidence at all | Business rule | standard | Human review | D-05 · PN-01 in Phase 4 |
| — | Rule failure | `E-16_ROUTING_RULE_FAILED` | A rule itself raised | Business rule | high | Human review | HEP §2 E-16 |

`E-14` (automation suspension) from the Phase 0 policy is deliberately **absent**:
suspension is what an Invariant violation produces, and Invariants are Phase 4.

### Why the order is the order

Safety first, then whether there is any cover to talk about, then who the customer is,
then the claim's own characteristics, then confidence. Two consequences worth stating:

- **Missing information does not outrank an emergency.** A customer whose home is unsafe
  reaches a person even with gaps in their FNOL.
- **Emergency is read from the FNOL, not only from the assessment.** A claim that
  short-circuits before the Assessment Agent runs — no policy found, information
  outstanding — is still checked for emergency signals. Routing always runs.

---

## 3. Every reason is structured

"The AI decided to escalate" is explicitly not good enough. Each reason carries:

| Field | Purpose |
| --- | --- |
| `code` · `label` | Stable identifier and a short human label |
| `detail` | One sentence a reviewer can act on |
| `basis` | **`ai_finding`** or **`business_rule`** — the distinction that matters most |
| `priority` · `outcome` | What it implies |
| `rule_reference` | Where the rule is written down |
| `observed_value` | What this claim actually showed |
| `threshold_value` | What it was measured against |
| `assumption` | Set when the rule rests on a POC-proposed number |
| `source_agent` | Which agent produced the underlying finding |

Worked example:

```
Above automated authority limit
  Basis:             Business rule
  Detail:            The estimated value is above the limit the POC rules allow
                     automated handling for. In Phase 4 this becomes a hard stop.
  Observed:          NZD 42,000
  Compared against:  NZD 20,000
  Rule:              docs/DECISION_TABLE.md D-08 · Invariant INV-02 in Phase 4
  From:              assessment
  [POC-proposed threshold pending business approval]
```

---

## 4. The three sources of truth, kept apart

| | What it is | Where it comes from | Who owns it |
| --- | --- | --- | --- |
| **AI finding** | An observation by an agent | The model plus retrieval | The system, with the uncertainty that implies |
| **Business rule** | A Phase 0 rule, evaluated deterministically | `routing/rules.py` | The business |
| **Human decision** | What a reviewer decided | A review action | The reviewer |

`RoutingDecision.decision_authority` is the fixed literal `"business_rules"`. The model
never decides a route: it supplies findings that rules evaluate. And
`ReviewActionResponse.decision_source` is the fixed literal `"human"` — a review outcome
is never attributed to the system.

---

## 5. Priority and review type

| Priority | Set by | Meaning |
| --- | --- | --- |
| `urgent` | Emergency | Safety before process. Top of the queue |
| `high` | Incomplete analysis, no cover basis, vulnerable customer, elevated risk, above authority | Needs attention ahead of routine work |
| `standard` | Everything else | Normal queue |

| Review type | When |
| --- | --- |
| `priority_review` | Any urgent reason |
| `specialist_review` | Elevated risk indicators |
| `standard_review` | Everything else |

The queue sorts urgent → high → standard, oldest first within a band. A queue that
buries the emergency claim is worse than no queue, so the ordering is part of the API
contract rather than a UI concern.

---

## 6. Claim-state transitions

| From | To | Trigger | Who |
| --- | --- | --- | --- |
| Submitted | Assessment | `AUTOMATED_PATH_RECOMMENDED` | Routing |
| Submitted | Human Review | `HUMAN_REVIEW_REQUIRED` | Routing |
| Submitted | Information Required | `INFORMATION_REQUIRED` | Routing |
| Human Review | Information Required | `request_information` | **Reviewer** |
| Human Review | Human Review (`specialist_referral`) | `refer_to_specialist` | **Reviewer** |
| Human Review | Approved/Completed | `complete_review` | **Reviewer only** |

Every transition is checked against `ALLOWED_TRANSITIONS` first. A routing decision that
would need an impossible transition is **refused and logged**, not forced — the claim
state model stays authoritative.

Routing can only ever move a claim to a state where a **person or the customer** holds
it. It cannot complete a claim.

---

## 7. Failing closed

| Failure | Result |
| --- | --- |
| An agent crashes | `E-16_INCOMPLETE_ANALYSIS` → human review |
| A dataset is missing | The agent degrades → `E-16` → human review |
| A routing rule raises | `E-16_ROUTING_RULE_FAILED` → human review |
| No confidence available | `E-01_NO_CONFIDENCE` → human review |
| No agent output at all | `E-01_NO_CONFIDENCE` → human review |

There is no path through this module where something going wrong produces
`AUTOMATED_PATH_RECOMMENDED`. "The risk check crashed" must never read the same as "no
risk found", and a test asserts it.

---

## 8. The vulnerable-customer and emergency pathways

**Vulnerable customer.** Read from the synthetic customer record: a support flag and any
accessibility need. The reason records that support is needed and how the customer wants
to be contacted — nothing medical, nothing diagnostic. A test asserts no such vocabulary
appears in the reason, and a second asserts that vulnerability never becomes a risk
indicator. Those two pathways must not be allowed to touch.

**Emergency.** Detected from the FNOL itself so it survives a short-circuit, given
`urgent` priority and `priority_review`, and surfaced in the UI with make-safe guidance
that is explicitly marked placeholder wording — Phase 0 requires the insurer's own
approved emergency content, and the AI must not improvise safety advice.

Neither pathway allows the automated route for the rest of that claim.

---

## 9. Where Phase 4's gates go

| Seam | Commitment point | What Phase 4 adds |
| --- | --- | --- |
| `graph/escalation.py :: escalation_node` | CP-11 (taking the automated route) | `gated_node` wrapping, `route_on_denial` on the edge, unique `denial_key` |
| `ReviewService.apply_routing` | CP-09 (claim-state write), CP-12 (queue placement) | Gate awaited immediately before the writes |
| `ReviewService.perform_action` | CP-09 | Gate awaited immediately before the write |

The mapping from today's rules to Phase 4 constructs:

| Today (Phase 3) | Phase 4 |
| --- | --- |
| `E-01_LOW_CONFIDENCE` routing rule | **PreNode PN-01** denial → fallback to human review |
| `E-04_ABOVE_AUTOMATED_AUTHORITY` routing rule | **Invariant INV-02** → TerminalState → suspension |
| `E-05_POLICY_NOT_IN_FORCE` routing rule | **Invariant INV-01** → TerminalState |
| `E-06_POLICY_UNCERTAINTY` routing rule | **Invariant INV-03** → TerminalState |

The difference is not cosmetic. Today these *route*; in Phase 4 the Invariants *stop*
automation and require human re-enablement recorded as a HUMAN_AUTHORISED_TRANSITION.
Phase 3 deliberately does not simulate that — see `GOVERNANCE_POLICY_CATALOGUE.md`.

**No PreNode, Invariant, TerminalState or ledger record exists in Phase 3**, and none is
faked. A test asserts the governance modules and VSL packages are absent.

---

## 10. Values requiring business approval

All of them. Consolidated in [`DECISION_TABLE.md` §7](DECISION_TABLE.md); the ones this
module reads are the value bands, the complexity factors, the risk banding, the
confidence boundary, and the emergency and vulnerability signal definitions.
