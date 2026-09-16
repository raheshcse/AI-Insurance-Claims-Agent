/**
 * Claim review screen. INTERNAL — claims staff only.
 *
 * Laid out to answer the six questions the requirements ask, in order:
 *
 *   1. What the customer reported
 *   2. What the policy information says
 *   3. What the AI agents found
 *   4. What risks were identified
 *   5. Why the claim was escalated
 *   6. What the AI recommends
 *
 * And then, kept visually and structurally apart from all six: what the reviewer
 * decides. The AI's output is a recommendation; the reviewer's action is the
 * decision. The screen never lets those blur together.
 */

import { useCallback, useEffect, useState } from 'react'
import { Alert, Field, Select, TextArea, TextInput } from '../components/FormControls.jsx'
import {
  getClaimReview,
  performReviewAction,
  reEnableAutomation,
} from '../api/client.js'
import EscalationReasons from './EscalationReasons.jsx'
import IntelligenceReport from './IntelligenceReport.jsx'

const ACTION_LABELS = {
  start_review: 'Start review (claim this)',
  request_information: 'Request information from the customer',
  refer_to_specialist: 'Refer to a specialist',
  complete_review: 'Record review complete',
}

const ACTION_EFFECT = {
  start_review: 'Assigns the claim to you. The claim state does not change.',
  request_information: 'Moves the claim to Information Required and closes the queue entry.',
  refer_to_specialist: 'Keeps the claim in Human Review, flagged for a specialist.',
  complete_review:
    'Moves the claim to Approved/Completed. A POC bookkeeping outcome — it does not approve a claim for payment, set a reserve, settle anything or notify the customer.',
}

const yesNo = (value) => (value ? 'Yes' : 'No')

