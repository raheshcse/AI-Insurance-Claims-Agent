/**
 * Governance dashboard. INTERNAL — claims staff only.
 *
 * The screen has one job: let a person see that governance exists, that it runs,
 * and that it sometimes says no — with the ledger entries behind each claim.
 *
 * Three things it deliberately does NOT do:
 *
 *  1. It does not render a failing audit as a green tick. An open terminal state
 *     fails check 5 by design, and the screen says so in those words.
 *  2. It does not present a skipped check as a passed one. `checks_not_asserted`
 *     gets its own, visibly different treatment.
 *  3. It does not dress up the assurance level. LOW is what VSL derived from the
 *     F1/F2 facts, and LOW is what is shown, with what it means.
 *
 * It is read-only. Lifting a terminal state is a review action taken by a named
 * person on the claim review screen, not a button here.
 */

import { useCallback, useEffect, useState } from 'react'
import { Alert } from '../components/FormControls.jsx'
import { getGovernanceDashboard } from '../api/client.js'

const ENTRY_LABELS = {
  MONITOR: 'Monitor',
  PRE_NODE: 'PreNode',
  VERIFICATION: 'Verification',
  TERMINAL: 'Terminal state',
  SPECIFICATION_UPDATE: 'Specification update',
  HUMAN_AUTHORISED_TRANSITION: 'Human-authorised transition',
  RE_ENABLEMENT: 'Re-enablement',
}

const CHECK_LABELS = {
  no_monitoring_gaps: 'Monitoring is continuous',
  drift_flagged_monitor_has_pre_node: 'Every drift signal reached a gate',
  pre_node_has_verification: 'Every gate decision was verified',
  insufficient_verification_has_specification_update:
    'Every governance failure was registered for review',
  terminal_has_human_authorised_transition:
    'Every terminal state was lifted by a person',
}

function Stat({ label, value, tone }) {
  return (
    <div className={`gov-stat${tone ? ` gov-stat--${tone}` : ''}`}>
      <span className="gov-stat__value">{value}</span>
      <span className="gov-stat__label">{label}</span>
    </div>
  )
}

