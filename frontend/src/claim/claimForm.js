/**
 * The shape of the FNOL the customer fills in.
 *
 * Fields and their mandatory/optional status come from
 * docs/SYNTHETIC_DATA_SPEC.md section 4.2 -- the Phase 0 definition of a
 * complete FNOL. No field is added here that Phase 0 did not define.
 */

export const STEPS = [
  { id: 'start', label: 'Start' },
  { id: 'customer', label: 'Your details' },
  { id: 'property', label: 'Property' },
  { id: 'damage', label: 'Storm damage' },
  { id: 'review', label: 'Review' },
]

export const UTILITY_OPTIONS = [
  { value: 'power', label: 'Power' },
  { value: 'water', label: 'Water' },
  { value: 'heating', label: 'Heating' },
  { value: 'sanitation', label: 'Sanitation' },
]

export const CONTACT_METHODS = [
  { value: 'email', label: 'Email' },
  { value: 'phone', label: 'Phone' },
  { value: 'portal', label: 'This portal' },
]

export function emptyDamagedItem() {
  return { area: '', item: '', description: '', estimated_value: '' }
}

export function createEmptyClaim() {
  return {
    customer: {
      full_name: '',
      email: '',
      phone: '',
      policy_number: '',
      preferred_contact_method: 'email',
    },
    property: {
      loss_address: {
        address_line_1: '',
        suburb: '',
        city: '',
        postcode: '',
      },
      property_habitable: true,
      temporary_accommodation_needed: false,
    },
    damage: {
      date_of_loss: '',
      time_of_loss: '',
      peril: 'storm',
      incident_description: '',
      damaged_items: [emptyDamagedItem()],
      damage_ongoing: false,
      anyone_injured: false,
      utilities_affected: [],
      emergency_repairs_done: false,
      third_party_involved: false,
      photos_supplied: false,
      customer_estimated_value: '',
    },
  }
}

/**
 * Convert the form state into the API payload.
 * Empty optional values become null rather than empty strings, because the API
 * models them as nullable, not as blank.
 */
export function toSubmissionPayload(claim) {
  const optionalNumber = (value) =>
    value === '' || value === null || value === undefined ? null : Number(value)

  return {
    customer: { ...claim.customer },
    property: {
      loss_address: { ...claim.property.loss_address },
      property_habitable: claim.property.property_habitable,
      temporary_accommodation_needed: claim.property.temporary_accommodation_needed,
    },
    damage: {
      date_of_loss: claim.damage.date_of_loss,
      time_of_loss: claim.damage.time_of_loss === '' ? null : claim.damage.time_of_loss,
      peril: 'storm',
      incident_description: claim.damage.incident_description,
      damaged_items: claim.damage.damaged_items.map((item) => ({
        area: item.area,
        item: item.item,
        description: item.description,
        estimated_value: optionalNumber(item.estimated_value),
      })),
      damage_ongoing: claim.damage.damage_ongoing,
      anyone_injured: claim.damage.anyone_injured,
      utilities_affected: claim.damage.utilities_affected,
      emergency_repairs_done: claim.damage.emergency_repairs_done,
      third_party_involved: claim.damage.third_party_involved,
      photos_supplied: claim.damage.photos_supplied,
      customer_estimated_value: optionalNumber(claim.damage.customer_estimated_value),
    },
  }
}

/**
 * Signals that Phase 0's escalation policy treats as an emergency
 * (docs/HUMAN_ESCALATION_POLICY.md section 4.1).
 *
 * Phase 1 has no routing engine, so this ONLY drives an on-screen safety notice.
 * It does not classify, score or route the claim -- that is Phase 3.
 */
export function hasEmergencySignal(claim) {
  const { anyone_injured, damage_ongoing, utilities_affected } = claim.damage
  return Boolean(
    anyone_injured ||
      damage_ongoing ||
      claim.property.property_habitable === false ||
      utilities_affected.length > 0,
  )
}
