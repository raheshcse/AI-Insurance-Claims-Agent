# Synthetic Dataset Specification

**Phase 0 — Business & Governance Foundation.**
This defines dataset **structure and sample-data requirements**. The datasets themselves are
generated at the start of Phase 1. No application code is written here.

> **SYNTHETIC DATA ONLY.** Every record is fabricated. No real customer, policy, claim,
> address, phone number, email or document may enter this repository at any phase. Names,
> addresses and identifiers must be obviously invented and must not coincide with real people.
> This is a POC constraint from the requirements document and is not negotiable.

Location: `data/synthetic/`. Format proposal: **JSON Lines** for record sets, **Markdown** for
policy wording. **[POC-PROPOSED — format is not specified by either source document.]**

---

## 1. Dataset map

```
                 ┌──────────────┐
                 │  CUSTOMERS   │  customer_id
                 └──────┬───────┘
                        │ 1
                        │
                        │ n
                 ┌──────▼───────┐        ┌────────────────────┐
                 │   POLICIES   │───────►│  POLICY_WORDINGS   │
                 │  policy_id   │ n    1 │  wording_id        │
                 └──────┬───────┘        │ (Home/Storm KB)    │
                        │ 1              └────────────────────┘
                        │
              ┌─────────┴──────────┐
              │ n                  │ n
       ┌──────▼───────┐    ┌───────▼────────────┐
       │    CLAIMS    │    │ HISTORICAL_CLAIMS  │
       │  claim_id    │    │ historical_claim_id│
       └──────┬───────┘    └────────────────────┘
              │ 1
              │ n
       ┌──────▼───────┐        ┌────────────────────┐
       │  DOCUMENTS   │        │    RISK_RULES      │
       │ document_id  │        │   rule_id          │
       └──────────────┘        │ (reference data)   │
                               └────────────────────┘
```

Five required datasets (Customers, Policies, Claims, Documents, Historical Claims) plus two
supporting reference sets (Policy Wordings, Risk Rules) that the requirements name under
"Knowledge & Data".

---

## 2. Customers

**Purpose.** The policyholder lodging the claim. Provides identity for policy lookup, contact
details for communication, and the vulnerability/accessibility signals the escalation policy
depends on.

| Field | Type | Notes |
| --- | --- | --- |
| `customer_id` | string, `CUST-#####` | Primary key |
| `full_name` | string | Obviously fictional |
| `date_of_birth` | date | Used only for identity matching in the POC |
| `email` | string | `@example.invalid` domain only |
| `phone` | string | Reserved-for-fiction ranges only |
| `address_line_1`, `suburb`, `city`, `postcode` | string | Must match the insured address for a valid claim |
| `preferred_contact_method` | enum `email` \| `phone` \| `portal` | Communication Agent uses it |
| `preferred_language` | string | Default `en-NZ` |
| `accessibility_needs` | string \| null | e.g. "large print", "no phone contact" |
| `vulnerability_flag` | bool | Pre-known vulnerability on the customer record |
| `vulnerability_notes` | string \| null | Non-sensitive operational note only — see §8 |
| `communication_preferences_confirmed` | bool | Consent-style flag |
| `customer_since` | date | Feeds the "new customer" risk indicator |

**Relationships.** 1 → n Policies. 1 → n Claims (through Policies).

**Workflow use.** Intake Agent matches the caller to a customer; Communication Agent chooses the
channel and tone; escalation logic reads `vulnerability_flag` and `accessibility_needs`;
Fraud & Risk Agent reads `customer_since`.

**Sample.**

```json
{"customer_id":"CUST-10042","full_name":"Marama Whitcombe","email":"m.whitcombe@example.invalid",
 "suburb":"Titirangi","city":"Auckland","postcode":"0604","preferred_contact_method":"email",
 "vulnerability_flag":false,"customer_since":"2019-03-14"}
```

**Required coverage:** at least one customer with `vulnerability_flag = true`; at least one with
an accessibility need; at least one very recent `customer_since` (risk indicator); a mix of
contact preferences.

---

## 3. Policies

**Purpose.** The contractual basis for cover. Everything the Policy Agent retrieves and
everything the `policy-in-force` Invariant checks comes from here.