export default function GovernanceDashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await getGovernanceDashboard({ limit: 100 }))
    } catch (apiError) {
      setData(null)
      setError({ message: apiError.message })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return <p className="muted">Loading the governance record…</p>
  }

  if (error) {
    return (
      <Alert tone="error" title="The governance dashboard could not be loaded">
        <p>{error.message}</p>
        <button type="button" className="btn btn--secondary" onClick={load}>
          Try again
        </button>
      </Alert>
    )
  }

  if (!data) return null

  const { configuration, counts, integrity, audit } = data
  const suspended = data.suspended_claims ?? []
  const denied = data.denied_actions ?? []
  const entries = data.recent_entries ?? []

  return (
    <section className="panel panel--staff" aria-labelledby="governance-heading">
      <p className="eyebrow eyebrow--internal">Internal — claims staff</p>
      <h1 id="governance-heading">Governance</h1>
      <p className="lede">
        X-Verba / VSL enforcement at the points where this system commits to
        something. Governance decides whether an automated step may proceed. It
        never decides a claim.
      </p>

      {/* ---------------------------------------------------------- status */}
      <div className="gov-status">
        <div
          className={`gov-badge gov-badge--${integrity.verified ? 'ok' : 'bad'}`}
        >
          <strong>Ledger integrity</strong>
          <span>{integrity.verified ? 'Chain intact' : 'Chain broken'}</span>
          <small>
            {integrity.entries} entries
            {integrity.checkpoint_sequence !== null
              ? ` · tip #${integrity.checkpoint_sequence}`
              : ''}
          </small>
        </div>

        <div className={`gov-badge gov-badge--${audit.all_passed ? 'ok' : 'warn'}`}>
          <strong>Audit</strong>
          <span>
            {audit.all_passed
              ? `${audit.checks_passed.length} checks passed`
              : `${audit.checks_failed.length} check${
                  audit.checks_failed.length === 1 ? '' : 's'
                } failing`}
          </span>
          <small>
            {audit.certificate_issued
              ? 'VerbaCertificate issued'
              : 'No certificate issued'}
          </small>
        </div>

        <div className="gov-badge gov-badge--neutral">
          <strong>Derived assurance</strong>
          <span>{String(configuration.assurance_level).toUpperCase()}</span>
          <small>output-layer control</small>
        </div>
      </div>

      <p className="footnote">{configuration.assurance_note}</p>

      {/* ----------------------------------------------------------- counts */}
      <h2>What governance did</h2>
      <div className="gov-stats">
        <Stat label="Claims governed" value={counts.claims_seen} />
        <Stat label="Decisions recorded" value={counts.decisions} />
        <Stat label="Ledger entries" value={counts.total_entries} />
        <Stat label="Drift signals" value={counts.drift_flagged} />
        <Stat
          label="Actions denied"
          value={counts.actions_denied}
          tone={counts.actions_denied > 0 ? 'deny' : undefined}
        />
        <Stat label="PreNode denials (rerouted)" value={counts.pre_node_denials} />
        <Stat
          label="Invariant violations (halted)"
          value={counts.invariant_violations}
          tone={counts.invariant_violations > 0 ? 'deny' : undefined}
        />
        <Stat
          label="Terminal states open"
          value={counts.terminal_states_open}
          tone={counts.terminal_states_open > 0 ? 'deny' : undefined}
        />
        <Stat
          label="Human-authorised transitions"
          value={counts.human_authorised_transitions}
        />
      </div>

      {/* ------------------------------------------------------ audit checks */}
      <h2>Audit checks</h2>
      <ul className="gov-checks">
        {audit.checks_passed.map((check) => (
          <li key={check} className="gov-check gov-check--pass">
            <span className="gov-check__state">Pass</span>
            <span>{CHECK_LABELS[check] ?? check}</span>
          </li>
        ))}
        {audit.checks_not_asserted.map((check) => (
          <li key={check} className="gov-check gov-check--unasserted">
            <span className="gov-check__state">Not asserted</span>
            <span>
              {CHECK_LABELS[check] ?? check} — no monitoring-gap threshold was
              given, so this check was skipped rather than tested.
            </span>
          </li>
        ))}
        {audit.checks_failed.map((check) => (
          <li key={check} className="gov-check gov-check--fail">
            <span className="gov-check__state">Fail</span>
            <span>{CHECK_LABELS[check] ?? check}</span>
          </li>
        ))}
      </ul>
      {!audit.all_passed ? (
        <Alert tone="warning" title="The audit is not passing, and that is the point">
          <p>{audit.note}</p>
        </Alert>
      ) : null}

      {/* --------------------------------------------------------- suspended */}
      <h2>Claims with automation suspended</h2>
      {suspended.length === 0 ? (
        <p className="muted">
          No claim currently has automation suspended.
        </p>
      ) : (
        <table className="gov-table">
          <caption className="sr-only">Claims with automation suspended</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Invariant violated</th>
              <th scope="col">Terminal state</th>
              <th scope="col">Way out</th>
            </tr>
          </thead>
          <tbody>
            {suspended.map((item) => (
              <tr key={item.claim_id}>
                <td>{item.claim_id}</td>
                <td>{item.invariant}</td>
                <td>{item.terminal_state}</td>
                <td>A claims authority must authorise the transition</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ----------------------------------------------------- denied actions */}
      <h2>Actions governance stopped</h2>
      {denied.length === 0 ? (
        <p className="muted">
          Nothing has been denied yet. That is a fact about the traffic so far, not
          evidence that the gates work — the tests are what demonstrate that.
        </p>
      ) : (
        <ul className="gov-denials">
          {denied.map((action) => (
            <li
              key={action.entry_id}
              className={`gov-denial gov-denial--${action.gate_kind}`}
            >
              <div className="gov-denial__head">
                <span className="gov-denial__gate">{action.gate}</span>
                <span className="gov-denial__kind">
                  {action.gate_kind === 'invariant'
                    ? 'Invariant — automation halted'
                    : 'PreNode — rerouted to a person'}
                </span>
              </div>
              <p className="gov-denial__claim">{action.claim_id}</p>
              {action.reason ? <p>{action.reason}</p> : null}
              {action.fallback ? (
                <p className="muted">Fallback: {action.fallback}</p>
              ) : null}
              {action.terminal_state ? (
                <p className="muted">Terminal state: {action.terminal_state}</p>
              ) : null}
              <p className="footnote">{action.recorded_at}</p>
            </li>
          ))}
        </ul>
      )}

      {/* ----------------------------------------------------- configuration */}
      <h2>What is enforced</h2>
      <p className="muted">
        {configuration.specification} ·{' '}
        {configuration.specification_active ? 'active' : 'not active'} · approved
        by {configuration.governance_authority}
      </p>
      <ul className="gov-constructs">
        {configuration.pre_nodes.map((gate) => (
          <li key={gate.name} className="gov-construct gov-construct--soft">
            <strong>{gate.name}</strong>
            <span className="gov-construct__kind">PreNode — soft gate</span>
            <p>{gate.description}</p>
            <p className="muted">
              Γ threshold {gate.gamma_threshold} · confidence floor{' '}
              {configuration.effective_confidence_floor} · fallback {gate.fallback}
            </p>
          </li>
        ))}
        {configuration.invariants.map((rule) => (
          <li key={rule.name} className="gov-construct gov-construct--hard">
            <strong>{rule.name}</strong>
            <span className="gov-construct__kind">Invariant — hard rule</span>
            <p>{rule.description}</p>
            <p className="muted">On violation: {rule.on_violation}</p>
          </li>
        ))}
      </ul>
      <p className="footnote">{configuration.threshold_note}</p>

      {/* ----------------------------------------------------------- ledger */}
      <h2>Ledger events</h2>
      <p className="muted">
        Newest first. Every entry records what caused it, so the chain can be read
        back as a causal trail rather than a timeline that happens to be ordered.
      </p>
      <table className="gov-table gov-table--ledger">
        <caption className="sr-only">Recent VerbaLedger entries</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Event</th>
            <th scope="col">Claim</th>
            <th scope="col">Recorded</th>
            <th scope="col">Caused by</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.entry_id}>
              <td>{entry.sequence}</td>
              <td>{ENTRY_LABELS[entry.entry_type] ?? entry.entry_type}</td>
              <td>{entry.claim_id ?? '—'}</td>
              <td>{entry.recorded_at}</td>
              <td className="gov-table__hash">
                {entry.caused_by ? entry.caused_by.slice(0, 8) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="footnote">{data.boundary_note}</p>
      <p className="footnote">
        This view is read-only. Lifting a terminal state is a review action taken
        by a named person on the claim, not a control on this screen.
      </p>
      <p className="footnote">
        No authentication protects this view in the POC. Access control for claims
        staff is Phase 6.
      </p>
    </section>
  )
}
