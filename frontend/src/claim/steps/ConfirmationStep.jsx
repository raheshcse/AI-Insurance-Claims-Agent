const money = (value) =>
  value === null || value === undefined
    ? 'Not provided'
    : new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(
        Number(value),
      )

export default function ConfirmationStep({ result, onStartAnother }) {
  const { claim_id, claim_state, submitted_at, next_step, summary } = result

  return (
    <section className="panel panel--confirmation" aria-labelledby="confirmation-heading">
      <div className="confirmation__badge" aria-hidden="true">
        ✓
      </div>
      <h1 id="confirmation-heading">Your claim has been submitted</h1>
      <p className="lede">
        Thank you. We have everything we need to get started, and we have sent a
        confirmation to {summary.customer_name.split(' ')[0]}'s preferred contact.
      </p>

      <div className="claim-reference">
        <p className="claim-reference__label">Your claim reference</p>
        <p className="claim-reference__value">{claim_id}</p>
        <p className="claim-reference__hint">
          Please quote this if you contact us about your claim.
        </p>
      </div>

      <div className="status-row">
        <span className="status-pill">{claim_state}</span>
        <span className="status-row__time">
          Lodged {new Date(submitted_at).toLocaleString('en-NZ')}
        </span>
      </div>

      <h2 className="subheading">What happens next</h2>
      <p>{next_step}</p>

      <h2 className="subheading">Claim summary</h2>
      <dl className="summary__list">
        <div className="summary__row">
          <dt>Policy number</dt>
          <dd>{summary.policy_number}</dd>
        </div>
        <div className="summary__row">
          <dt>Policyholder</dt>
          <dd>{summary.customer_name}</dd>
        </div>
        <div className="summary__row">
          <dt>What happened</dt>
          <dd>Storm damage</dd>
        </div>
        <div className="summary__row">
          <dt>Date of damage</dt>
          <dd>{summary.date_of_loss}</dd>
        </div>
        <div className="summary__row">
          <dt>Property</dt>
          <dd>{summary.loss_address}</dd>
        </div>
        <div className="summary__row">
          <dt>Damaged items</dt>
          <dd>{summary.damaged_item_count}</dd>
        </div>
        <div className="summary__row">
          <dt>Your estimate</dt>
          <dd>{money(summary.customer_estimated_value)}</dd>
        </div>
      </dl>

      <div className="actions">
        <button type="button" className="btn btn--secondary" onClick={onStartAnother}>
          Start another claim
        </button>
      </div>
    </section>
  )
}
