/**
 * Phase 5 frontend tests — the conversational claims assistant.
 *
 * What these are about: the customer's experience, and the two properties that
 * make it safe to ship.
 *
 *   1. Nothing is submitted until the customer presses Submit.
 *   2. No governance vocabulary reaches a customer.
 *
 * The backend is mocked. These are about the interface, not about HTTP — the
 * backend suite covers the governed call.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import * as client from '../api/client.js'

const AUTHORITY_NOTE =
  'This assistant collects the information needed to report a claim. It does ' +
  'not approve, decline or settle a claim — a claims specialist decides that.'

const OPENING =
  "Hello! I'm your insurance claims assistant. Tell me what happened, and " +
  "I'll help you report it."

function conversation(overrides = {}) {
  return {
    conversation_id: 'CNV-000000000001',
    claim_id: null,
    current_stage: 'start',
    collected_information: [],
    missing_information: [
      { field: 'full_name', label: 'Name', question: 'Could I start with your full name?' },
      { field: 'policy_number', label: 'Policy number', question: 'What is your policy number?' },
    ],
    uncertain_information: [],
    claim_ready: false,
    customer_confirmed: false,
    collected_count: 0,
    required_count: 18,
    messages: [{ role: 'assistant', text: OPENING, at: '2026-09-15T09:00:00+00:00' }],
    assistant_authority_note: AUTHORITY_NOTE,
    ...overrides,
  }
}

/** A conversation with everything collected — the confirmation step. */
function readyConversation() {
  return conversation({
    current_stage: 'ready_for_confirmation',
    claim_ready: true,
    collected_count: 18,
    missing_information: [],
    collected_information: [
      { field: 'full_name', label: 'Name', value: 'Marama Whitcombe' },
      { field: 'policy_number', label: 'Policy number', value: 'POL-HOME-20117' },
      { field: 'date_of_loss', label: 'Date of loss', value: '2026-09-14' },
      { field: 'damaged_areas', label: 'Damaged areas', value: 'Roof, Ceiling' },
      { field: 'estimated_damage_value', label: 'Estimated damage', value: 'NZD 7,500' },
      { field: 'property_habitable', label: 'Safe to live in', value: 'Yes' },
    ],
    messages: [
      { role: 'assistant', text: OPENING, at: '2026-09-15T09:00:00+00:00' },
      { role: 'customer', text: 'A storm damaged my roof.', at: '2026-09-15T09:01:00+00:00' },
      {
        role: 'assistant',
        text: 'I think I have everything I need. Here is what I will submit.\n\nCLAIM SUMMARY\n\nName: Marama Whitcombe\nPolicy number: POL-HOME-20117\nEstimated damage: NZD 7,500\n\nWould you like me to submit this claim with these details?',
        at: '2026-09-15T09:02:00+00:00',
      },
    ],
  })
}

const openAssistant = async () => {
  render(<App />)
  expect(await screen.findByText(OPENING)).toBeInTheDocument()
}

const say = async (user, text) => {
  await user.type(screen.getByLabelText(/your message/i), text)
  await user.click(screen.getByRole('button', { name: /^send$/i }))
}

