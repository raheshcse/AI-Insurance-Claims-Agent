/**
 * Client-side validation.
 *
 * This mirrors the backend rules so the customer gets an immediate, friendly
 * message -- it does NOT replace them. The backend validates every submission
 * independently; a browser is not a trust boundary.
 *
 * Deliberately simple: required fields, formats, and "clearly incomplete".
 * Anything that needs judgement -- consistency, completeness against a policy,
 * plausibility -- is the Validation Agent's job in Phase 2.
 */

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MIN_DESCRIPTION_LENGTH = 20

const required = (value) => (value ?? '').toString().trim().length > 0

export function validateCustomer(customer) {
  const errors = {}
  if (!required(customer.full_name)) errors.full_name = 'Please enter your full name.'
  if (!required(customer.email)) {
    errors.email = 'Please enter your email address.'
  } else if (!EMAIL_PATTERN.test(customer.email.trim())) {
    errors.email = 'Please enter a valid email address.'
  }
  if (!required(customer.phone)) {
    errors.phone = 'Please enter a contact phone number.'
  } else if (customer.phone.trim().length < 6) {
    errors.phone = 'Please enter a complete phone number.'
  }
  if (!required(customer.policy_number)) {
    errors.policy_number = 'Please enter your policy number.'
  } else if (customer.policy_number.trim().length < 4) {
    errors.policy_number = 'A policy number is at least 4 characters.'
  }
  return errors
}

export function validateProperty(property) {
  const errors = {}
  const address = property.loss_address
  if (!required(address.address_line_1)) errors.address_line_1 = 'Please enter the street address.'
  if (!required(address.suburb)) errors.suburb = 'Please enter the suburb.'
  if (!required(address.city)) errors.city = 'Please enter the town or city.'
  if (!required(address.postcode)) {
    errors.postcode = 'Please enter the postcode.'
  } else if (address.postcode.trim().length < 3) {
    errors.postcode = 'Please enter a complete postcode.'
  }
  return errors
}

export function validateDamage(damage, today = new Date()) {
  const errors = {}

  if (!required(damage.date_of_loss)) {
    errors.date_of_loss = 'Please tell us when the damage happened.'
  } else {
    const lossDate = new Date(`${damage.date_of_loss}T00:00:00`)
    const endOfToday = new Date(today)
    endOfToday.setHours(23, 59, 59, 999)
    if (Number.isNaN(lossDate.getTime())) {
      errors.date_of_loss = 'Please enter a valid date.'
    } else if (lossDate > endOfToday) {
      errors.date_of_loss = 'The date of loss cannot be in the future.'
    }
  }

  if (!required(damage.incident_description)) {
    errors.incident_description = 'Please describe what happened.'
  } else if (damage.incident_description.trim().length < MIN_DESCRIPTION_LENGTH) {
    errors.incident_description = `Please give us a little more detail (at least ${MIN_DESCRIPTION_LENGTH} characters).`
  }

  const itemErrors = damage.damaged_items.map((item) => {
    const itemError = {}
    if (!required(item.area)) itemError.area = 'Which part of the property?'
    if (!required(item.item)) itemError.item = 'What was damaged?'
    if (!required(item.description)) itemError.description = 'Please describe the damage.'
    if (item.estimated_value !== '' && Number(item.estimated_value) < 0) {
      itemError.estimated_value = 'An estimate cannot be negative.'
    }
    return itemError
  })
  if (itemErrors.some((item) => Object.keys(item).length > 0)) {
    errors.damaged_items = itemErrors
  }

  if (damage.customer_estimated_value !== '' && Number(damage.customer_estimated_value) < 0) {
    errors.customer_estimated_value = 'An estimate cannot be negative.'
  }

  return errors
}

export function hasErrors(errors) {
  return Object.keys(errors).length > 0
}

export function validateStep(stepId, claim) {
  switch (stepId) {
    case 'customer':
      return validateCustomer(claim.customer)
    case 'property':
      return validateProperty(claim.property)
    case 'damage':
      return validateDamage(claim.damage)
    default:
      return {}
  }
}