| Field | Type | Notes |
| --- | --- | --- |
| `policy_id` | string, `POL-HOME-#####` | Primary key |
| `customer_id` | FK → Customers | Owner |
| `product_type` | enum | `home` for this POC |
| `policy_status` | enum `active` \| `lapsed` \| `cancelled` \| `pending` | |
| `inception_date`, `expiry_date` | date | **The Invariant compares date of loss to this range** |
| `last_renewal_date` | date | |
| `insured_address_*` | string | Must match the loss address |
| `dwelling_sum_insured` | number NZD | |
| `contents_sum_insured` | number NZD | |
| `standard_excess` | number NZD | Surfaced as context to the customer |
| `storm_excess` | number NZD \| null | Peril-specific excess if any |
| `covered_perils` | array[string] | Must contain `storm` for a valid storm claim |
| `exclusions` | array[object] `{code, summary, wording_ref}` | Drives the `no-auto-approval-under-exclusion` Invariant |
| `conditions` | array[object] `{code, summary, wording_ref}` | e.g. maintenance obligations |
| `optional_covers` | array[string] | e.g. `temporary_accommodation` |
| `wording_id` | FK → Policy Wordings | Which wording version applies |
| `recent_cover_change_date` | date \| null | Feeds the "recent cover increase" risk indicator |

**Relationships.** n → 1 Customer. 1 → n Claims. n → 1 Policy Wording.

**Workflow use.** Policy Agent retrieves coverage, conditions, excess and exclusions as context
(FR-03); the `policy-in-force` Invariant tests `inception_date ≤ date_of_loss ≤ expiry_date` and
`policy_status = active`; the Assessment Agent nets the excess off the estimate; the exclusion
list is what makes cover "ambiguous" in decision row D-09.

**Sample.**

```json
{"policy_id":"POL-HOME-20117","customer_id":"CUST-10042","policy_status":"active",
 "inception_date":"2024-08-01","expiry_date":"2026-08-01","dwelling_sum_insured":750000,
 "standard_excess":500,"storm_excess":1000,"covered_perils":["storm","fire","burglary"],
 "exclusions":[{"code":"EXC-MAINT","summary":"Damage from lack of maintenance or gradual deterioration","wording_ref":"§4.2"}],
 "wording_id":"WORD-HOME-2024A"}
```

**Required coverage:** an active policy with clean cover (Scenario A); a policy **lapsed at the
date of loss** (Invariant D-03); a policy whose exclusions plausibly engage — e.g. pre-existing
roof deterioration (D-09); a policy with a recent cover increase (risk indicator); a policy with
`temporary_accommodation` for the emergency pathway.

---

## 4. Claims

**Purpose.** The live claim record — what the FNOL builds, what the workflow advances, and what
the governance gate protects.

### 4.1 Core fields

| Field | Type | Notes |
| --- | --- | --- |
| `claim_id` | string, `CLM-2026-######` | Primary key; also the customer-facing claim reference **[POC-PROPOSED format]** |
| `policy_id` | FK → Policies | |
| `customer_id` | FK → Customers | Denormalised for convenience |
| `claim_state` | enum | One of the six official states only |
| `internal_status` | enum \| null | The internal statuses in `CLAIM_JOURNEY.md` §4 |
| `created_at`, `updated_at` | timestamp | |
| `submitted_at` | timestamp \| null | Set on the Draft → Submitted transition |

### 4.2 FNOL fields (mandatory unless noted) — this list defines "complete"

| Field | Type | Mandatory |
| --- | --- | --- |
| `date_of_loss` | date | ✔ |
| `time_of_loss` | time | optional |
| `loss_address_*` | string | ✔ |
| `peril` | enum, `storm` for this POC | ✔ |
| `incident_description` | text | ✔ |
| `damaged_items` | array[object] `{area, item, description, estimated_value}` | ✔ (≥ 1) |
| `property_habitable` | bool | ✔ |
| `anyone_injured` | bool | ✔ |
| `damage_ongoing` | bool | ✔ |
| `utilities_affected` | array[string] | ✔ (may be empty) |
| `emergency_repairs_done` | bool | ✔ |
| `temporary_accommodation_needed` | bool | ✔ |
| `third_party_involved` | bool | ✔ |
| `customer_estimated_value` | number NZD \| null | optional — absence triggers the conservative default |
| `photos_supplied` | bool | ✔ |