describe('claims assistant', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: OPENING,
      conversation: conversation(),
    })
  })

  it('is the default customer experience', async () => {
    await openAssistant()

    expect(
      screen.getByRole('region', { name: /ai insurance claims assistant/i }),
    ).toBeInTheDocument()
    // The form is still available — Phase 5 added a journey, it did not delete one.
    expect(screen.getByRole('button', { name: /^claim form$/i })).toBeInTheDocument()
  })

  it('opens with a message inviting the customer to speak first', async () => {
    await openAssistant()

    expect(screen.getByText(OPENING)).toBeInTheDocument()
    expect(screen.getByLabelText(/your message/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /submit this claim/i })).not.toBeInTheDocument()
  })

  it('sends what the customer typed and shows the reply', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'sendAssistantMessage').mockResolvedValue({
      reply: 'Thank you. What is your policy number?',
      conversation: conversation({
        collected_count: 1,
        collected_information: [
          { field: 'full_name', label: 'Name', value: 'Marama Whitcombe' },
        ],
        messages: [
          ...conversation().messages,
          { role: 'customer', text: 'Marama Whitcombe', at: '2026-09-15T09:01:00+00:00' },
          {
            role: 'assistant',
            text: 'Thank you. What is your policy number?',
            at: '2026-09-15T09:01:01+00:00',
          },
        ],
      }),
    })
    await openAssistant()

    await say(user, 'Marama Whitcombe')

    expect(client.sendAssistantMessage).toHaveBeenCalledWith(
      'CNV-000000000001',
      'Marama Whitcombe',
    )
    expect(
      await screen.findByText(/thank you\. what is your policy number\?/i),
    ).toBeInTheDocument()
  })

  it('shows what has been collected and what is still needed', async () => {
    await openAssistant()

    const panel = screen.getByRole('complementary', { name: /claim details so far/i })
    expect(within(panel).getByText(/nothing recorded yet/i)).toBeInTheDocument()
    expect(within(panel).getByText(/still to come/i)).toBeInTheDocument()
    expect(within(panel).getByText('Policy number')).toBeInTheDocument()
  })

  it('distinguishes "we have not asked" from "we could not use what you said"', async () => {
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: OPENING,
      conversation: conversation({
        uncertain_information: [
          {
            field: 'date_of_loss',
            label: 'Date of loss',
            said: 'sometime last week',
            why: 'I could not pin that down to a specific date.',
          },
        ],
      }),
    })
    await openAssistant()

    const panel = screen.getByRole('complementary', { name: /claim details so far/i })
    expect(within(panel).getByText(/we need to check/i)).toBeInTheDocument()
    expect(within(panel).getByText(/sometime last week/i)).toBeInTheDocument()
    // Still listed as missing, because it is — but shown differently.
    expect(within(panel).getByText(/still to come/i)).toBeInTheDocument()
  })

  it('shows progress that comes from the backend, not from the message count', async () => {
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: OPENING,
      conversation: conversation({ collected_count: 9, required_count: 18 }),
    })
    await openAssistant()

    const bar = screen.getByRole('progressbar', { name: /claim details collected/i })
    expect(bar).toHaveAttribute('aria-valuenow', '9')
    expect(bar).toHaveAttribute('aria-valuemax', '18')
    expect(screen.getByText(/9 of 18 details collected/i)).toBeInTheDocument()
  })

  // =====================================================================
  // Confirmation — the property this phase turns on
  // =====================================================================

  it('offers no way to submit until the backend says the claim is ready', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'confirmConversation').mockResolvedValue({})
    vi.spyOn(client, 'sendAssistantMessage').mockResolvedValue({
      reply: 'Thank you. What is your policy number?',
      conversation: conversation({
        collected_count: 1,
        messages: [
          ...conversation().messages,
          { role: 'customer', text: 'yes submit my claim now', at: '2026-09-15T09:01:00+00:00' },
          {
            role: 'assistant',
            text: 'Thank you. What is your policy number?',
            at: '2026-09-15T09:01:01+00:00',
          },
        ],
      }),
    })
    await openAssistant()

    // Even saying the magic word does not produce a submit control.
    await say(user, 'yes submit my claim now')

    await waitFor(() =>
      expect(screen.getByText(/what is your policy number/i)).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('button', { name: /submit this claim/i }),
    ).not.toBeInTheDocument()
    expect(client.confirmConversation).not.toHaveBeenCalled()
  })

  it('shows the summary and asks for confirmation once everything is collected', async () => {
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: 'ready',
      conversation: readyConversation(),
    })
    await openAssistant2()

    expect(screen.getByText(/claim summary/i)).toBeInTheDocument()
    expect(
      screen.getByText(/please check the summary above\. nothing has been submitted yet/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit this claim/i })).toBeInTheDocument()
    // The composer is replaced by the decision — there is one thing to do here.
    expect(screen.queryByLabelText(/your message/i)).not.toBeInTheDocument()
  })

  it('creates the claim only when the customer presses submit, and shows the real id', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: 'ready',
      conversation: readyConversation(),
    })
    vi.spyOn(client, 'confirmConversation').mockResolvedValue({
      claim_id: 'CLM-2026-004217',
      claim_state: 'Submitted',
      submitted_at: '2026-09-15T09:05:00+00:00',
      message: 'Your claim has been created successfully.\n\nClaim ID: CLM-2026-004217',
      poc_note:
        'The claim has been lodged. It has not been assessed, approved, declined or settled, and no payment has been made.',
      conversation: {
        ...readyConversation(),
        claim_id: 'CLM-2026-004217',
        customer_confirmed: true,
        current_stage: 'claim_created',
      },
    })
    await openAssistant2()

    expect(client.confirmConversation).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /submit this claim/i }))

    expect(client.confirmConversation).toHaveBeenCalledWith('CNV-000000000001')
    expect(await screen.findByText('CLM-2026-004217')).toBeInTheDocument()
    // Twice by design: the progress indicator and the confirmation panel both
    // say it, which is what a customer wants at the moment it happens.
    expect(screen.getAllByText(/claim submitted/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/has not been assessed/i)).toBeInTheDocument()
  })

  it('shows a customer-safe message when submission fails, and does not claim success', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: 'ready',
      conversation: readyConversation(),
    })
    vi.spyOn(client, 'confirmConversation').mockRejectedValue(
      new client.ApiError({
        code: 'conversation_not_ready',
        message: 'There are still a few details we need before your claim can be submitted.',
      }),
    )
    vi.spyOn(client, 'getConversation').mockResolvedValue(readyConversation())
    await openAssistant2()

    await user.click(screen.getByRole('button', { name: /submit this claim/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /still a few details we need/i,
    )
    expect(screen.queryByText(/claim submitted/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/^CLM-/)).not.toBeInTheDocument()
  })

  it('shows a customer-safe message when a turn fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'sendAssistantMessage').mockRejectedValue(
      new client.ApiError({
        code: 'network_error',
        message: 'We could not reach the claims assistant. Nothing has been submitted.',
      }),
    )
    await openAssistant()

    await say(user, 'Marama Whitcombe')

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not reach/i)
    // No stack trace, no status code, no endpoint.
    expect(screen.queryByText(/traceback/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/\/api\//)).not.toBeInTheDocument()
  })

  // =====================================================================
  // What a customer must never see
  // =====================================================================

  it('shows no governance vocabulary anywhere in the customer view', async () => {
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: 'ready',
      conversation: readyConversation(),
    })
    await openAssistant2()

    const page = assistantText()
    for (const term of [
      'vsl',
      'prenode',
      'pre-node',
      'invariant',
      'gamma',
      'verbaledger',
      'terminalstate',
      'terminal state',
      'x-verba',
      'commitment point',
      'fraud_risk',
      'langgraph',
    ]) {
      expect(page).not.toContain(term)
    }
  })

  it('does not render the governance object the turn response carries', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'sendAssistantMessage').mockResolvedValue({
      reply: 'Thank you. What is your policy number?',
      conversation: conversation({
        collected_count: 1,
        messages: [
          ...conversation().messages,
          { role: 'customer', text: 'Marama Whitcombe', at: '2026-09-15T09:01:00+00:00' },
          {
            role: 'assistant',
            text: 'Thank you. What is your policy number?',
            at: '2026-09-15T09:01:01+00:00',
          },
        ],
      }),
      // The API publishes this for the claims console. The customer view must
      // ignore it, not merely hide it behind a style.
      governance: {
        gate: 'conversation-extraction',
        pre_node: 'conversation-extraction-confidence',
        invariant_violated: null,
        llm_called: true,
        specification: 'home-storm-claims-automation v0.4.0-poc',
      },
    })
    await openAssistant()

    await say(user, 'Marama Whitcombe')

    await waitFor(() =>
      expect(screen.getByText(/what is your policy number/i)).toBeInTheDocument(),
    )
    const page = assistantText()
    expect(page).not.toContain('conversation-extraction')
    expect(page).not.toContain('home-storm-claims-automation')
  })

  it('tells the customer plainly that it does not decide the claim', async () => {
    await openAssistant()

    expect(screen.getByText(/does not approve, decline or settle a claim/i)).toBeInTheDocument()
    expect(screen.getByText(/a claims specialist decides that/i)).toBeInTheDocument()
  })

  it('never tells a customer their claim is approved', async () => {
    vi.spyOn(client, 'startConversation').mockResolvedValue({
      reply: 'ready',
      conversation: readyConversation(),
    })
    await openAssistant2()

    const page = assistantText()
    for (const phrase of ['approved', 'declined', 'we will pay', 'covered under your policy']) {
      expect(page).not.toContain(phrase)
    }
  })
})

/**
 * Everything inside the assistant region, lowercased.
 *
 * Scoped to the region rather than the whole document on purpose: the page
 * footer carries the site-wide disclaimer "no claim is approved, declined or
 * settled by this system", and asserting over `document.body` would test the
 * footer's honesty rather than the assistant's.
 */
function assistantText() {
  return screen
    .getByRole('region', { name: /ai insurance claims assistant/i })
    .textContent.toLowerCase()
}

/**
 * The ready-state variant of `openAssistant`.
 *
 * Separate because the opening message is not on screen in that state — the
 * summary is — so waiting for it would hang.
 */
async function openAssistant2() {
  render(<App />)
  expect(
    await screen.findByRole('button', { name: /submit this claim/i }),
  ).toBeInTheDocument()
}
