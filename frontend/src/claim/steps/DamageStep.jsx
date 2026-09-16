import {
  Alert,
  CheckboxGroup,
  Field,
  TextArea,
  TextInput,
  YesNo,
} from '../../components/FormControls.jsx'
import { UTILITY_OPTIONS, emptyDamagedItem } from '../claimForm.js'

export default function DamageStep({ damage, errors, onChange, showSafetyNotice }) {
  const set = (key) => (value) => onChange({ ...damage, [key]: value })

  const updateItem = (index, key, value) => {
    const items = damage.damaged_items.map((item, i) =>
      i === index ? { ...item, [key]: value } : item,
    )
    onChange({ ...damage, damaged_items: items })
  }

  const addItem = () =>
    onChange({ ...damage, damaged_items: [...damage.damaged_items, emptyDamagedItem()] })

  const removeItem = (index) =>
    onChange({
      ...damage,
      damaged_items: damage.damaged_items.filter((_, i) => i !== index),
    })

  const toggleUtility = (value) => {
    const selected = damage.utilities_affected.includes(value)
      ? damage.utilities_affected.filter((v) => v !== value)
      : [...damage.utilities_affected, value]
    onChange({ ...damage, utilities_affected: selected })
  }

  const itemErrors = errors.damaged_items ?? []

  return (
    <section className="panel" aria-labelledby="damage-heading">
      <h1 id="damage-heading">The storm damage</h1>
      <p className="lede">
        Tell us when the storm damage happened and what it affected. The more specific
        you can be, the faster we can deal with your claim.
      </p>

      {showSafetyNotice ? (
        <Alert tone="warning" title="If anyone is at risk, get help first">
          <p>
            From what you have told us, this may be an urgent situation. If anyone is hurt
            or the property is unsafe, contact emergency services, then call our claims
            line. You can still finish lodging this claim afterwards.
          </p>
          <p className="alert__note">
            Placeholder wording — the insurer's approved emergency guidance replaces this.
          </p>
        </Alert>
      ) : null}

      <div className="grid grid--two">
        <Field
          label="Date the damage happened"
          htmlFor="date_of_loss"
          error={errors.date_of_loss}
          required
        >
          <TextInput
            id="date_of_loss"
            type="date"
            value={damage.date_of_loss}
            onChange={set('date_of_loss')}
            error={errors.date_of_loss}
          />
        </Field>

        <Field
          label="Approximate time"
          htmlFor="time_of_loss"
          hint="Optional — if you know it."
        >
          <TextInput
            id="time_of_loss"
            type="time"
            value={damage.time_of_loss}
            onChange={set('time_of_loss')}
          />
        </Field>
      </div>

      <Field
        label="What happened?"
        htmlFor="incident_description"
        error={errors.incident_description}
        hint="Describe the storm and the damage it caused in your own words."
        required
      >
        <TextArea
          id="incident_description"
          value={damage.incident_description}
          onChange={set('incident_description')}
          error={errors.incident_description}
          hint="describe"
        />
      </Field>

      <h2 className="subheading">What was damaged?</h2>
      <p className="field__hint">
        Add each damaged part of the property separately. You need at least one.
      </p>

      {damage.damaged_items.map((item, index) => (
        <div className="item-card" key={index}>
          <div className="item-card__header">
            <h3 className="item-card__title">Damaged item {index + 1}</h3>
            {damage.damaged_items.length > 1 ? (
              <button
                type="button"
                className="btn btn--link"
                onClick={() => removeItem(index)}
              >
                Remove
              </button>
            ) : null}
          </div>

          <div className="grid grid--two">
            <Field
              label="Area of the property"
              htmlFor={`item-${index}-area`}
              error={itemErrors[index]?.area}
              hint="For example: roof, kitchen, garden"
              required
            >
              <TextInput
                id={`item-${index}-area`}
                value={item.area}
                onChange={(value) => updateItem(index, 'area', value)}
                error={itemErrors[index]?.area}
              />
            </Field>

            <Field
              label="What was damaged"
              htmlFor={`item-${index}-item`}
              error={itemErrors[index]?.item}
              hint="For example: roof tiles, fence, window"
              required
            >
              <TextInput
                id={`item-${index}-item`}
                value={item.item}
                onChange={(value) => updateItem(index, 'item', value)}
                error={itemErrors[index]?.item}
              />
            </Field>
          </div>

          <Field
            label="Describe the damage"
            htmlFor={`item-${index}-description`}
            error={itemErrors[index]?.description}
            required
          >
            <TextArea
              id={`item-${index}-description`}
              rows={3}
              value={item.description}
              onChange={(value) => updateItem(index, 'description', value)}
              error={itemErrors[index]?.description}
            />
          </Field>

          <Field
            label="Your estimate of the cost (NZD)"
            htmlFor={`item-${index}-estimated_value`}
            error={itemErrors[index]?.estimated_value}
            hint="Optional — a rough figure is fine."
          >
            <TextInput
              id={`item-${index}-estimated_value`}
              type="number"
              min="0"
              value={item.estimated_value}
              onChange={(value) => updateItem(index, 'estimated_value', value)}
              error={itemErrors[index]?.estimated_value}
            />
          </Field>
        </div>
      ))}

      <button type="button" className="btn btn--secondary" onClick={addItem}>
        Add another damaged item
      </button>

      <h2 className="subheading">A few more questions</h2>

      <YesNo
        id="damage_ongoing"
        legend="Is the damage still happening or getting worse?"
        value={damage.damage_ongoing}
        onChange={set('damage_ongoing')}
      />

      <YesNo
        id="anyone_injured"
        legend="Was anyone hurt?"
        value={damage.anyone_injured}
        onChange={set('anyone_injured')}
      />

      <CheckboxGroup
        legend="Are any of these affected?"
        hint="Leave all unticked if none are affected."
        options={UTILITY_OPTIONS}
        selected={damage.utilities_affected}
        onToggle={toggleUtility}
      />

      <YesNo
        id="emergency_repairs_done"
        legend="Have any emergency or make-safe repairs already been done?"
        value={damage.emergency_repairs_done}
        onChange={set('emergency_repairs_done')}
      />

      <YesNo
        id="third_party_involved"
        legend="Was anyone else's property damaged, or was anyone else involved?"
        value={damage.third_party_involved}
        onChange={set('third_party_involved')}
      />

      <YesNo
        id="photos_supplied"
        legend="Do you have photos of the damage?"
        value={damage.photos_supplied}
        onChange={set('photos_supplied')}
        hint="You can send photos after lodging your claim — uploading them here is coming soon."
      />

      <Field
        label="Your overall estimate of the claim (NZD)"
        htmlFor="customer_estimated_value"
        error={errors.customer_estimated_value}
        hint="Optional. If you are not sure, leave it blank."
      >
        <TextInput
          id="customer_estimated_value"
          type="number"
          min="0"
          value={damage.customer_estimated_value}
          onChange={set('customer_estimated_value')}
          error={errors.customer_estimated_value}
          hint="estimate"
        />
      </Field>
    </section>
  )
}
