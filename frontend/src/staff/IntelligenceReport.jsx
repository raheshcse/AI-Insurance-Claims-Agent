/**
 * The claims intelligence report. INTERNAL — claims staff only.
 *
 * Two presentation rules carry real weight here, both from the Phase 0 docs:
 *
 *  1. The recommendation/action boundary is stated at the top, not buried. A
 *     reader must not be able to mistake this page for a decision.
 *  2. Risk indicators are shown as prompts to review and are marked
 *     employee-only. They never appear in any customer-facing view.
 *
 * Findings that rest on a POC-proposed threshold render an "assumption" chip, so
 * an unapproved number can never be read as an insurer rule.
 */

import EscalationReasons from './EscalationReasons.jsx'

const money = (value) =>
  value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat('en-NZ', {
        style: 'currency',
        currency: 'NZD',
        maximumFractionDigits: 0,
      }).format(Number(value))

const titleise = (value) =>
  String(value ?? '')
    .replace(/_/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase())

const OUTCOME_TONE = {
  AUTOMATED_PATH_RECOMMENDED: 'ok',
  INFORMATION_REQUIRED: 'attention',
  HUMAN_REVIEW_REQUIRED: 'concern',
}

const STEP_TONE = {
  standard_processing_candidate: 'ok',
  information_required: 'attention',
  manual_review_recommended: 'attention',
  specialist_review_recommended: 'concern',
}

function Band({ label, value, tone = 'neutral' }) {
  return (
    <div className={`band band--${tone}`}>
      <span className="band__label">{label}</span>
      <span className="band__value">{titleise(value) || '—'}</span>
    </div>
  )
}

