# data/ — Synthetic insurance data

**Status: reserved. Datasets to be generated as part of Phase 0/1.**

**Synthetic data only.** No real customer, policy or claim data enters this repository at any
phase.

## `synthetic/` — planned datasets

| Dataset | Contents | Used by |
| --- | --- | --- |
| Customers | Policyholder records, including at least one vulnerable-customer case | Intake Agent, escalation paths |
| Policies | Home insurance policies: coverage, conditions, excess, exclusions | Policy Agent |
| Claims | In-flight claims across Draft / Submitted / Information Required / Assessment / Human Review / Approved-Completed | Whole workflow |
| Documents | Placeholder claim documents and photos | Document upload flow |
| Historical claims | Prior claim history | Fraud & Risk Agent |
| Policy knowledge base | Home / Storm damage policy content for retrieval | Policy Agent |
| Risk rules | Risk indicator definitions | Fraud & Risk Agent |

## Coverage the data must support

The datasets must be rich enough to drive all four demonstration scenarios:

- **A** — a straightforward storm claim with complete information and low risk.
- **B** — a claim with deliberately missing or ambiguous information (low confidence).
- **C** — a claim whose proposed action breaches a non-negotiable rule, e.g. exceeding the
  automated authority threshold.
- **D** — a claim with inconsistent or unusual risk indicators.

Record schemas and file formats are an open Phase 0 item — see `docs/PROJECT_PLAN.md` §14 and
§20.
