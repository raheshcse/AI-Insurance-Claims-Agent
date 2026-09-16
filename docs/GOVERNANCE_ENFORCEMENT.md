# Governance enforcement — how X-Verba / VSL actually runs

**Phase 4.** Companion to `GOVERNANCE_POLICY_CATALOGUE.md`, which says *what* is
governed. This says *how it is enforced*, and — just as importantly — what this
implementation does **not** give you.

Synthetic data only. Every threshold here is a POC proposal awaiting business
approval, not an insurer-approved rule.

---

## 1. The claim this phase makes, in one sentence

When this system is about to commit to handling a claim automatically, a real
`vsl_core` PreNode and three real `vsl_core` Invariants run **first**, the
irreversible write is passed into the gate as a callable so no denial path can
reach it, and every decision is recorded in a hash-chained `VerbaLedger` that the
framework's own `audit()` can check and can fail.

Everything below is either evidence for that sentence or a limit on it.

---

## 2. What is real, and how you can tell

| Question | Answer | How to check it yourself |
| --- | --- | --- |
| Is this the actual framework? | Yes — `super-semantics-vsl` (imports as `vsl_core`) and `vsl-langgraph` | `test_every_construct_is_an_actual_vsl_core_type` asserts `type(x) is vsl_constructs.PreNode`, which a look-alike subclass would fail |
| Does the adapter obey the VSL contract? | Yes | `python -m governance.audit_cli conformance` runs `run_conformance_suite` and reports CONFORMANT |
| Does the gate really run before the side effect? | Yes | `test_the_side_effect_is_referenced_once_and_only_after_every_gate` reads the source of `govern_automated_route` and asserts the single `perform()` call sits after the last gate `await`, and after every denial's `return` |
| Is the ledger a hash chain? | Yes | `test_the_ledger_is_hash_chained_and_detects_tampering` edits one payload field on disk and `verify_integrity()` goes False |
| Can the audit fail? | Yes, and it does | An open terminal state fails check 5; `python -m governance.audit_cli audit` exits 1 |

---

## 3. Where the gates are, and why there

Governed commitment points, doing different jobs.

| Point | Location | What it protects | Mechanism |
| --- | --- | --- | --- |
| **CP-13** | `backend/agents/base.py :: narrate` | **the LLM call — data leaving for a third party** | `govern_llm_narration(perform=...)` |
| CP-11 | `backend/graph/governed.py` | the workflow committing to the automated branch | `gated_node` + `route_on_denial` |
| **CP-14** | `governance/gates.py :: govern_automated_route` | **the automated claim action — handling a claim without a person** | INV-01/02/03, evaluated before `perform()` |
| CP-09 / CP-12 | `backend/app/services/review_service.py :: apply_routing` | the claim-state write and queue placement | `govern_automated_route(perform=...)` |

**CP-14 and CP-09/CP-12 are one gate call, in that order.** The Invariants
decide whether this claim may be handled automatically at all; only a claim that
clears them reaches the write that `apply_routing` handed in. They are listed
separately because they answer different questions, and answering the second
without asking the first is the defect this refactor removed.

**CP-13 was added in the governance refactor, and it closed a real gap.** The
spec's §1 lists an LLM call first among the things code cannot take back, and
until the refactor it was the one commitment here that ran ungoverned: all five
agents narrate inside the agent nodes, which execute *before* `governance_gate`
in the graph. VSL ran after the model, not before it.

The commitment points carry different Invariants — `AUTOMATED_ROUTE_INVARIANTS`
(INV-01/02/03) at the automated action, `LLM_EGRESS_INVARIANTS` (INV-04) at the
call — because they ask different questions. They share one TerminalState, so a
claim suspended at either is refused at the other.

**A CP-13 permission is not a CP-14 permission.** The gates are separate, the
rule sets are disjoint, and a NZD 42,000 claim routinely produces CP-13
PERMITTED alongside CP-14 DENIED. `GovernanceOutcome` therefore exposes
`automated_action_allowed` as a field distinct from `permitted`: the first is
false for every outcome except `proceed`, so no caller can read "the gate
returned" as "the automated action was approved".

