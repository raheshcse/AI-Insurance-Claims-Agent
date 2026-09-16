# Commitment Point Catalogue

**Phase 0 — Business & Governance Foundation.**

A **commitment point** is any place in the future claims workflow where the system commits to
something it cannot take back, or produces an outcome that is meaningful outside the system.
The X-Verba/VSL guidance names the archetypes directly: *an LLM call, a payment, a database
write, an outbound message, a deployment, a handover to another agent.*

The governing rule from that guidance, which shapes this entire catalogue:

> Every `await gate(...)` precedes what it guards. The side effect is the last thing the caller
> does, and is unreachable from any denial path. **MUST NOT perform the side effect before the
> gates.**

Columns: what the action is · why it is consequential · recommendation or action · whether
governance runs before it · the expected mechanism (see `GOVERNANCE_POLICY_CATALOGUE.md` for the
PreNode/Invariant definitions).

---

## 1. Catalogue

### CP-01 — LLM call for intake understanding

| | |
| --- | --- |
| **Where** | Intake Agent, during FNOL conversation |
| **Why consequential** | The guidance names an LLM call as a commitment archetype. Its output becomes the structured claim information everything downstream relies on. Tokens are spent and the customer sees the reply |
| **Rec or action** | **Recommendation** (R-01) — until written to the claim record |
| **Governance before?** | **MONITOR entry, yes. Full gate, no** — for every claim, a MONITOR entry is written so audit check 1 has continuous evidence rather than only-on-incident evidence. The commitment that matters is CP-02 |
| **Mechanism** | `ledger.write_monitor(...)` per governed decision, with `drift_detected` set from the confidence comparison |
| **Note** | Conversational turns are not individually gated — gating every turn would make the assistant unusable and would gate a recommendation rather than an action. This is a deliberate reading of the guidance and is listed for confirmation in §4 |

### CP-02 — Issue claim reference and write the claim record

| | |
| --- | --- |
| **Where** | Draft → Submitted |
| **Why consequential** | The customer is given a reference and told a claim exists. The insurer's duty to respond begins. Cannot be unsaid |
| **Rec or action** | **Action** (A-01, A-02) |
| **Governance before?** | **Yes** |
| **Mechanism** | Gate before the database write and before the acknowledgement message. Invariant `policy-in-force` is available here if the policy is already known |

### CP-03 — Accept retrieved policy context as the cover basis

| | |
| --- | --- |
| **Where** | Policy Agent output accepted into state |
| **Why consequential** | Every downstream judgement — validation, cover, excess, exclusions — rests on it. A wrong cover basis produces a confidently wrong claim outcome |
| **Rec or action** | **Recommendation** (R-02), but it becomes the basis of an action at CP-11 |
| **Governance before?** | **Yes — Invariant** |
| **Mechanism** | Invariant `policy-in-force`: the policy must have been active at the date of loss. Violation → TerminalState. Decision row D-03 |

### CP-04 — Accept the validation result

| | |
| --- | --- |
| **Where** | Validation Agent output accepted |
| **Why consequential** | Drives the state change to Information Required and the itemised request to the customer. A false "complete" lets an under-evidenced claim reach the automated route |
| **Rec or action** | **Recommendation** (R-03) |
| **Governance before?** | Not itself gated — it is gated where it acts, at CP-09/CP-10 |
| **Mechanism** | Deterministic workflow logic; completeness is a checkable fact, not a confidence judgement |

### CP-05 — Use the classification for routing

| | |
| --- | --- |
| **Where** | Assessment Agent classification consumed by the router |
| **Why consequential** | Named explicitly in the requirements as a governance decision point. A misclassified claim is routed wrongly and assessed against the wrong expectations |
| **Rec or action** | **Recommendation** (R-04) that becomes an action the moment it is routed on |
| **Governance before?** | **Yes** — as part of the CP-11 gate |
| **Mechanism** | PreNode `automation-confidence`, whose input includes classification confidence |

### CP-06 — Use the triage recommendation (complexity, urgency, value)

| | |
| --- | --- |
| **Where** | Assessment Agent triage output |
| **Why consequential** | Determines whether a human ever sees the claim, and whether the authority-limit Invariant engages |
| **Rec or action** | **Recommendation** (R-05, R-06, R-10) |
| **Governance before?** | **Yes** — at CP-11. The estimated value is the Invariant's input |
| **Mechanism** | Deterministic escalation rules (D-06, D-07) plus Invariant `automated-authority-limit` |

