import { Field, Select, TextInput } from '../../components/FormControls.jsx'
import { CONTACT_METHODS } from '../claimForm.js'

export default function CustomerStep({ customer, errors, onChange }) {
  const set = (key) => (value) => onChange({ ...customer, [key]: value })

  return (
    <section className="panel" aria-labelledby="customer-heading">
      <h1 id="customer-heading">Your details</h1>
      <p className="lede">
        We use these to find your policy and to keep you updated about your claim.
      </p>

      <Field label="Full name" htmlFor="full_name" error={errors.full_name} required>
        <TextInput
          id="full_name"
          value={customer.full_name}
          onChange={set('full_name')}
          error={errors.full_name}
          autoComplete="name"
        />
      </Field>

      <Field label="Email address" htmlFor="email" error={errors.email} required>
        <TextInput
          id="email"
          type="email"
          value={customer.email}
          onChange={set('email')}
          error={errors.email}
          autoComplete="email"
        />
      </Field>

      <Field label="Phone number" htmlFor="phone" error={errors.phone} required>
        <TextInput
          id="phone"
          type="tel"
          value={customer.phone}
          onChange={set('phone')}
          error={errors.phone}
          autoComplete="tel"
        />
      </Field>

      <Field
        label="Policy number"
        htmlFor="policy_number"
        error={errors.policy_number}
        hint="You will find this on your policy schedule, for example POL-HOME-20117."
        required
      >
        <TextInput
          id="policy_number"
          value={customer.policy_number}
          onChange={set('policy_number')}
          error={errors.policy_number}
          hint="policy"
        />
      </Field>

      <Field
        label="How would you prefer we contact you?"
        htmlFor="preferred_contact_method"
        error={errors.preferred_contact_method}
      >
        <Select
          id="preferred_contact_method"
          value={customer.preferred_contact_method}
          onChange={set('preferred_contact_method')}
          options={CONTACT_METHODS}
        />
      </Field>
    </section>
  )
}