### The Invariants judge the claim, not the routing decision

INV-01…03 previously short-circuited to `True` when `automated_route_proposed`
was false, which made governance report PERMITTED on a NZD 42,000 claim — it was
answering a question nobody had asked. They now evaluate the candidate's own
facts every time. What depends on routing is the *severity*:

| | routing already chose a person | the layer above attempted it |
| --- | --- | --- |
| `automated_action_attempted` | `False` | `True` |
| Verification result | `SUFFICIENT` — governance worked | `INSUFFICIENT` — an incident |
| TerminalState | none | `claim-automation-suspended` |
| `SPECIFICATION_UPDATE` | not written | written |

Recording the routine case as `INSUFFICIENT` would demand a specification update
for every claim over the limit and audit check 4 would fail permanently on
ordinary traffic. Full rationale: `docs/COMMITMENT_POINTS.md`, CP-14.

The authoritative one is the second. It carries the ledger and the Invariants
because it guards the irreversible write. The first is the workflow's own soft
gate: on denial the graph routes away from the automated branch, so the run never
reaches the code that would propose automation at all.

**Why the side effect is a callable.** `apply_routing` does not call the gate and
then decide whether to write. It hands the write *in*:

```python
governance, _ = await govern_automated_route(
    _governance_candidate(claim, intelligence),
    perform=lambda: self._apply_outcome(claim, intelligence, routing, outcome),
)
```

Inside `govern_automated_route`, `perform()` appears exactly once, on the last
line of the proceed path. Every denial path returns above it. So a denied action
is not "checked and then skipped" — the code that would take it is unreachable.
That is what makes F1 (pre-commitment) a property of the program rather than a
claim in a comment.

---

## 4. The constructs, and where each came from

No construct is invented. Each maps to a Phase 0 / Phase 3 rule.

| Construct | Name | From | On failure |
| --- | --- | --- | --- |
| PreNode (soft gate) | `automation-confidence` | E-01 | `ROUTE_TO_HUMAN_QUEUE` — reroute to a person |
| Invariant (hard rule) | `policy-in-force` | E-05 | TerminalState |
| Invariant (hard rule) | `automated-authority-limit` | E-04 | TerminalState |
| Invariant (hard rule) | `no-auto-approval-under-exclusion` | E-06 | TerminalState |
| TerminalState | `claim-automation-suspended` | — | human-authorised transition only |

### Why the Invariants should almost never fire

The three Invariants mirror escalation rules the Phase 3 routing layer already
enforces. So when routing is working correctly, any claim it sends down the
automated path has already satisfied all three, and the Invariants pass. That is
not a weakness — it is the point.

**The Invariants exist to catch the routing layer being wrong.** A bug, a bad
deploy, a threshold edited in the wrong file: any of those can make the layer
above recommend automation for a claim that should never have it. The Invariant
sits at the commitment point, downstream of that mistake, and stops the write.
`test_an_invariant_catches_the_routing_layer_being_wrong` demonstrates exactly
this: a deliberately broken router recommends the automated path for a
NZD 240,000 claim, and INV-02 halts it, suspends automation and records why.

If an Invariant ever fires in production, the correct reading is **"the layer
above is wrong"**, not "we found an unusual claim". That is why a violation
writes an INSUFFICIENT verification *and* a `SPECIFICATION_UPDATE` registering
the active specification for review.

### Why an unknown value is not an Invariant violation

`_within_automated_authority` treats a missing estimate as *not* a violation. An
Invariant means "proceeding anyway is always wrong". With no estimate we do not
know that proceeding is wrong — we know that we do not know, which is a review
matter, and Phase 3's rules already send it to a person. An Invariant that fires
on ignorance rather than on breach would make the terminal state meaningless.

---