**[POC-PROPOSED — the mandatory-field list is not specified by either source document and needs
claims-operations approval.]**

### 4.3 Derived / AI fields (recommendations until acted on)

| Field | Type | Produced by |
| --- | --- | --- |
| `classification` | object `{insurance_type, incident_category}` | Assessment Agent (R-04) |
| `complexity_band` | enum `low` \| `medium` \| `high` | Assessment Agent (R-05) |
| `urgency_band` | enum `emergency` \| `high` \| `standard` | Assessment Agent (R-06) |
| `confidence` | float 0–1 | Assessment Agent (R-07) — the PreNode's input |
| `estimated_claim_value` | number NZD | Assessment Agent (R-10) |
| `recommended_route` | enum `automated` \| `human_review` | Assessment Agent (R-08) |
| `risk_level` | enum `low` \| `medium` \| `high` | Fraud & Risk Agent (R-09) |
| `risk_indicators` | array[object] `{rule_id, detail}` | Fraud & Risk Agent — **internal only** |
| `missing_items` | array[string] | Validation Agent (R-03) |
| `validation_issues` | array[object] `{type, detail}` | Validation Agent |
| `ai_summary` | text | Assessment Agent (R-11) |
| `policy_context` | object | Policy Agent (R-02) |

### 4.4 Governance fields

| Field | Type | Notes |
| --- | --- | --- |
| `decision_ids` | array[string] | Every governed decision touching this claim |
| `governance_outcome` | enum `proceed` \| `human_queue` \| `suspended` \| null | Mirrors the gate's return |
| `terminal_state` | string \| null | Set only on an Invariant violation |
| `escalation_reason` | string \| null | Shown in the review queue (FR-08, UI-04) |

### 4.5 Human review fields

`assigned_to`, `review_started_at`, `review_outcome`, `review_notes`,
`human_authorised_transition_id` (links the ledger entry that re-enabled automation).

**Relationships.** n → 1 Policy, n → 1 Customer, 1 → n Documents, 1 → n ledger decision IDs.

**Workflow use.** The claim record is the persisted projection of the LangGraph shared state.
Recommendation fields may be overwritten freely; `claim_state` and governance fields may only
change behind a gate.

**Required coverage:** one claim per demonstration scenario A–D, plus one claim in each of the
six official states, plus one claim missing two mandatory fields, plus one emergency claim, plus
one from a vulnerable customer.

---

## 5. Documents

**Purpose.** Evidence attached to a claim, and the material the upload flow exercises.

| Field | Type | Notes |
| --- | --- | --- |
| `document_id` | string, `DOC-#####` | Primary key |
| `claim_id` | FK → Claims | |
| `document_type` | enum `photo` \| `repair_quote` \| `invoice` \| `police_report` \| `weather_report` \| `other` | |
| `file_name`, `mime_type`, `size_bytes` | | |
| `uploaded_at` | timestamp | |
| `document_date` | date \| null | **Compared with `date_of_loss`** — a document dated before the loss is a risk indicator |
| `description` | text | |
| `required_for_claim_type` | bool | Feeds the completeness check |
| `content_summary` | text \| null | Placeholder; whether documents are analysed by an agent is an open question (§8) |
| `synthetic_placeholder` | bool, always `true` | Explicit marker that no real document is present |

**Relationships.** n → 1 Claim.

**Workflow use.** Validation Agent checks required documents are present; Fraud & Risk Agent
checks date consistency; the UI-02 upload area and UI-06 document list read from here.

**Required coverage:** a claim with complete photo evidence; a claim missing a required repair
quote (D-01); a document dated before the date of loss (risk indicator); an oversized or
unsupported file for the upload-validation path.

---

## 6. Historical claims

**Purpose.** Prior claim history for the customer and the insured property. The Fraud & Risk
Agent's main evidence base.

