# backend/ — API, application and orchestration layer

**Status: Phase 3 implemented.** FastAPI claims API, a LangGraph multi-agent claims
intelligence workflow, risk-based routing and a human review queue. No governance runtime —
that is Phase 4.

## Run it

```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

- API: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>
- Reference: [`../docs/API.md`](../docs/API.md)

Configuration comes from the environment — copy `.env.example` to `.env` at the
project root (`Copy-Item .env.example .env`). Every setting has a working default,
so the API runs without one.

## Endpoints

| Method | Path | Phase | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/health` | 1 | Liveness |
| `POST` | `/api/claims` | 1 | Lodge a storm-damage FNOL → state `Submitted` |
| `GET` | `/api/claims/{claim_id}` | 1 | Read a lodged claim |
| `POST` | `/api/claims/{claim_id}/analyze` | 2 | Run the claims intelligence workflow (**internal**) |
| `GET` | `/api/claims/{claim_id}/analysis` | 2 | Read the stored result (**internal**) |
| `GET` | `/api/review-queue` | 3 | Claims awaiting human review (**internal**) |
| `GET` | `/api/review-queue/{claim_id}` | 3 | Everything a reviewer needs (**internal**) |
| `POST` | `/api/review-queue/{claim_id}/action` | 3 | Record a POC review action (**internal**) |

## Layout

```
backend/app/
├── main.py                          app, CORS, exception handlers
├── config.py                        environment-driven settings
├── errors.py                        customer-safe error hierarchy
├── api/
│   ├── health.py                    health router
│   ├── claims.py                    claims router
│   └── dependencies.py              wiring — the one place the repository is chosen
├── schemas/claim.py                 request and response models
├── domain/
│   ├── claim_state.py               ClaimState, InternalStatus, ALLOWED_TRANSITIONS
│   └── reference.py                 claim reference generation
├── domain/thresholds.py             POC-proposed business thresholds (move to governance/ in Phase 4)
├── services/
│   ├── claim_service.py             the single claim-creation call site
│   └── intelligence_service.py      runs the workflow, stores the result
├── repositories/
│   ├── claim_repository.py          Protocol + in-memory + JSONL
│   ├── analysis_repository.py       separate store, so analysis cannot mutate a claim
│   └── reference_data.py            the synthetic datasets the agents read
└── schemas/intelligence.py          the claims intelligence result

backend/agents/     Intake, Policy, Validation, Assessment, Fraud & Risk + shared contracts
backend/graph/      StateGraph: shared state, node wrappers, escalation node, finalize
backend/routing/    Phase 3: escalation rule catalogue, router, routing contracts
backend/llm/        Provider boundary: protocol, deterministic stub, HTTP provider, factory
```

Also under `app/`: `schemas/review.py`, `repositories/review_queue_repository.py`,
`services/review_service.py`, `api/review.py`.

## Design rules

- **Model logic, application logic and governance stay separated.** Nothing here may embed
  governance policy; that lives in `governance/` from Phase 4 and is applied via the
  VSL-LangGraph adapter.
- **Agents produce recommendations.** Converting a recommendation into an action is a governed
  commitment behind a gate.
- **The LLM is not the business authority.** Policy retrieval, validation rules and human review
  determine outcomes.
- **LLM access will be provider-independent.** OpenAI first, behind a swappable interface.
- **Governed side effects sit immediately after their gate**, never before.
- **Customers never see an exception.** Every error is translated in `main.py` into a stable code
  and a plain-language message.

## The multi-agent workflow

Five agents run as nodes in a LangGraph `StateGraph` over shared state, with exactly two
conditional branches — each justified by a Phase 0 decision row (D-03 no cover basis, D-01
information outstanding). The output is a **recommendation**: no claim state changes, no
customer is contacted, nothing is approved, declined or settled.

Three properties every agent has: it returns a contract not free text; it cannot raise (a failure
becomes a result that points at a person); and it narrates through the LLM boundary only after
its structured result exists.

**The LLM contributes narrative only.** Every value a decision turns on is rule-derived from the
Phase 0 decision table. A test proves it: with a broken LLM, every band and recommendation is
unchanged. The default provider is a deterministic offline stub, so the POC runs with no API key.

## Where the governance gates go

| Seam | Commitment point |
| --- | --- |
| `services/claim_service.py :: submit_claim` | CP-02, CP-09 — immediately before `repository.save(...)` |
| `graph/nodes.py :: agent_node` | CP-05, CP-07, CP-08 — where `gated_node` wraps a node |
| `services/intelligence_service.py :: analyse` | Before the analysis is stored |
| `graph/escalation.py :: escalation_node` | CP-11 — where `gated_node` wraps the routing decision |
| `services/review_service.py :: apply_routing` | CP-09 (claim-state write), CP-12 (queue placement) |
| `services/review_service.py :: perform_action` | CP-09 |

There is **no governance check of any kind** yet — not even a passing placeholder. A stub that
always returns "allowed" would be a false claim of governance, which
[`../docs/GOVERNANCE_POLICY_CATALOGUE.md`](../docs/GOVERNANCE_POLICY_CATALOGUE.md) rules out.
Comments mark the insertion points, and nothing more.

## Risk routing (Phase 3)

Twelve escalation rules, each traceable to a Phase 0 decision row, decide whether a claim
continues on the automated path, needs a person, or needs something from the customer.
Every applicable rule fires; the outcome comes from the first match in Phase 0 precedence
order; the priority is the strongest across all of them. Full catalogue:
[`../docs/ROUTING_MODEL.md`](../docs/ROUTING_MODEL.md).

Routing applies the claim-state transition — this is where Human Review stops being a
label. It can only ever move a claim to a state where a **person or the customer** holds
it; Approved/Completed is reachable only by a reviewer's own action.

Every failure path escalates. There is no route through the module where something going
wrong produces "automated path".

See [`../docs/PROJECT_PLAN.md`](../docs/PROJECT_PLAN.md) §10, §11, §21, §22 and §23.