## 5. Assurance is derived, and it is LOW

VSL will not let you assert an assurance level. You supply two facts and it
derives one:

| Fact | Our value | Meaning |
| --- | --- | --- |
| F1 — pre-commitment | `True` | the gate runs before the commitment |
| F2 — modification | `NONE` | the gate does not change the energy landscape |
| **Derived level** | **LOW** | output-layer control |

**LOW is the correct answer and is reported as LOW everywhere** — in the API, on
the dashboard, and in this document. It means the gates block a bad action; they
do not change how the model decides. The only route to HIGH is a
formation-layer change — loss function, feature space, training — which this POC
does not make. Claiming anything above LOW would be a fabrication.

---

## 6. Gamma: the mistake that would have been silent

`vsl-core` ships no Gamma estimator, so `governance/policy.py` supplies one:

```
gamma = (p / (1 - p)) / (t / (1 - t))
```

where `t` is the decision boundary (0.80). **Dividing by the boundary odds is
load-bearing.** Using the raw odds `p / (1 - p)` silently assumes a boundary of
0.5. At our boundary of 0.80 that mistake would make every claim look far more
confident than it is, and the PreNode would wave through work it should stop —
with no error raised anywhere, no failing test, and no log line. It would simply
govern less than it appeared to.

Gamma = 1.0 therefore means "exactly on the boundary" — no governance signal.

**The confidence floor is derived, not chosen.** Solving
`gamma >= ROBUST_GAMMA_DEFAULT_THRESHOLD` (1.1) for `p` at `t = 0.80` gives
**0.8148**. That is the confidence a claim must reach for PN-01 to pass — higher
than the boundary itself, because robustness costs something.

### Runtime Gamma vs a static scan

There is **no `x-verba scan` command**. Neither distribution ships a console
entry point or a static-analysis module, and no static Γ figure is reported
anywhere in this project, because computing one would mean inventing a number.
What the framework does provide mechanically is
`vsl_core.conformance.suite.run_conformance_suite`, exposed as
`python -m governance.audit_cli conformance`. It checks the *adapter contract*
and nothing else — not the ledger, not runtime Gamma. The three are reported
separately and never merged into one "governance is fine" line.

---

## 7. The ledger, and the two questions it answers

```
MONITOR ──caused_by──> PRE_NODE ──caused_by──> VERIFICATION
                                                    │
                                    (INSUFFICIENT)  ├──> TERMINAL ──> HUMAN_AUTHORISED_TRANSITION
                                                    └──> SPECIFICATION_UPDATE
```

**`caused_by` is set on every entry, and that is not cosmetic.** Without it,
`audit()` falls back to a "same identity, later timestamp" heuristic that can
match an unrelated PRE_NODE and report a **false pass** under concurrency. A
claims queue is exactly that concurrency.

**A MONITOR is written for every request**, not only for incidents, so audit
check 1 has continuous evidence rather than only-on-incident evidence.

### SUFFICIENT vs INSUFFICIENT — the trap

| Event | Verification result | Why |
| --- | --- | --- |
| PreNode denial | **SUFFICIENT** | Governance *worked*. The claim went to a person, which is the declared fallback. |
| Invariant violation | **INSUFFICIENT** | Governance *failed* — something reached the commitment point that should not have. |

Recording a PreNode denial as INSUFFICIENT would make audit check 4 demand a
`SPECIFICATION_UPDATE` for every ordinary low-confidence claim. The audit would
then fail permanently on routine traffic, and everyone would learn to ignore it.
An audit that always fails is worth exactly as much as one that always passes.

### `verify_integrity()` ≠ `audit()`

They answer different questions and both are always run:

- **`verify_integrity()`** — were these records edited? (re-walks the hash chain)
- **`audit()`** — do these records describe a governed process? (five checks)

A ledger can be perfectly intact and describe a process with a terminal state
nobody ever resolved. It can also pass every structural check while having been
rewritten. Reporting one as though it answered the other is the easiest way to
produce a governance claim that is false, so `certify` requires both.

