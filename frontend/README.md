# frontend/ — Customer claims experience

**Status: Phase 3 implemented.** React + Vite. Two separated experiences: the customer-facing
storm-damage FNOL journey, and an internal claims console with the AI analysis, the human
review queue and a claim review screen.

## Run it

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The backend must be running on <http://127.0.0.1:8000> (see `../backend/README.md`). To point at
a different API, set `VITE_API_BASE_URL` in a `.env` file here or at the project root.

```powershell
npm test             # vitest, 38 tests
npm run build        # production build into dist/
```

## The journey

```
Start  →  Your details  →  Property  →  Storm damage  →  Review  →  Confirmation
```

A progress indicator appears from step 2. Back is available throughout, and the Review screen has
a *Change …* link for every section. Submitting re-validates all three data steps, so a value
edited from Review cannot slip through.

## Layout

```
src/
├── App.jsx                      shell — masthead, main, footer
├── main.jsx                     entry point
├── styles.css                   hand-written stylesheet, no UI framework
├── api/client.js                the only place the UI talks to the backend
├── claim/
│   ├── ClaimWizard.jsx          step state machine, validation gating, submission
│   ├── claimForm.js             form shape, API payload mapping, emergency-signal helper
│   ├── validation.js            client-side rules, mirroring the backend
│   └── steps/                   Start, Customer, Property, Damage, Review, Confirmation
├── staff/                       INTERNAL — claims staff only
│   ├── StaffConsole.jsx         tabs: analyse a claim · review queue
│   ├── IntelligenceReport.jsx   routing decision, agent panels, risk indicators, trace
│   ├── EscalationReasons.jsx    each reason with its evidence and AI/rule basis
│   ├── ReviewQueue.jsx          priority-ordered queue with filters and counts
│   └── ClaimReview.jsx          the six reviewer questions, then the decision panel
├── components/
│   ├── FormControls.jsx         Field, TextInput, TextArea, Select, YesNo, CheckboxGroup, Alert
│   └── ProgressSteps.jsx        step indicator
└── __tests__/                   vitest + testing-library
```

## The two views

`App.jsx` switches between them. The customer portal is the default and shows **nothing**
internal: no risk indicators, no policy interpretation, no confidence scores. A test asserts
that internal content is absent from the customer view.

The claims console has its own folder, its own visual treatment and an "Internal view — claims
staff" banner. In Phase 2 the separation is architectural, not enforced — there is no
authentication, and the view switch is a demonstration affordance. That is stated on screen
rather than assumed away. Phase 6 adds identity and access management.

Tests sit beside the code they cover rather than in the project-root `tests/`, which is the
convention Vitest and Testing Library expect. Backend tests do live in `../tests/backend/`.

## Rules this layer follows

- **The UI never calls a model or a data store directly.** Everything goes through the FastAPI
  backend — the boundary that lets Phase 4 add a governance gate without the frontend changing.
- **Client-side validation is a courtesy, not a control.** The backend validates every
  submission independently.
- **`human_queue` must render as a real review state** when Phase 4 arrives. A soft-gate denial
  reroutes; it is never swallowed or shown as an error.
- **Risk indicators never appear in customer-facing content.** Nor do escalation reasons,
  vulnerability flags or policy interpretation. A test asserts it.
- **An AI recommendation and a human decision are never presented as the same thing.** The
  claim review screen puts the reviewer's decision panel in its own bordered section, below
  everything the AI produced, and says so in words.

## Screens still to build

| Screen | Phase |
| --- | --- |
| UI-01 *Check Existing Claim* — the API endpoint exists, the screen does not | 1 follow-up / 2 |
| Document upload — the FNOL records whether photos exist; it does not accept files | 2 |
| UI-03 Claim Assessment | **done** — the claims console report |
| UI-04 Human Review Queue | **done** — the claims console queue tab |
| UI-05 Governance Dashboard | 4 |
| UI-06 Claim Detail | **mostly done** — the claim review screen; governance events await Phase 4 |

Screen definitions: [`../docs/PROJECT_PLAN.md`](../docs/PROJECT_PLAN.md) §9.

## A note on the emergency notice

When the answers suggest an urgent situation — injury, ongoing damage, an uninhabitable property,
utilities out — the damage step shows a safety notice. It is **display only**: it does not route,
prioritise or classify anything, because Phase 1 has no routing engine. Its wording is a
placeholder and must be replaced with the insurer's approved emergency guidance before any
demonstration to customers. See `../docs/HUMAN_ESCALATION_POLICY.md` §4.