function FindingList({ findings }) {
  if (!findings?.length) return <p className="muted">No findings recorded.</p>
  return (
    <ul className="findings">
      {findings.map((finding, index) => (
        <li key={`${finding.code}-${index}`} className={`findings__item findings__item--${finding.severity}`}>
          <p className="findings__summary">
            {finding.summary}
            {finding.assumption ? (
              <span className="chip chip--assumption" title={finding.assumption}>
                POC assumption
              </span>
            ) : null}
          </p>
          {finding.detail ? <p className="findings__detail">{finding.detail}</p> : null}
          {finding.data_reference ? (
            <p className="findings__ref">Source: {finding.data_reference}</p>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

/**
 * The CP-13 decision for one agent's LLM call.
 *
 * Two facts, kept separate on purpose, because conflating them is exactly the
 * failure mode this refactor removed:
 *
 *   VSL Governance   PERMITTED / DENIED   — what the gate decided
 *   LLM Call         EXECUTED / BLOCKED   — whether the provider was reached
 *
 * BLOCKED means no request was built and no key was read. It does not mean
 * "called and then ignored" — that state does not exist in this architecture.
 */
function NarrationGovernance({ governance }) {
  if (!governance) return null

  const permitted = governance.permitted === true
  const called = governance.llm_called === true

  return (
    <div className={`llm-gov llm-gov--${permitted ? 'permit' : 'deny'}`}>
      <div className="llm-gov__row">
        <span className="llm-gov__label">VSL governance</span>
        <span className={`llm-gov__verdict llm-gov__verdict--${permitted ? 'permit' : 'deny'}`}>
          {permitted ? 'PERMITTED' : 'DENIED'}
        </span>
        <span className="llm-gov__label">LLM call</span>
        <span className={`llm-gov__verdict llm-gov__verdict--${called ? 'permit' : 'deny'}`}>
          {called ? 'EXECUTED' : 'BLOCKED'}
        </span>
      </div>
      <p className="llm-gov__meta">
        {governance.gate}
        {governance.provider ? ` · provider: ${governance.provider}` : ''}
        {governance.model ? ` · model: ${governance.model}` : ''}
        {governance.degraded !== undefined
          ? ` · degraded: ${governance.degraded ? 'true' : 'false'}`
          : ''}
        {/* WHY it degraded. A fixed reason code, safe to display: it is never
            derived from a response body, a URL or a credential. "degraded: true"
            on its own is what makes a local misconfiguration look like a model
            problem, which is the confusion this line removes. */}
        {governance.degraded && governance.degraded_reason
          ? ` · reason: ${governance.degraded_reason}`
          : ''}
      </p>
      {!called ? (
        <p className="llm-gov__reason">
          {governance.invariant_violated
            ? `Invariant "${governance.invariant_violated}" — `
            : ''}
          {governance.reason ?? 'The gate denied this call.'}
          {governance.terminal_state
            ? ` Terminal state: ${governance.terminal_state}.`
            : ''}
          {' '}The provider was never contacted: no request was built and no key was read.
        </p>
      ) : null}
    </div>
  )
}

function AgentPanel({ title, result, children }) {
  if (!result) return null
  return (
    <section className="agent-panel">
      <header className="agent-panel__header">
        <h3>{title}</h3>
        <span className={`status-tag status-tag--${result.status}`}>{titleise(result.status)}</span>
      </header>

      <NarrationGovernance governance={result.narration_governance} />

      {result.narrative ? (
        <p className="agent-panel__narrative">
          {result.narrative}
          {result.narrative_source ? (
            <span className="agent-panel__source"> — {result.narrative_source}</span>
          ) : null}
        </p>
      ) : null}

      {children}

      <p className="agent-panel__recommendation">
        <strong>Recommends:</strong> {result.recommendation}
      </p>

      {result.confidence ? (
        <p className="agent-panel__confidence">
          Confidence {(result.confidence.value * 100).toFixed(0)}% — {result.confidence.basis}
        </p>
      ) : null}

      <FindingList findings={result.findings} />
    </section>
  )
}

export default function IntelligenceReport({ report }) {
  const {
    claim_id,
    claim_state,
    claim_summary,
    agent_results = {},
    policy_assessment,
    validation_result,
    damage_assessment,
    risk_assessment,
    recommended_next_step,
    recommendation_summary,
    recommendation_reasons = [],
    overall_confidence,
    recommended_claim_state,
    routing,
    governance,
    governance_gate,
    claim_state_changed,
    degraded,
    trace = [],
    llm_provider,
    llm_model,
    llm_degraded,
    llm_governance,
    analysed_at,
  } = report

  const tone = routing
    ? OUTCOME_TONE[routing.outcome] ?? 'neutral'
    : STEP_TONE[recommended_next_step] ?? 'neutral'
  const policyFacts = policy_assessment?.facts
  const policyView = policy_assessment?.interpretation

  return (
    <div className="report">
      <div className="report__boundary" role="note">
        <strong>Analysis only.</strong> Nothing below has been acted on. No claim has been
        approved, declined, settled or progressed, no claim state has changed, and no
        customer has been contacted.
      </div>

      <header className="report__header">
        <div>
          <p className="eyebrow">Claims intelligence</p>
          <h2>{claim_id}</h2>
          <p className="muted">
            {claim_summary?.customer_name} · {claim_summary?.policy_number} ·{' '}
            {claim_summary?.loss_address}
          </p>
        </div>
        <div className="report__state">
          <span className="status-pill">{claim_state}</span>
          <span className="muted">
            {claim_state_changed
              ? 'moved here by the routing decision'
              : 'unchanged by this analysis'}
          </span>
        </div>
      </header>

      {degraded ? (
        <div className="alert alert--warning" role="status">
          <p className="alert__title">Analysis incomplete</p>
          <p>
            Part of the workflow did not complete. Treat the absence of findings as unknown,
            not as a clear result.
          </p>
        </div>
      ) : null}

      <section className={`recommendation recommendation--${tone}`}>
        <p className="recommendation__label">
          {routing ? 'Routing decision' : 'Recommended next step'}
        </p>
        <p className="recommendation__value">
          {titleise(routing ? routing.outcome : recommended_next_step)}
        </p>
        <p className="recommendation__summary">{recommendation_summary}</p>
        {routing ? (
          <p className="recommendation__authority">
            <strong>Business routing</strong> — decided by business rules, not by the
            model, and not by governance
            {routing.review_type ? ` · ${titleise(routing.review_type)}` : ''}
            {routing.priority !== 'standard' ? ` · ${routing.priority} priority` : ''}
          </p>
        ) : null}
        {recommendation_reasons.length ? (
          <ul className="recommendation__reasons">
            {recommendation_reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        ) : null}
        <div className="recommendation__meta">
          {overall_confidence ? (
            <span>
              Overall confidence {(overall_confidence.value * 100).toFixed(0)}%
              {overall_confidence.clears_poc_threshold === false
                ? ' — below the POC-proposed floor'
                : ''}
            </span>
          ) : null}
          {recommended_claim_state ? (
            <span>Suggested state: {recommended_claim_state} (not applied)</span>
          ) : null}
        </div>
      </section>

      <div className="bands">
        <Band label="Complexity" value={damage_assessment?.complexity_band} tone="neutral" />
        <Band label="Urgency" value={damage_assessment?.urgency_band} tone="neutral" />
        <Band label="Value band" value={damage_assessment?.value_band} tone="neutral" />
        <Band label="Risk signal" value={risk_assessment?.risk_level} tone="neutral" />
      </div>

      {/* Three separate verdicts, never merged. An LLM permission is not an
          action permission, and business routing is not governance at all. */}
      {governance ? (
        <section
          className={`governance-strip governance-strip--${
            governance.automated_action_allowed ? 'permitted' : 'denied'
          }`}
          aria-label="Automated action governance"
        >
          <p className="governance-strip__label">
            Automated action governance (CP-14) — X-Verba / VSL
          </p>
          <p className="governance-strip__value">
            {governance.automated_action_allowed
              ? 'PERMITTED — the automated claim action was allowed to proceed'
              : governance.action === 'suspended'
                ? `DENIED — automation suspended (Invariant "${governance.invariant_violated}")`
                : governance.action === 'action_denied'
                  ? `DENIED — this claim may not be handled automatically (Invariant "${governance.invariant_violated}")`
                  : 'DENIED — routed to a person instead'}
          </p>
          <p className="governance-strip__meta">
            Automated action:{' '}
            <strong>{governance.side_effect_performed ? 'EXECUTED' : 'BLOCKED'}</strong>
            {governance.observed_value !== null && governance.observed_value !== undefined
              ? ` · observed ${money(governance.observed_value)}`
              : ''}
            {governance.threshold_value
              ? ` against a limit of ${money(governance.threshold_value)}`
              : ''}
          </p>
          <p className="governance-strip__meta">
            {governance.specification} · derived assurance{' '}
            {String(governance.assurance_level ?? '').toUpperCase()} (output-layer control)
            {governance.ledger_entry_ids?.length
              ? ` · ${governance.ledger_entry_ids.length} VerbaLedger entries`
              : ''}
          </p>
          {!governance.automated_action_allowed && !governance.automated_action_attempted ? (
            <p className="governance-strip__meta">
              Business routing had already selected a non-automated path, so governance
              and the business rules agree. Nothing is suspended — the claim goes to a
              person.
            </p>
          ) : null}
          {governance.terminal_state ? (
            <p className="governance-strip__meta">
              Terminal state: {governance.terminal_state}. The layer above attempted an
              action the policy prohibits, so automation is suspended until a claims
              authority re-enables it.
            </p>
          ) : null}
          <p className="governance-strip__note">
            Governance decides whether an automated step may proceed. It never decides a
            claim. Business routing decides where the claim goes; this decides whether the
            system may handle it without a person.
          </p>
        </section>
      ) : governance_gate ? (
        <section
          className={`governance-strip governance-strip--${
            governance_gate.outcome === 'denied' ? 'denied' : 'permitted'
          }`}
          aria-label="Workflow governance gate"
        >
          <p className="governance-strip__label">Workflow gate (CP-11) — PN-01</p>
          <p className="governance-strip__value">
            {governance_gate.outcome === 'denied'
              ? 'DENIED at the workflow gate — the automated branch was not taken'
              : 'Permitted at the workflow gate'}
          </p>
          <p className="governance-strip__meta">
            confidence {governance_gate.confidence} against a floor of{' '}
            {governance_gate.confidence_floor} · derived assurance{' '}
            {String(governance_gate.assurance_level ?? '').toUpperCase()}
          </p>
        </section>
      ) : null}

      {llm_governance?.governed_calls ? (
        <section
          className={`governance-strip governance-strip--${
            llm_governance.blocked > 0 ? 'denied' : 'permitted'
          }`}
          aria-label="LLM commitment governance"
        >
          <p className="governance-strip__label">
            LLM calls (CP-13) — governed before the provider
          </p>
          <p className="governance-strip__value">
            {llm_governance.permitted} permitted · {llm_governance.blocked} blocked
            {llm_governance.blocked > 0 ? ' — those calls were never made' : ''}
          </p>
          {llm_governance.invariants_violated?.length ? (
            <p className="governance-strip__meta">
              Invariant(s): {llm_governance.invariants_violated.join(', ')}
              {llm_governance.terminal_states?.length
                ? ` · terminal state: ${llm_governance.terminal_states.join(', ')}`
                : ''}
            </p>
          ) : null}
          <p className="governance-strip__note">{llm_governance.note}</p>
        </section>
      ) : null}

      {routing?.reasons?.length ? (
        <EscalationReasons reasons={routing.reasons} />
      ) : null}

      <AgentPanel title="Intake" result={agent_results.intake} />

      <AgentPanel title="Policy" result={agent_results.policy}>
        {policyFacts ? (
          <dl className="summary__list summary__list--tight">
            <div className="summary__row">
              <dt>Policy facts</dt>
              <dd>
                {policyFacts.policy_id} · {policyFacts.policy_status} ·{' '}
                {policyFacts.inception_date} to {policyFacts.expiry_date}
              </dd>
            </div>
            <div className="summary__row">
              <dt>Sums insured</dt>
              <dd>
                Dwelling {money(policyFacts.dwelling_sum_insured)} · contents{' '}
                {money(policyFacts.contents_sum_insured)}
              </dd>
            </div>
            <div className="summary__row">
              <dt>Applicable excess</dt>
              <dd>{money(policyView?.applicable_excess)}</dd>
            </div>
            <div className="summary__row">
              <dt>Cover certainty</dt>
              <dd>{titleise(policyView?.cover_certainty)}</dd>
            </div>
            {policyView?.relevant_wording_refs?.length ? (
              <div className="summary__row">
                <dt>Wording referenced</dt>
                <dd>{policyView.relevant_wording_refs.join(', ')}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
        {policyView?.caveat ? <p className="caveat">{policyView.caveat}</p> : null}
      </AgentPanel>

      <AgentPanel title="Validation" result={agent_results.validation}>
        {validation_result ? (
          <dl className="summary__list summary__list--tight">
            <div className="summary__row">
              <dt>Status</dt>
              <dd>{titleise(validation_result.validation_status)}</dd>
            </div>
            {validation_result.missing_information?.length ? (
              <div className="summary__row">
                <dt>Outstanding</dt>
                <dd>{validation_result.missing_information.join('; ')}</dd>
              </div>
            ) : null}
            {validation_result.inconsistencies?.length ? (
              <div className="summary__row">
                <dt>Inconsistencies</dt>
                <dd>{validation_result.inconsistencies.join('; ')}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </AgentPanel>

      <AgentPanel title="Assessment" result={agent_results.assessment}>
        {damage_assessment ? (
          <dl className="summary__list summary__list--tight">
            <div className="summary__row">
              <dt>Category</dt>
              <dd>{titleise(damage_assessment.incident_category)}</dd>
            </div>
            <div className="summary__row">
              <dt>Estimated value</dt>
              <dd>
                {money(damage_assessment.estimated_claim_value)} — {damage_assessment.estimate_basis}
              </dd>
            </div>
            {damage_assessment.net_of_excess_estimate !== null &&
            damage_assessment.net_of_excess_estimate !== undefined ? (
              <div className="summary__row">
                <dt>Net of excess</dt>
                <dd>{money(damage_assessment.net_of_excess_estimate)}</dd>
              </div>
            ) : null}
            {damage_assessment.complexity_factors?.length ? (
              <div className="summary__row">
                <dt>Complexity factors</dt>
                <dd>{damage_assessment.complexity_factors.join('; ')}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </AgentPanel>

      <AgentPanel title="Fraud &amp; risk" result={agent_results.fraud_risk}>
        {risk_assessment ? (
          <>
            <p className="caveat caveat--strong">{risk_assessment.framing_note}</p>
            {risk_assessment.indicators?.length ? (
              <ul className="indicators">
                {risk_assessment.indicators.map((indicator) => (
                  <li key={indicator.rule_id} className={`indicators__item indicators__item--${indicator.severity}`}>
                    <p className="indicators__name">
                      {indicator.name}
                      <span className="chip chip--internal">Employee only</span>
                    </p>
                    <p className="indicators__detail">{indicator.detail}</p>
                    <p className="findings__ref">Source: {indicator.data_reference}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">
                No risk indicators triggered across{' '}
                {risk_assessment.historical_claims_considered} historical claim(s).
              </p>
            )}
          </>
        ) : null}
      </AgentPanel>

      <details className="trace">
        <summary>Workflow trace ({trace.length} steps)</summary>
        <table className="trace__table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Status</th>
              <th>Next step</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {trace.map((entry, index) => (
              <tr key={index}>
                <td>{entry.agent}</td>
                <td>{entry.status}</td>
                <td>{entry.next_step ?? '—'}</td>
                <td>{entry.duration_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">
          Analysed {analysed_at ? new Date(analysed_at).toLocaleString('en-NZ') : '—'} ·
          narration provider: {llm_provider ?? 'unknown'}
          {llm_model ? ` · model: ${llm_model}` : ''}
        </p>
        {/* Naming the provider without saying whether it answered would let a
            reader assume the model wrote prose the fallback actually composed. */}
        {llm_degraded ? (
          <p className="muted">
            The model was configured but did not answer. This narrative was composed
            deterministically instead. No band, reason or routing outcome is affected —
            every value a decision turns on is rule-derived, not model-derived.
          </p>
        ) : null}
        <p className="muted">
          This is an execution trace, not a governance audit trail. The hash-chained
          VerbaLedger is separate — see the Governance tab.
        </p>
      </details>
    </div>
  )
}