| Field | Type | Notes |
| --- | --- | --- |
| `historical_claim_id` | string, `HCLM-#####` | Primary key |
| `customer_id` | FK → Customers | |
| `policy_id` | FK → Policies | |
| `claim_date`, `date_of_loss` | date | |
| `peril` | enum | |
| `incident_category` | string | |
| `claim_value` | number NZD | |
| `outcome` | enum `settled` \| `declined` \| `withdrawn` \| `open` | |
| `decline_reason` | string \| null | |
| `fraud_flag_raised` | bool | |
| `days_from_policy_inception` | integer | Derived; feeds the "claim soon after inception" indicator |

**Relationships.** n → 1 Customer, n → 1 Policy.

**Workflow use.** Frequency and pattern checks; repeat-peril detection; prior-decline context for
the employee summary. History informs a risk *indicator*; it never by itself produces a decline.

**Required coverage:** a customer with no history (baseline); a customer with three storm claims
in 24 months (frequency indicator); a customer with a prior declined claim; a claim lodged
within 30 days of inception.

---

## 7. Supporting reference data

### 7.1 Policy wordings — the Home/Storm knowledge base

| Field | Notes |
| --- | --- |
| `wording_id` | e.g. `WORD-HOME-2024A` |
| `version`, `effective_from` | Versioned so retrieval is reproducible |
| `sections` | array of `{ref, heading, body}` — the retrievable chunks |
| `applies_to_perils` | array[string] |

Synthetic wording covering: what storm damage means; what is covered for dwelling, outbuildings,
fences and contents; excess application; maintenance and gradual-deterioration exclusions;
notification conditions; temporary accommodation. Written specifically so that the exclusion in
Scenario D-09 is genuinely arguable rather than a strawman.

**Workflow use.** The Policy Agent's retrieval corpus (FR-03). Every piece of policy context
shown to a customer or an employee must cite a `ref` from here — the LLM does not author policy.

### 7.2 Risk rules

| Field | Notes |
| --- | --- |
| `rule_id` | e.g. `RISK-FREQ-01` |
| `name`, `description` | |
| `severity` | `standard` \| `severe` — feeds the risk banding |
| `signal_source` | which dataset/field the rule reads |
| `customer_visible` | always `false` |

**Workflow use.** The Fraud & Risk Agent evaluates these rules against claim, document and
historical data. Keeping them as data rather than prompt text means they are reviewable,
testable and changeable without touching the model.

---

## 8. Assumptions and open questions

| # | Item | Status |
| --- | --- | --- |
| 1 | JSON Lines for records, Markdown for wordings | **[POC-PROPOSED]** — no format specified |
| 2 | Claim reference format `CLM-2026-######` | **[POC-PROPOSED]** — required by Phase 1, format unspecified |
| 3 | Mandatory FNOL field list (§4.2) | **[POC-PROPOSED]** — defines completeness; needs claims-operations approval |
| 4 | NZD and New Zealand context | **[POC-PROPOSED]** |
| 5 | Whether uploaded documents are **analysed** by an agent or only stored and date-checked | **Open** — not stated in the requirements; affects whether a vision/OCR step exists at all |
| 6 | Volume of synthetic records per dataset | **Open** — proposal: 20 customers, 25 policies, 15 claims, 30 documents, 40 historical claims, enough to be realistic without becoming a data-management task |
| 7 | Whether historical claims cover the *property* as well as the customer | **Open** — property-level history is a stronger risk signal but needs a property key |
| 8 | Vulnerability representation | **Open** — the POC stores an operational flag and a non-sensitive note only. Any real implementation must decide what may lawfully be recorded and who may see it; this is a privacy question for the insurer, not a modelling choice |
| 9 | Whether a separate "weather event" reference dataset is needed to validate date-of-loss claims | **Open** — currently a risk indicator with no backing data |

## 9. Generation rules

1. Generate from an explicit, version-controlled script so datasets are reproducible.
2. Seed the random generator; record the seed.
3. Every record traceably supports at least one decision-table row or scenario — no filler.
4. Cross-dataset referential integrity must hold (every FK resolves).
5. Include the awkward cases deliberately: lapsed policy, engaged exclusion, missing fields,
   back-dated document, claim history cluster, emergency, vulnerable customer, above-authority
   value.
6. No file in `data/synthetic/` may contain anything resembling real personal data.
