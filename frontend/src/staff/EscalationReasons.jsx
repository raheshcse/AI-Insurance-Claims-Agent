/**
 * Escalation reasons. INTERNAL — claims staff only.
 *
 * The requirements are explicit that "AI decided to escalate" is not good enough.
 * Each reason therefore shows what fired, what was observed, what it was measured
 * against, and — the distinction that matters most — whether the reason is an
 * **AI finding** or a **business rule**. A reviewer should never have to guess
 * which of those they are looking at.
 */

const BASIS_LABEL = {
  ai_finding: 'AI finding',
  business_rule: 'Business rule',
}

export default function EscalationReasons({ reasons = [], heading = 'Why this was escalated' }) {
  if (!reasons.length) {
    return (
      <p className="muted">
        No escalation reason recorded — no rule fired for this claim.
      </p>
    )
  }

  return (
    <section className="reasons">
      <h3 className="reasons__heading">
        {heading} <span className="reasons__count">{reasons.length}</span>
      </h3>

      <ol className="reasons__list">
        {reasons.map((reason, index) => (
          <li
            key={reason.code}
            className={`reasons__item reasons__item--${reason.priority}`}
          >
            <div className="reasons__header">
              <span className="reasons__rank">{index + 1}</span>
              <p className="reasons__label">{reason.label}</p>
              <span className={`chip chip--basis chip--${reason.basis}`}>
                {BASIS_LABEL[reason.basis] ?? reason.basis}
              </span>
              {reason.priority !== 'standard' ? (
                <span className={`chip chip--priority chip--${reason.priority}`}>
                  {reason.priority}
                </span>
              ) : null}
            </div>

            <p className="reasons__detail">{reason.detail}</p>

            <dl className="reasons__evidence">
              {reason.observed_value ? (
                <>
                  <dt>Observed</dt>
                  <dd>{reason.observed_value}</dd>
                </>
              ) : null}
              {reason.threshold_value ? (
                <>
                  <dt>Compared against</dt>
                  <dd>{reason.threshold_value}</dd>
                </>
              ) : null}
              <dt>Rule</dt>
              <dd className="reasons__rule">{reason.rule_reference}</dd>
              {reason.source_agent ? (
                <>
                  <dt>From</dt>
                  <dd>{reason.source_agent}</dd>
                </>
              ) : null}
            </dl>

            {reason.assumption ? (
              <p className="reasons__assumption">
                <span className="chip chip--assumption">POC assumption</span>{' '}
                {reason.assumption}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  )
}