### CP-07 — Act on the risk/fraud recommendation

| | |
| --- | --- |
| **Where** | Fraud & Risk Agent output triggering referral |
| **Why consequential** | Named explicitly in the requirements. A referral is reputationally serious for the customer; a missed one exposes the insurer |
| **Rec or action** | **Recommendation** (R-09) → **Action** (A-06) on referral |
| **Governance before?** | **Yes**, before the referral is recorded or the queue entry created |
| **Mechanism** | Deterministic escalation rule on the risk band, gated before the routing write. Indicators never reach the customer |

### CP-08 — Commit an agent-to-agent handover

| | |
| --- | --- |
| **Where** | Any graph edge where the receiving agent treats the handed-over state as established fact |
| **Why consequential** | Named by both source documents. The receiving agent does not re-derive what it is given; an unchecked handover launders an unverified recommendation into an input |
| **Rec or action** | **Action** (A-07) where it advances the workflow; a pure state read is not |
| **Governance before?** | **Yes** for the handover into the routing decision; not for intermediate reads |
| **Mechanism** | In Phase 4, `gated_node` on the governed node plus `route_on_denial`. Each gate gets **its own `denial_key`** — the guidance is explicit that two gates sharing a key makes the second router read the first gate's denial |

### CP-09 — Write a claim-state change

| | |
| --- | --- |
| **Where** | Every official state transition |
| **Why consequential** | A database write, named directly by the guidance. State drives SLAs, customer-visible status and downstream behaviour |
| **Rec or action** | **Action** (A-02) |
| **Governance before?** | **Yes — every time, without exception** |
| **Mechanism** | Gate before the write. The suspension check runs first: a suspended claim returns `suspended` before any other evaluation (D-16) |

### CP-10 — Send an outbound customer communication

| | |
| --- | --- |
| **Where** | Acknowledgement, information request, status update, outcome message |
| **Why consequential** | An outbound message is a commitment archetype in the guidance. It cannot be unsent and it sets expectations the insurer must meet. A message containing a wrong cover statement is a regulatory problem, not a UX one |
| **Rec or action** | Draft = **recommendation** (R-12); send = **action** (A-03) |
| **Governance before?** | **Yes** |
| **Mechanism** | Gate before send. Risk indicators must never appear in customer-facing content; policy statements must cite retrieved wording |

### CP-11 — Take the automated route

| | |
| --- | --- |
| **Where** | Assessment → Approved/Completed without human review |
| **Why consequential** | **The principal commitment of this POC.** A claim decision is made with no human in the loop |
| **Rec or action** | **Action** (A-04) |
| **Governance before?** | **Yes — this is the gate the whole governance layer exists for** |
| **Mechanism** | Full sequence: MONITOR → PreNodes → Invariants → SUFFICIENT verification → side effect. Any PreNode denial routes to human review; any Invariant violation writes INSUFFICIENT, a TERMINAL entry, and suspends |

### CP-12 — Place a claim in the human review queue

| | |
| --- | --- |
| **Where** | Every escalation path, including emergency and vulnerable-customer routing |
| **Why consequential** | Consumes scarce human capacity and changes the customer's timeline. Equally, a *failure* to queue means a denial silently disappeared — which the non-functional requirements forbid |
| **Rec or action** | **Action** (A-05) |
| **Governance before?** | **Yes** — and the queue write is itself the evidence that a denial was honoured |
| **Mechanism** | Fallback target of the PreNode (`ROUTE_TO_HUMAN_QUEUE`), plus deterministic escalation rules. The UI must render it as a real review state, never swallow it |

### CP-16 — Write a ledger entry

| | |
| --- | --- |
| **Where** | Throughout the governed path |
| **Why consequential** | Append-only and hash-chained. A wrong entry cannot be edited away, and a missing one breaks the audit permanently |
| **Rec or action** | **Action** (A-08) |
| **Governance before?** | It *is* the governance record — not gated by itself |
| **Mechanism** | `caused_by` MUST be set on every entry. Without it, `audit()` falls back to a "same identity, later timestamp" heuristic that can match an unrelated PRE_NODE under concurrency and report a false pass |

### CP-17 — Re-enable automation after a TerminalState

