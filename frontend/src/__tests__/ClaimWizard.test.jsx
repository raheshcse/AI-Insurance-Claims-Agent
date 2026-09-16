/**
 * Phase 1 frontend tests — the customer journey.
 *
 * Covers the Phase 1 exit criteria: the customer can navigate the form,
 * required fields are validated, the review page shows what was entered, and a
 * successful submission shows the claim confirmation.
 *
 * The backend is mocked. These tests are about the customer journey, not about
 * HTTP.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import * as client from '../api/client.js'

const YESTERDAY = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)

const CONFIRMATION = {
  claim_id: 'CLM-2026-004217',
  claim_state: 'Submitted',
  internal_status: null,
  submitted_at: '2026-09-13T09:15:00+00:00',
  next_step:
    'Your claim has been lodged. A claims specialist will review the details you provided.',
  summary: {
    policy_number: 'POL-HOME-20117',
    customer_name: 'Marama Whitcombe',
    peril: 'storm',
    date_of_loss: YESTERDAY,
    loss_address: '18 Kauri Point Road, Titirangi, Auckland 0604',
    damaged_item_count: 1,
    customer_estimated_value: 4200,
  },
}

async function fillCustomerStep(user) {
  await user.type(screen.getByLabelText(/full name/i), 'Marama Whitcombe')
  await user.type(screen.getByLabelText(/email address/i), 'm.whitcombe@example.invalid')
  await user.type(screen.getByLabelText(/phone number/i), '+64 20 900 0142')
  await user.type(screen.getByLabelText(/policy number/i), 'POL-HOME-20117')
}

async function fillPropertyStep(user) {
  await user.type(screen.getByLabelText(/street address/i), '18 Kauri Point Road')
  await user.type(screen.getByLabelText(/suburb/i), 'Titirangi')
  await user.type(screen.getByLabelText(/town or city/i), 'Auckland')
  await user.type(screen.getByLabelText(/postcode/i), '0604')
}

async function fillDamageStep(user) {
  await user.type(screen.getByLabelText(/date the damage happened/i), YESTERDAY)
  await user.type(
    screen.getByLabelText(/what happened\?/i),
    'Overnight storm tore tiles off the north side of the roof and water came in.',
  )
  await user.type(screen.getByLabelText(/area of the property/i), 'Roof')
  await user.type(screen.getByLabelText(/what was damaged/i), 'Roof tiles')
  await user.type(
    screen.getByLabelText(/describe the damage/i),
    'Around fifteen tiles lifted and broken on the north slope.',
  )
}

const next = (user, name = /continue/i) =>
  user.click(screen.getByRole('button', { name }))

/**
 * Phase 5 moved the conversational assistant to the default customer view and
 * the six-step form to its own tab. The form journey itself is UNCHANGED, so
 * these tests were not rewritten -- they open the tab and then assert exactly
 * what they always asserted. A journey that still works should still be tested.
 */
async function renderForm(user) {
  render(<App />)
  await user.click(screen.getByRole('button', { name: /^claim form$/i }))
}

