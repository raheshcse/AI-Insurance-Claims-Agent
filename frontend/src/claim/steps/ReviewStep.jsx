import { Alert } from '../../components/FormControls.jsx'

const yesNo = (value) => (value ? 'Yes' : 'No')

const money = (value) =>
  value === '' || value === null || value === undefined
    ? 'Not provided'
    : new Intl.NumberFormat('en-NZ', { style: 'currency', currency: 'NZD' }).format(
        Number(value),
      )

const orDash = (value) => (value === '' || value == null ? '—' : value)

function SummarySection({ title, onEdit, editLabel, children }) {
  return (
    <section className="summary">
      <div className="summary__header">
        <h2 className="summary__title">{title}</h2>
        <button type="button" className="btn btn--link" onClick={onEdit}>
          {editLabel}
        </button>
      </div>
      <dl className="summary__list">{children}</dl>
    </section>
  )
}

function Row({ label, value }) {
  return (
    <div className="summary__row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export default function ReviewStep({ claim, onEditStep, submitError }) {
  const { customer, property, damage } = claim
  const address = property.loss_address

  return (
    <section className="panel" aria-labelledby="review-heading">
      <h1 id="review-heading">Review your claim</h1>
      <p className="lede">
        Please check everything below. You can go back and change anything before you
        submit — once submitted, you will need to contact us to make changes.
      </p>

      {submitError ? (
        <Alert tone="error" title="We could not lodge your claim">
          <p>{submitError.message}</p>
          {submitError.fields ? (
            <ul className="alert__fields">
              {Object.entries(submitError.fields).map(([field, message]) => (
                <li key={field}>
                  <strong>{field}</strong>: {message}
                </li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}

      <SummarySection
        title="Your details"
        editLabel="Change your details"
        onEdit={() => onEditStep('customer')}
      >
        <Row label="Full name" value={customer.full_name} />
        <Row label="Email" value={customer.email} />
        <Row label="Phone" value={customer.phone} />
        <Row label="Policy number" value={customer.policy_number} />
        <Row label="Preferred contact" value={customer.preferred_contact_method} />
      </SummarySection>

      <SummarySection
        title="The property"
        editLabel="Change property details"
        onEdit={() => onEditStep('property')}
      >
        <Row
          label="Address"
          value={`${address.address_line_1}, ${address.suburb}, ${address.city} ${address.postcode}`}
        />
        <Row label="Still liveable" value={yesNo(property.property_habitable)} />
        <Row
          label="Temporary accommodation needed"
          value={yesNo(property.temporary_accommodation_needed)}
        />
      </SummarySection>

      <SummarySection
        title="The storm damage"
        editLabel="Change damage details"
        onEdit={() => onEditStep('damage')}
      >
        <Row label="Date of damage" value={damage.date_of_loss} />
        <Row label="Time" value={orDash(damage.time_of_loss)} />
        <Row label="What happened" value={damage.incident_description} />
        <Row label="Damage still happening" value={yesNo(damage.damage_ongoing)} />
        <Row label="Anyone hurt" value={yesNo(damage.anyone_injured)} />
        <Row
          label="Utilities affected"
          value={
            damage.utilities_affected.length ? damage.utilities_affected.join(', ') : 'None'
          }
        />
        <Row label="Emergency repairs done" value={yesNo(damage.emergency_repairs_done)} />
        <Row label="Third party involved" value={yesNo(damage.third_party_involved)} />
        <Row label="Photos available" value={yesNo(damage.photos_supplied)} />
        <Row label="Your overall estimate" value={money(damage.customer_estimated_value)} />
      </SummarySection>

      <section className="summary">
        <div className="summary__header">
          <h2 className="summary__title">Damaged items ({damage.damaged_items.length})</h2>
          <button type="button" className="btn btn--link" onClick={() => onEditStep('damage')}>
            Change damaged items
          </button>
        </div>
        <ul className="review-items">
          {damage.damaged_items.map((item, index) => (
            <li key={index} className="review-items__item">
              <p className="review-items__heading">
                {item.area} — {item.item}
              </p>
              <p className="review-items__description">{item.description}</p>
              <p className="review-items__value">Your estimate: {money(item.estimated_value)}</p>
            </li>
          ))}
        </ul>
      </section>

      <Alert tone="info" title="Before you submit">
        <p>
          By submitting, you confirm the information you have given is true and complete as
          far as you know.
        </p>
      </Alert>
    </section>
  )
}