---

## 8. The terminal state, and the only way out

`claim-automation-suspended` has `requires_human_authorised_transition=True`.
Nothing lifts it on its own: no timeout, no retry, no confidence score, no
successful re-analysis. A suspended claim that is re-submitted is refused again
before the PreNode even runs.

The exit runs through `vsl_core.governance.request_re_enablement`, which produces
the successor `Instance` and the `HumanAuthorisedTransition` **together**, so a
caller cannot obtain one without the other. `Evidence` is a validated type: an
empty root-cause analysis is refused at construction, by the framework, not by
our code.

In the application this is a review action on the claim
(`POST /api/review-queue/{claim_id}/re-enable-automation`), taken by a named
person with a root-cause analysis and a specification-update proposal. It is
**not** a button on the governance dashboard — the dashboard is read-only, and a
dashboard that can change governance state is a second, unaudited enforcement
path.

Re-enabling automation **decides nothing about the claim**. The reviewer still
holds it; only future automated steps become permitted again.

---

## 9. The audit, and why it is allowed to fail

The framework's five checks:

| # | Check | What it means here |
| --- | --- | --- |
| 1 | `no_monitoring_gaps` | monitoring is continuous |
| 2 | `drift_flagged_monitor_has_pre_node` | every drift signal reached a gate |
| 3 | `pre_node_has_verification` | every gate decision was verified |
| 4 | `insufficient_verification_has_specification_update` | every governance failure was registered for review |
| 5 | `terminal_has_human_authorised_transition` | every terminal state was lifted by a person |

**With an open terminal state, check 5 fails and the CLI exits 1.** That is the
ledger telling the truth about unfinished governance, not a defect. After a human
authorises the transition, the audit passes 5/5 and a `VerbaCertificate` can be
issued. `verify_integrity()` is True throughout — the records were always intact;
the *process* was unfinished.

**Check 1 is reported as NOT ASSERTED unless you supply a threshold.** `vsl-core`
deliberately has no universal default for monitoring cadence, and passing `None`
*skips* the check while reporting it as passed. Repeating that as "passed" would
overstate what was checked, so the CLI, the API and the dashboard all separate
`checks_not_asserted` from `checks_passed`, and the dashboard styles it visibly
differently from a pass.

---

## 10. Running it

```bash
python -m governance.audit_cli verify        # hash chain intact?            exit 0/1
python -m governance.audit_cli audit         # the five checks               exit 0/1
python -m governance.audit_cli certify       # certificate, or refusal       exit 0/1
python -m governance.audit_cli conformance   # adapter contract              exit 0/1
python -m governance.audit_cli summary       # what happened, in numbers     exit 0

# machine-readable
python -m governance.audit_cli audit --json
# assert check 1 rather than skipping it
python -m governance.audit_cli audit --max-monitor-gap-seconds 3600
```

Exit codes: `0` passed, `1` failed, `2` could not run (no ledger, empty ledger,
bad arguments). Non-zero on failure is the point — an audit that only prints is
an audit nobody notices. This is what CI would run.

An **empty ledger is refused** for `audit` and `certify` (exit 2). An empty
ledger satisfies every check vacuously; it is not evidence of governance.

---

## 11. Stated limitations

These are limitations of this POC, written down rather than worked around.

1. **Suspension state lives in process memory.** It does not survive a restart
   and is not shared across workers. This is the one the Phase 4 brief
   specifically warns against pretending to have solved, so: it is not solved.
   What exists instead is `rebuild_suspensions_from_ledger()` — the production
   re-derivation (a TERMINAL with no later HUMAN_AUTHORISED_TRANSITION is an open
   suspension), implemented and tested, so moving to Redis is a storage swap
   rather than a redesign.
   `test_suspension_state_does_not_survive_a_restart_and_is_rebuilt_from_the_ledger`
   asserts both halves of this, including the failure.