describe('claim wizard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('starts on the landing page with a way to begin a claim', async () => {
    const user = userEvent.setup()
    await renderForm(user)
    expect(
      screen.getByRole('heading', { name: /make a storm damage claim/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start a claim/i })).toBeInTheDocument()
  })

  it('lets the customer move through every step of the form', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    expect(screen.getByRole('heading', { name: /your details/i })).toBeInTheDocument()

    await fillCustomerStep(user)
    await next(user)
    expect(screen.getByRole('heading', { name: /the property/i })).toBeInTheDocument()

    await fillPropertyStep(user)
    await next(user)
    expect(screen.getByRole('heading', { name: /the storm damage/i })).toBeInTheDocument()

    await fillDamageStep(user)
    await next(user)
    expect(screen.getByRole('heading', { name: /review your claim/i })).toBeInTheDocument()
  })

  it('blocks progress and explains why when required fields are empty', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await next(user)

    // Still on the customer step.
    expect(screen.getByRole('heading', { name: /your details/i })).toBeInTheDocument()
    expect(screen.getByText('Please enter your full name.')).toBeInTheDocument()
    expect(screen.getByText('Please enter your email address.')).toBeInTheDocument()
    expect(screen.getByText('Please enter your policy number.')).toBeInTheDocument()
  })

  it('rejects an email address that is not an email address', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await user.type(screen.getByLabelText(/full name/i), 'Marama Whitcombe')
    await user.type(screen.getByLabelText(/email address/i), 'not-an-email')
    await user.type(screen.getByLabelText(/phone number/i), '+64 20 900 0142')
    await user.type(screen.getByLabelText(/policy number/i), 'POL-HOME-20117')
    await next(user)

    expect(screen.getByText('Please enter a valid email address.')).toBeInTheDocument()
  })

  it('shows the entered information on the review page', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)
    await next(user)
    await fillDamageStep(user)
    await next(user)

    expect(screen.getByText('Marama Whitcombe')).toBeInTheDocument()
    expect(screen.getByText('POL-HOME-20117')).toBeInTheDocument()
    expect(
      screen.getByText('18 Kauri Point Road, Titirangi, Auckland 0604'),
    ).toBeInTheDocument()
    expect(screen.getByText(/roof tiles/i)).toBeInTheDocument()
  })

  it('lets the customer go back from review and correct an answer', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)
    await next(user)
    await fillDamageStep(user)
    await next(user)

    await user.click(screen.getByRole('button', { name: /change your details/i }))
    expect(screen.getByRole('heading', { name: /your details/i })).toBeInTheDocument()

    const nameField = screen.getByLabelText(/full name/i)
    await user.clear(nameField)
    await user.type(nameField, 'Marama T Whitcombe')

    await next(user)
    await next(user)
    await next(user)

    expect(screen.getByText('Marama T Whitcombe')).toBeInTheDocument()
  })

  it('shows the claim reference, status and summary after a successful submission', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'submitClaim').mockResolvedValue(CONFIRMATION)
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)
    await next(user)
    await fillDamageStep(user)
    await next(user)
    await user.click(screen.getByRole('button', { name: /submit claim/i }))

    expect(
      await screen.findByRole('heading', { name: /your claim has been submitted/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('CLM-2026-004217')).toBeInTheDocument()
    expect(screen.getByText('Submitted')).toBeInTheDocument()
    expect(screen.getByText(/a claims specialist will review/i)).toBeInTheDocument()
  })

  it('sends the FNOL in the shape the API expects', async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(client, 'submitClaim').mockResolvedValue(CONFIRMATION)
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)
    await next(user)
    await fillDamageStep(user)
    await next(user)
    await user.click(screen.getByRole('button', { name: /submit claim/i }))

    const payload = spy.mock.calls[0][0]
    expect(payload.damage.peril).toBe('storm')
    expect(payload.customer.policy_number).toBe('POL-HOME-20117')
    expect(payload.damage.damaged_items).toHaveLength(1)
    // Optional fields the customer left blank are null, not empty strings.
    expect(payload.damage.time_of_loss).toBeNull()
    expect(payload.damage.customer_estimated_value).toBeNull()
  })

  it('shows a customer-safe message when the backend cannot be reached', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'submitClaim').mockRejectedValue(
      new client.ApiError({
        code: 'network_error',
        message:
          'We could not reach our claims service. Your claim has not been submitted.',
      }),
    )
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)
    await next(user)
    await fillDamageStep(user)
    await next(user)
    await user.click(screen.getByRole('button', { name: /submit claim/i }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/could not reach our claims service/i)).toBeInTheDocument()
    // The customer stays on review with their answers intact.
    expect(screen.getByRole('heading', { name: /review your claim/i })).toBeInTheDocument()
    expect(screen.getByText('Marama Whitcombe')).toBeInTheDocument()
  })

  it('shows a safety notice when the answers suggest an urgent situation', async () => {
    const user = userEvent.setup()
    await renderForm(user)

    await user.click(screen.getByRole('button', { name: /start a claim/i }))
    await fillCustomerStep(user)
    await next(user)
    await fillPropertyStep(user)

    // "Can you still live in the property?" -> No
    const habitable = screen.getByRole('group', { name: /can you still live in the property/i })
    await user.click(within(habitable).getByRole('radio', { name: 'No' }))
    await next(user)

    expect(screen.getByText(/if anyone is at risk/i)).toBeInTheDocument()
  })
})
