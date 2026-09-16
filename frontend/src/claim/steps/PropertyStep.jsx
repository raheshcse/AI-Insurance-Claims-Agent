import { Field, TextInput, YesNo } from '../../components/FormControls.jsx'

export default function PropertyStep({ property, errors, onChange }) {
  const setAddress = (key) => (value) =>
    onChange({
      ...property,
      loss_address: { ...property.loss_address, [key]: value },
    })

  const set = (key) => (value) => onChange({ ...property, [key]: value })

  return (
    <section className="panel" aria-labelledby="property-heading">
      <h1 id="property-heading">The property</h1>
      <p className="lede">Tell us which property the storm damaged.</p>

      <Field
        label="Street address"
        htmlFor="address_line_1"
        error={errors.address_line_1}
        required
      >
        <TextInput
          id="address_line_1"
          value={property.loss_address.address_line_1}
          onChange={setAddress('address_line_1')}
          error={errors.address_line_1}
          autoComplete="address-line1"
        />
      </Field>

      <div className="grid grid--two">
        <Field label="Suburb" htmlFor="suburb" error={errors.suburb} required>
          <TextInput
            id="suburb"
            value={property.loss_address.suburb}
            onChange={setAddress('suburb')}
            error={errors.suburb}
          />
        </Field>

        <Field label="Town or city" htmlFor="city" error={errors.city} required>
          <TextInput
            id="city"
            value={property.loss_address.city}
            onChange={setAddress('city')}
            error={errors.city}
            autoComplete="address-level2"
          />
        </Field>
      </div>

      <Field label="Postcode" htmlFor="postcode" error={errors.postcode} required>
        <TextInput
          id="postcode"
          value={property.loss_address.postcode}
          onChange={setAddress('postcode')}
          error={errors.postcode}
          autoComplete="postal-code"
          inputMode="numeric"
        />
      </Field>

      <YesNo
        id="property_habitable"
        legend="Can you still live in the property?"
        value={property.property_habitable}
        onChange={set('property_habitable')}
      />

      <YesNo
        id="temporary_accommodation_needed"
        legend="Do you need temporary accommodation?"
        value={property.temporary_accommodation_needed}
        onChange={set('temporary_accommodation_needed')}
        hint="Let us know if you need somewhere to stay while repairs are arranged."
      />
    </section>
  )
}