2. **Derived assurance is LOW.** Output-layer control only. See §5.

3. **`Fallback`'s fields are declarative.** `vsl-langgraph` emits a warning at
   import saying `gated_node` does not consume `Fallback` — no retry loop is
   implemented by the adapter. The warning is real, expected, and left visible
   rather than suppressed. `ROUTE_TO_HUMAN_QUEUE` is implemented by us, in
   `governance/gates.py` and `graph/governed.py`, as the VSL guidance instructs.

4. **The `Proofing` is a documentation review, not a formal proof.** The
   specification's `verified_against` says so in those words.

5. **The governance authority is a POC placeholder.** A real deployment names a
   real board with a real escalation contact.

6. **Every threshold is a POC proposal.** None is insurer-approved.

7. **No authentication** on any internal endpoint, governance dashboard
   included. Phase 6.

8. **The ledger is a JSONL file.** `fsync=True` deliberately — a record lost in a
   page cache never happened, and a governance record that never happened is
   worse than one that says "denied". It is still a file, and Phase 6 replaces
   it.

9. **`verify_integrity()` detects tampering; it does not prevent it.** Anyone
   with write access to the file can rewrite the chain from a chosen point
   forward. `current_checkpoint()` exposes the tip an external witness would need
   to anchor the chain over time — `vsl-core` exposes the value and stops there,
   and so does this POC. Nothing transmits it anywhere.

---

## 12. What the Phase 0 constraints turned into

`governance/` was reserved from Phase 0 with a list of constraints the implementation would have
to satisfy. Every one of them bit. None was theoretical.

| Constraint written in Phase 0 | What Phase 4 found |
| --- | --- |
| `Fallback`'s fields are declarative only | Confirmed — `vsl-langgraph` emits a `UserWarning` at import saying `gated_node` does not consume `Fallback`. The warning is left visible, not suppressed. `ROUTE_TO_HUMAN_QUEUE` is implemented in `gates.py` and `graph/governed.py`. |
| In-process suspension does not survive a restart | Confirmed and **not solved**. `rebuild_suspensions_from_ledger()` is the production re-derivation, implemented and tested; a test asserts both the loss and the recovery. |
| `AutomationDeniedException` can be swallowed | Structural answer instead of a grep: the side effect is passed *into* the gate, so swallowing the exception still cannot reach it. |
| `verify_integrity()` cannot detect truncation | Carried into §11 above as a stated limitation, with `current_checkpoint()` named as the anchoring value an external witness would need. |
| Static Γ ≠ runtime Gamma | Sharper than expected: **there is no `x-verba scan` tool at all** — no console entry point, no static-analysis module. No static Γ figure is reported anywhere, because computing one would mean inventing it. `audit_cli conformance` runs the framework's real adapter suite instead. |
| SUFFICIENT vs INSUFFICIENT | Exactly the trap described. A PreNode denial writes SUFFICIENT; only an Invariant violation writes INSUFFICIENT. |
| Unique `denial_key` per gate | Implemented as `policy.DENIAL_KEYS`, one per gate. |
| Gamma vs the decision boundary | The one that would have failed silently: dividing by the raw odds assumes a boundary of 0.5. Ours is 0.80, so the gate would have waved through work it should stop, with no error anywhere. |

Still outstanding, unchanged: the threshold values (`docs/DECISION_TABLE.md` §7) remain POC
proposals awaiting business approval, and the pinned commit SHAs should be re-checked before
any deployment.

---

## 13. What this phase does **not** do

- It does not approve, decline, settle or pay any claim.
- It does not contact any customer.
- It does not turn an AI recommendation into an insurance decision.
- It does not accuse anyone of fraud.
- It does not connect to any real insurance system.
- It does not automatically recover from a terminal state.
- It does not claim assurance above LOW.
- It does not run a static Γ scan, because no such tool exists.

Governance decides whether an automated step may proceed. **It never decides a
claim.**