| | |
| --- | --- |
| **Where** | Human Review, `automation_suspended` |
| **Why consequential** | Undoes a hard stop. If it can happen automatically, the hard stop was never hard |
| **Rec or action** | **Action** (A-09) — **human only** |
| **Governance before?** | **Yes**, and it is the only way out of suspension |
| **Mechanism** | A **HUMAN_AUTHORISED_TRANSITION** ledger entry with `caused_by` pointing at the TERMINAL entry. This is exactly what audit check 5 requires: *every TERMINAL has a HUMAN_AUTHORISED_TRANSITION caused_by it* |

### CP-15 — Initiate settlement or payment · **FUTURE, OUT OF SCOPE**

| | |
| --- | --- |
| **Why consequential** | Money moves. The guidance lists payment first among commitment archetypes |
| **Rec or action** | **Action** (A-10) |
| **Governance before?** | Would require its own Invariant set and almost certainly a mandatory human authorisation, regardless of value |
| **Status** | Named as a *future* decision point by the requirements. **Not in this POC.** Recorded here so it is not forgotten |

---

## 2. Summary table

| CP | Action | Rec / Action | Governed before? | Mechanism |
| --- | --- | --- | --- | --- |
| CP-01 | LLM call for intake understanding | Rec | MONITOR only | `write_monitor` |
| CP-02 | Issue claim reference, write claim record | Action | **Yes** | Gate before write + message |
| CP-03 | Accept policy context as cover basis | Rec → basis for action | **Yes** | Invariant `policy-in-force` |
| CP-04 | Accept validation result | Rec | At its effects | Deterministic logic |
| CP-05 | Route on classification | Rec → Action | **Yes** | PreNode `automation-confidence` |
| CP-06 | Use triage (complexity/urgency/value) | Rec | **Yes** | Escalation rules + Invariant `automated-authority-limit` |
| CP-07 | Act on risk recommendation | Rec → Action | **Yes** | Escalation rule, gated |
| CP-08 | Commit agent handover | Action | **Yes** (governed edges) | `gated_node` + `route_on_denial`, unique `denial_key` |
| CP-09 | Claim-state write | Action | **Yes — always** | Gate before write |
| CP-10 | Outbound customer communication | Draft rec → send Action | **Yes** | Gate before send |
| CP-11 | Take the automated route | Action | **Yes — principal gate** | Full MONITOR → PreNode → Invariant sequence |
| CP-12 | Queue for human review | Action | **Yes** | Fallback + escalation rules |
| CP-16 | Write ledger entry | Action | It is the record | `caused_by` mandatory |
| CP-17 | Re-enable after suspension | Action, human only | **Yes** | HUMAN_AUTHORISED_TRANSITION |
| CP-15 | Settlement / payment | Action | Future | Out of scope |

---

## 3. Gate placement principle

```
   evaluate ──► MONITOR ──► PreNodes ──► Invariants ──► VERIFICATION ──► ┃ SIDE EFFECT ┃
                                │              │                          ▲
                        denial  │              │ violation                │
                                ▼              ▼                    unreachable from
                        human queue     TERMINAL + suspend           any denial path
                        (SUFFICIENT)      (INSUFFICIENT)
```

The side effect is the last statement in the caller and has no path from a denial branch. That
ordering *is* the pre-commitment property (F1) — it is what makes the assurance claim true
rather than asserted.

---

## 4. Open questions on this catalogue

1. **CP-01 granularity.** Is a MONITOR entry per governed decision sufficient, or does the
   business want every conversational LLM turn gated? Gating every turn gates a recommendation
   and would make the assistant unusable; this catalogue assumes it is not wanted.
2. **CP-08 scope.** Which graph edges count as "committing" handovers? Proposed: only the
   handover into the routing decision. Needs confirmation once the graph exists.
3. **CP-10 breadth.** Should *every* outbound message be gated, or only those containing a
   claim outcome or a policy statement? This catalogue gates all of them.
4. **Which CPs are in scope for Phase 4.** The requirements list seven candidate decision
   points; this catalogue expands them to fifteen. The business must confirm which are
   implemented in the POC versus documented for later.
5. **Monitoring gap tolerance.** Audit check 1 requires MONITOR entries within
   `max_monitor_gap_seconds`. What gap is acceptable for a claims system that may sit idle
   overnight? A low-traffic system can fail this check simply by being quiet.


---

## CP-13 — the LLM call (added in the governance refactor)