function CustomerReport({ report }) {
  const customer = report?.customer ?? {}
  const property = report?.property ?? {}
  const damage = report?.damage ?? {}
  const address = property.loss_address ?? {}

  return (
    <section className="agent-panel">
      <header className="agent-panel__header">
        <h3>1 · What the customer reported</h3>
        <span className="status-tag">Customer&apos;s own words</span>
      </header>

      <dl className="summary__list summary__list--tight">
        <div className="summary__row">
          <dt>Policyholder</dt>
          <dd>
            {customer.full_name} · {customer.policy_number}
          </dd>
        </div>
        <div className="summary__row">
          <dt>Contact</dt>
          <dd>
            {customer.email} · {customer.phone} · prefers {customer.preferred_contact_method}
          </dd>
        </div>
        <div className="summary__row">
          <dt>Property</dt>
          <dd>
            {address.address_line_1}, {address.suburb}, {address.city} {address.postcode}
          </dd>
        </div>
        <div className="summary__row">
          <dt>Date of loss</dt>
          <dd>
            {damage.date_of_loss} {damage.time_of_loss ?? ''}
          </dd>
        </div>
        <div className="summary__row">
          <dt>What happened</dt>
          <dd>{damage.incident_description}</dd>
        </div>
        <div className="summary__row">
          <dt>Liveable / accommodation</dt>
          <dd>
            {yesNo(property.property_habitable)} / {yesNo(property.temporary_accommodation_needed)}
          </dd>
        </div>
        <div className="summary__row">
          <dt>Injury / ongoing / utilities</dt>
          <dd>
            {yesNo(damage.anyone_injured)} / {yesNo(damage.damage_ongoing)} /{' '}
            {(damage.utilities_affected ?? []).join(', ') || 'none'}
          </dd>
        </div>
        <div className="summary__row">
          <dt>Photos supplied</dt>
          <dd>{yesNo(damage.photos_supplied)}</dd>
        </div>
      </dl>

      <ul className="review-items">
        {(damage.damaged_items ?? []).map((item, index) => (
          <li key={index} className="review-items__item">
            <p className="review-items__heading">
              {item.area} — {item.item}
            </p>
            <p className="review-items__description">{item.description}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ReviewActions({ detail, onDone }) {
  const actions = detail.available_actions ?? []
  const [action, setAction] = useState(actions[0] ?? '')
  const [reviewer, setReviewer] = useState('')
  const [notes, setNotes] = useState('')
  const [requested, setRequested] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    setAction(actions[0] ?? '')
  }, [detail.claim_id, actions.length]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!actions.length) {
    return (
      <section className="decision-panel">
        <h3>Reviewer decision</h3>
        <p className="muted">
          No review actions are available — this claim is not open in the queue.
        </p>
      </section>
    )
  }

  const submit = async () => {
    if (reviewer.trim().length < 2) {
      setError({ message: 'Enter your name so the action is attributable.' })
      return
    }
    setBusy(true)
    setError(null)
    try {
      const response = await performReviewAction(detail.claim_id, {
        action,
        reviewer: reviewer.trim(),
        notes,
        information_requested: requested
          ? requested.split('\n').map((line) => line.trim()).filter(Boolean)
          : [],
      })
      setResult(response)
      onDone?.()
    } catch (apiError) {
      setError({ message: apiError.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="decision-panel">
      <h3>Reviewer decision</h3>
      <p className="decision-panel__boundary">
        Everything above is an AI recommendation. What you record here is the decision.
        These are stored separately and are never treated as the same thing.
      </p>

      {result ? (
        <Alert tone="info" title="Review action recorded">
          <p>
            {ACTION_LABELS[result.action]} — claim moved from{' '}
            <strong>{result.previous_claim_state}</strong> to{' '}
            <strong>{result.claim_state}</strong>, recorded by {result.performed_by}.
          </p>
          <p className="alert__note">{result.poc_note}</p>
        </Alert>
      ) : null}

      {error ? (
        <Alert tone="error" title="The action could not be recorded">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      <Field label="Action" htmlFor="review_action">
        <Select
          id="review_action"
          value={action}
          onChange={setAction}
          options={actions.map((value) => ({
            value,
            label: ACTION_LABELS[value] ?? value,
          }))}
        />
      </Field>

      {action ? <p className="decision-panel__effect">{ACTION_EFFECT[action]}</p> : null}

      <Field
        label="Your name"
        htmlFor="reviewer"
        hint="No authentication in the POC — Phase 6."
      >
        <TextInput id="reviewer" value={reviewer} onChange={setReviewer} hint="reviewer" />
      </Field>

      {action === 'request_information' ? (
        <Field
          label="What are you asking the customer for?"
          htmlFor="information_requested"
          hint="One item per line."
        >
          <TextArea
            id="information_requested"
            rows={3}
            value={requested}
            onChange={setRequested}
            hint="requested"
          />
        </Field>
      ) : null}

      <Field label="Your reasoning" htmlFor="review_notes" hint="Optional, but useful.">
        <TextArea id="review_notes" rows={3} value={notes} onChange={setNotes} hint="notes" />
      </Field>

      <button type="button" className="btn btn--primary" onClick={submit} disabled={busy}>
        {busy ? 'Recording…' : 'Record decision'}
      </button>
    </section>
  )
}

/**
 * What governance decided about this claim, and what it means.
 *
 * A PreNode denial and an Invariant violation are shown differently on purpose:
 * the first rerouted the claim to a person and is an ordinary, expected outcome;
 * the second halted automation and needs a claims authority to lift it. Showing
 * both as "blocked" would hide the only difference a reviewer acts on.
 */
function GovernancePanel({ detail }) {
  const governance = detail.governance ?? detail.intelligence?.governance ?? null
  const suspended = Boolean(detail.automation_suspended)

  if (!governance && !suspended) return null

  return (
    <section className="agent-panel agent-panel--governance">
      <header className="agent-panel__header">
        <h3>Governance (X-Verba / VSL)</h3>
        <span className={`status-tag${suspended ? ' status-tag--deny' : ''}`}>
          {suspended
            ? 'Automation suspended'
            : governance?.permitted
              ? 'Permitted'
              : 'Denied — routed to a person'}
        </span>
      </header>

      {governance ? (
        <dl className="summary__list summary__list--tight">
          <div className="summary__row">
            <dt>Specification</dt>
            <dd>{governance.specification}</dd>
          </div>
          <div className="summary__row">
            <dt>Gate</dt>
            <dd>
              {governance.pre_node}
              {governance.pre_node_denied ? ' — denied' : ' — passed'}
            </dd>
          </div>
          {governance.denial_reason ? (
            <div className="summary__row">
              <dt>Reason</dt>
              <dd>{governance.denial_reason}</dd>
            </div>
          ) : null}
          {governance.invariant_violated ? (
            <div className="summary__row">
              <dt>Invariant violated</dt>
              <dd>{governance.invariant_violated}</dd>
            </div>
          ) : null}
          {governance.terminal_state ? (
            <div className="summary__row">
              <dt>Terminal state</dt>
              <dd>{governance.terminal_state}</dd>
            </div>
          ) : null}
          <div className="summary__row">
            <dt>Confidence / floor</dt>
            <dd>
              {governance.confidence} / {governance.confidence_floor}
            </dd>
          </div>
          <div className="summary__row">
            <dt>Derived assurance</dt>
            <dd>
              {String(governance.assurance_level ?? '').toUpperCase()} — output-layer
              control. The gate blocks a bad action; it does not change how the model
              decides.
            </dd>
          </div>
          <div className="summary__row">
            <dt>Ledger entries</dt>
            <dd>{(governance.ledger_entry_ids ?? []).length} recorded</dd>
          </div>
        </dl>
      ) : null}

      {suspended ? <ReEnablementForm claimId={detail.claim_id} /> : null}
    </section>
  )
}

/**
 * The only exit from a terminal state.
 *
 * Deliberately not a one-click button. The framework requires a root-cause
 * analysis and a specification-update proposal, and refuses to issue the
 * transition without them — so the form asks for exactly that and nothing less.
 */
function ReEnablementForm({ claimId }) {
  const [authorisedBy, setAuthorisedBy] = useState('')
  const [rootCause, setRootCause] = useState('')
  const [proposal, setProposal] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const submit = async () => {
    if (authorisedBy.trim().length < 2) {
      setError({ message: 'Enter your name — re-enablement is attributable to a person.' })
      return
    }
    if (rootCause.trim().length < 20 || proposal.trim().length < 20) {
      setError({
        message:
          'Both the root-cause analysis and the specification-update proposal are required, and must be substantive.',
      })
      return
    }

    setBusy(true)
    setError(null)
    try {
      setResult(
        await reEnableAutomation(claimId, {
          authorised_by: authorisedBy.trim(),
          root_cause_analysis: rootCause.trim(),
          specification_update_proposal: proposal.trim(),
        }),
      )
    } catch (apiError) {
      setError({ message: apiError.message })
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return (
      <Alert tone="info" title="Automation re-enabled for this claim">
        <p>
          Authorised by {result.authorised_by} under {result.authority}. Recorded as
          a human-authorised transition in the ledger.
        </p>
        <p className="alert__note">{result.poc_note}</p>
      </Alert>
    )
  }

  return (
    <div className="decision-panel decision-panel--governance">
      <h4>Re-enable automation</h4>
      <p className="decision-panel__boundary">
        Automation is suspended on this claim and nothing lifts that on its own —
        no timeout, no retry, no confidence score. A claims authority must
        authorise it, with evidence. Re-enabling automation decides nothing about
        the claim; you still hold it.
      </p>

      {error ? (
        <Alert tone="error" title="Automation was not re-enabled">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      <Field
        label="Your name"
        htmlFor="reenable_authorised_by"
        hint="No authentication in the POC — Phase 6."
      >
        <TextInput
          id="reenable_authorised_by"
          value={authorisedBy}
          onChange={setAuthorisedBy}
          hint="authority"
        />
      </Field>

      <Field
        label="Root-cause analysis"
        htmlFor="reenable_root_cause"
        hint="Why was the rule violated? Required by the framework."
      >
        <TextArea
          id="reenable_root_cause"
          rows={3}
          value={rootCause}
          onChange={setRootCause}
          hint="root cause"
        />
      </Field>

      <Field
        label="Specification-update proposal"
        htmlFor="reenable_proposal"
        hint="What should change in the governance specification, and why?"
      >
        <TextArea
          id="reenable_proposal"
          rows={3}
          value={proposal}
          onChange={setProposal}
          hint="proposal"
        />
      </Field>

      <button type="button" className="btn btn--primary" onClick={submit} disabled={busy}>
        {busy ? 'Recording…' : 'Authorise re-enablement'}
      </button>
    </div>
  )
}

export default function ClaimReview({ claimId, onBack }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setDetail(await getClaimReview(claimId))
    } catch (apiError) {
      setDetail(null)
      setError({ message: apiError.message })
    } finally {
      setLoading(false)
    }
  }, [claimId])

  useEffect(() => {
    load()
  }, [load])

  const entry = detail?.queue_entry

  return (
    <section className="panel panel--staff" aria-labelledby="review-heading">
      <button type="button" className="btn btn--link" onClick={onBack}>
        ← Back to the queue
      </button>

      <p className="eyebrow eyebrow--internal">Internal — claims review</p>
      <h1 id="review-heading">Claim {claimId}</h1>

      {loading ? <p className="muted">Loading…</p> : null}

      {error ? (
        <Alert tone="error" title="This claim could not be loaded">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      {detail ? (
        <>
          <div className="review-header">
            <span className="status-pill">{detail.claim_state}</span>
            {detail.internal_status ? (
              <span className="chip chip--internal">{detail.internal_status}</span>
            ) : null}
            {entry?.emergency ? (
              <span className="chip chip--urgent">Emergency pathway</span>
            ) : null}
            {entry?.vulnerable_customer ? (
              <span className="chip chip--support">Vulnerable customer support</span>
            ) : null}
            {detail.automation_suspended ? (
              <span className="chip chip--deny">Automation suspended</span>
            ) : null}
          </div>

          {entry?.emergency ? (
            <Alert tone="warning" title="Emergency pathway">
              <p>
                This claim shows emergency indicators and was routed to the priority queue.
                Contact the customer before routine handling.
              </p>
              <p className="alert__note">
                Placeholder wording — the insurer&apos;s approved emergency guidance replaces
                this.
              </p>
            </Alert>
          ) : null}

          {entry?.vulnerable_customer ? (
            <Alert tone="info" title="Vulnerable customer support">
              <p>
                This customer&apos;s record indicates they need supported handling. Contact
                them by their recorded preference
                {detail.intelligence?.customer_context?.preferred_contact_method
                  ? ` (${detail.intelligence.customer_context.preferred_contact_method})`
                  : ''}
                {detail.intelligence?.customer_context?.accessibility_needs
                  ? `, honouring: ${detail.intelligence.customer_context.accessibility_needs}`
                  : ''}
                . Do not send automated chase-ups.
              </p>
              <p className="alert__note">
                Operational flag only. This POC records no medical or personal information.
              </p>
            </Alert>
          ) : null}

          <GovernancePanel detail={detail} />

          <CustomerReport report={detail.customer_report} />

          <EscalationReasons
            reasons={entry?.reasons ?? detail.intelligence?.routing?.reasons ?? []}
            heading="5 · Why this claim was escalated"
          />

          {detail.intelligence ? (
            <>
              <h2 className="subheading">2–4 &amp; 6 · What the AI found and recommends</h2>
              <IntelligenceReport report={detail.intelligence} />
            </>
          ) : (
            <p className="muted">
              No analysis has been run for this claim yet.
            </p>
          )}

          <ReviewActions detail={detail} onDone={load} />

          <p className="footnote">{detail.decision_authority_note}</p>
        </>
      ) : null}
    </section>
  )
}