| | |
| --- | --- |
| **What commits** | Claim-derived facts leave the system for a third-party model |
| **Why irreversible** | Egress cannot be undone. Once a payload has been sent, no downstream handling retrieves it. |
| **Where** | `backend/agents/base.py :: ClaimsAgent.narrate` |
| **Gate** | `governance.gates.govern_llm_narration(candidate, perform=...)` |
| **Governed by** | INV-04 `no-customer-data-egress`, plus the shared TerminalState |
| **On denial** | The provider is never reached. No request is built, no socket opens, `GEMINI_API_KEY` is never read. |
| **Recorded** | MONITOR → VERIFICATION (SUFFICIENT); on violation MONITOR → VERIFICATION (INSUFFICIENT) → TERMINAL → SPECIFICATION_UPDATE |

The X-Verba spec §1 names "an LLM call" as the first example of a commitment
point. This POC had five of them per analysis, ungoverned, until the refactor —
they ran in the agent nodes, upstream of every existing gate.

**Not governed, and why.** Reading synthetic reference data is not a commitment.
Writing the analysis record does not change the claim. Composing a
`NarrationRequest` is not egress — only sending it is, which is what CP-13
guards. Governing more than this would add ledger noise and dilute what a gate
means.

---

## CP-14 — the automated claim action (added in the governance refactor)

| | |
| --- | --- |
| **What commits** | The system handles a claim **without a person** — the claim-state write, the internal-status change, and the placement (or non-placement) that follows from it |
| **Why irreversible** | A claim that has been progressed automatically has been progressed. Undoing it is a manual correction with a customer-visible history, not a rollback |
| **Where** | `governance/gates.py :: govern_automated_route` — the Invariant block, evaluated before `perform()` |
| **Gate** | INV-01 `policy-in-force`, INV-02 `automated-authority-limit`, INV-03 `no-auto-approval-under-exclusion` |
| **On denial** | `perform()` is unreachable. `GovernanceOutcome.action` becomes `action_denied` and `automated_action_allowed` is `False` |
| **Recorded** | MONITOR → PRE_NODE → VERIFICATION, with `commitment: "automated_claim_action"`, the Invariant, the observed value and the threshold it exceeded |

### Why this is a separate commitment point from CP-11

CP-11 asks *"may this run proceed down the automated path?"* and is answered by
the PreNode on confidence. CP-14 asks *"may this **claim** be handled
automatically at all?"* and is answered by the Invariants on the claim's own
facts. They are adjacent in the code and answer different questions, and merging
them is what produced the defect this section records.

### The defect

INV-01…03 previously short-circuited to `True` whenever `automated_route_proposed`
was false. The effect on a NZD 42,000 claim:

```
business rule says "above the automated authority limit"
  -> routing: HUMAN_REVIEW_REQUIRED
  -> automated_route_proposed = False
  -> INV-02 returns True without looking at the value
  -> governance reports PERMITTED
```

Governance reported approval for an action it had never examined. Reversing the
condition in the UI would not have fixed it — the verdict itself was wrong.

### The fix, and the case it must not break

The Invariants now evaluate the candidate's facts unconditionally. That alone
would suspend automation on every large claim, so the *severity* of a denial is
what depends on `automated_route_proposed`:

| | `attempted = False` | `attempted = True` |
| --- | --- | --- |
| Meaning | routing and governance agree | the layer above tried a prohibited action |
| Verification | `SUFFICIENT` | `INSUFFICIENT` |
| TerminalState | none | `claim-automation-suspended` |
| `SPECIFICATION_UPDATE` | not written | written |
| Audit consequence | none | check 4 requires the update; check 5 fails until a person re-enables |

Recording routine denials as `INSUFFICIENT` would demand a root-cause analysis
for every claim over the limit, and audit check 4 would fail permanently on
ordinary traffic — the trap the X-Verba spec names explicitly.

### CP-13 is not CP-14

An LLM call being permitted says nothing about whether the claim may be handled
automatically. The two gates run different rules at different commitment points,
and a NZD 42,000 claim routinely produces **CP-13 PERMITTED, CP-14 DENIED**. The
API and the console publish them as separate fields for that reason;
`GovernanceOutcome.automated_action_allowed` exists so that no caller can read
one as the other.

### Numbering note

The Phase 0 catalogue above used CP-13 and CP-14 for "write a ledger entry" and
"re-enable automation". Those are now **CP-16** and **CP-17**. The governance
refactor had already published CP-13 as the LLM call in code, tests and the API
(`commitment_point: "CP-13"`), so renumbering the two documentation-only entries
was the smaller and less error-prone change.
