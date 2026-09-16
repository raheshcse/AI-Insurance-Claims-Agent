/**
 * Phase 3 frontend tests — the review queue and claim review.
 *
 * The backend is mocked; these are about what a reviewer sees, and about the
 * separation between an AI recommendation and a human decision.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import * as client from '../api/client.js'

const URGENT_REASON = {
  code: 'E-11_EMERGENCY',
  label: 'Emergency situation',
  detail:
    'The claim shows emergency indicators — the home is reported as not liveable. Treat as a priority.',
  basis: 'ai_finding',
  priority: 'urgent',
  outcome: 'HUMAN_REVIEW_REQUIRED',
  rule_reference: 'docs/HUMAN_ESCALATION_POLICY.md §4.1 · decision row D-13',
  observed_value: 'the home is reported as not liveable',
  threshold_value: null,
  assumption: 'POC-proposed threshold pending business approval',
  source_agent: 'intake/assessment',
}

const VALUE_REASON = {
  code: 'E-04_ABOVE_AUTOMATED_AUTHORITY',
  label: 'Above automated authority limit',
  detail: 'The estimated value is above the limit the POC rules allow automated handling for.',
  basis: 'business_rule',
  priority: 'high',
  outcome: 'HUMAN_REVIEW_REQUIRED',
  rule_reference: 'docs/DECISION_TABLE.md D-08 · Invariant INV-02 in Phase 4',
  observed_value: 'NZD 42,000',
  threshold_value: 'NZD 20,000',
  assumption: 'POC-proposed threshold pending business approval',
  source_agent: 'assessment',
}

const QUEUE = {
  total: 2,
  open_count: 2,
  urgent_count: 1,
  entries: [
    {
      queue_id: 'RQ-AAAA111122',
      claim_id: 'CLM-2026-004217',
      claim_state: 'Human Review',
      internal_status: 'assessment_complete',
      queue_status: 'open',
      priority: 'urgent',
      review_type: 'priority_review',
      primary_reason_code: 'E-11_EMERGENCY',
      primary_reason_label: 'Emergency situation',
      reason_count: 2,
      customer_name: 'Marama Whitcombe',
      policy_number: 'POL-HOME-20117',
      peril: 'storm',
      date_of_loss: '2026-09-12',
      estimated_claim_value: 42000,
      complexity_band: 'high',
      risk_level: 'low',
      confidence: 0.72,
      created_at: '2026-09-13T09:20:00+00:00',
      updated_at: '2026-09-13T09:20:00+00:00',
      assigned_to: null,
    },
    {
      queue_id: 'RQ-BBBB222233',
      claim_id: 'CLM-2026-009001',
      claim_state: 'Human Review',
      internal_status: 'assessment_complete',
      queue_status: 'open',
      priority: 'standard',
      review_type: 'standard_review',
      primary_reason_code: 'E-03_HIGH_VALUE',
      primary_reason_label: 'High-value claim',
      reason_count: 1,
      customer_name: 'Tobias Fenwick',
      policy_number: 'POL-HOME-20455',
      peril: 'storm',
      date_of_loss: '2026-09-10',
      estimated_claim_value: 14000,
      complexity_band: 'medium',
      risk_level: 'low',
      confidence: 0.85,
      created_at: '2026-09-13T08:00:00+00:00',
      updated_at: '2026-09-13T08:00:00+00:00',
      assigned_to: null,
    },
  ],
}

const DETAIL = {
  claim_id: 'CLM-2026-004217',
  claim_state: 'Human Review',
  internal_status: 'assessment_complete',
  queue_entry: {
    ...QUEUE.entries[0],
    analysis_id: 'ANL-9F2A71C40D3B',
    reasons: [URGENT_REASON, VALUE_REASON],
    explanation: [
      'Emergency situation: the home is reported as not liveable. Source: an AI finding.',
      'Above automated authority limit. Observed: NZD 42,000. Compared against: NZD 20,000.',
    ],
    routing_summary: 'Human review required — emergency situation. 2 escalation reason(s) recorded.',
    recommended_next_step: 'manual_review_recommended',
    vulnerable_customer: false,
    emergency: true,
    history: [],
  },
  customer_report: {
    customer: {
      full_name: 'Marama Whitcombe',
      policy_number: 'POL-HOME-20117',
      email: 'm.whitcombe@example.invalid',
      phone: '+64 20 900 0142',
      preferred_contact_method: 'email',
    },
    property: {
      loss_address: {
        address_line_1: '18 Kauri Point Road',
        suburb: 'Titirangi',
        city: 'Auckland',
        postcode: '0604',
      },
      property_habitable: false,
      temporary_accommodation_needed: true,
    },
    damage: {
      date_of_loss: '2026-09-12',
      peril: 'storm',
      incident_description: 'The storm tore the roof open and the ceiling came down.',
      damaged_items: [
        { area: 'Roof', item: 'Roof', description: 'Roof partly torn off' },
      ],
      anyone_injured: false,
      damage_ongoing: true,
      utilities_affected: ['power'],
      photos_supplied: true,
    },
  },
  intelligence: null,
  available_actions: [
    'start_review',
    'request_information',
    'refer_to_specialist',
    'complete_review',
  ],
  decision_authority_note:
    "Everything the AI produced is a recommendation. The reviewer's action is the decision.",
}

const openQueue = async (user) => {
  await user.click(screen.getByRole('button', { name: /claims console/i }))
  await user.click(screen.getByRole('button', { name: /review queue/i }))
}

describe('review queue', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'getReviewQueue').mockResolvedValue(QUEUE)
    vi.spyOn(client, 'getClaimReview').mockResolvedValue(DETAIL)
  })

  it('lists escalated claims with their reason and priority', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openQueue(user)

    expect(await screen.findByRole('button', { name: 'CLM-2026-004217' })).toBeInTheDocument()
    expect(screen.getByText('Emergency situation')).toBeInTheDocument()
    expect(screen.getByText(/\+1 more reason/i)).toBeInTheDocument()
    expect(screen.getAllByText('urgent').length).toBeGreaterThan(0)
  })

  it('shows how many claims are waiting and how many are urgent', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openQueue(user)

    expect(await screen.findByText(/awaiting a reviewer/i)).toBeInTheDocument()
    expect(screen.getByText(/1 urgent/i)).toBeInTheDocument()
  })

  it('puts the urgent claim above the standard one', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openQueue(user)

    await screen.findByRole('button', { name: 'CLM-2026-004217' })
    const rows = screen.getAllByRole('listitem')
    expect(within(rows[0]).getByRole('button', { name: 'CLM-2026-004217' })).toBeInTheDocument()
  })

  it('can filter the queue', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openQueue(user)
    await screen.findByRole('button', { name: 'CLM-2026-004217' })

    await user.click(screen.getByRole('button', { name: /^closed$/i }))

    expect(client.getReviewQueue).toHaveBeenCalledWith({ status: 'closed' })
  })

  it('shows a safe message when the queue cannot be loaded', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'getReviewQueue').mockRejectedValue(
      new client.ApiError({ code: 'network_error', message: 'We could not reach our claims service.' }),
    )
    render(<App />)
    await openQueue(user)

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/could not reach our claims service/i)).toBeInTheDocument()
  })
})

describe('claim review', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'getReviewQueue').mockResolvedValue(QUEUE)
    vi.spyOn(client, 'getClaimReview').mockResolvedValue(DETAIL)
  })

  const openClaim = async (user) => {
    await openQueue(user)
    await user.click(await screen.findByRole('button', { name: 'CLM-2026-004217' }))
  }

  it('opens the claim review from the queue', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(
      await screen.findByRole('heading', { name: /claim CLM-2026-004217/i }),
    ).toBeInTheDocument()
  })

  it('shows what the customer reported', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(await screen.findByText(/what the customer reported/i)).toBeInTheDocument()
    expect(
      screen.getByText('The storm tore the roof open and the ceiling came down.'),
    ).toBeInTheDocument()
  })

  it('explains every escalation reason with its evidence and its basis', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(await screen.findByText(/why this claim was escalated/i)).toBeInTheDocument()
    expect(screen.getByText('Above automated authority limit')).toBeInTheDocument()
    expect(screen.getByText('NZD 42,000')).toBeInTheDocument()
    expect(screen.getByText('NZD 20,000')).toBeInTheDocument()
    // The distinction the requirements ask for.
    expect(screen.getByText('AI finding')).toBeInTheDocument()
    expect(screen.getByText('Business rule')).toBeInTheDocument()
  })

  it('never says the AI simply decided to escalate', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)
    await screen.findByText(/why this claim was escalated/i)

    expect(screen.queryByText(/ai decided/i)).not.toBeInTheDocument()
  })

  it('flags the emergency pathway', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    // Shown twice on purpose: a chip in the header, and a banner with guidance.
    expect((await screen.findAllByText('Emergency pathway')).length).toBe(2)
    expect(screen.getByText(/contact the customer before routine handling/i)).toBeInTheDocument()
  })

  it('flags a vulnerable customer separately and operationally', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'getClaimReview').mockResolvedValue({
      ...DETAIL,
      queue_entry: { ...DETAIL.queue_entry, emergency: false, vulnerable_customer: true },
    })
    render(<App />)
    await openClaim(user)

    expect((await screen.findAllByText('Vulnerable customer support')).length).toBe(2)
    expect(screen.getByText(/no medical or personal information/i)).toBeInTheDocument()
  })

  it('keeps the reviewer decision separate from the AI recommendation', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(await screen.findByText(/reviewer decision/i)).toBeInTheDocument()
    expect(
      screen.getByText(/everything above is an ai recommendation/i),
    ).toBeInTheDocument()
  })

  it('records a review action and shows the state change', async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(client, 'performReviewAction').mockResolvedValue({
      claim_id: 'CLM-2026-004217',
      action: 'refer_to_specialist',
      performed_by: 'A. Reviewer',
      performed_at: '2026-09-13T10:00:00+00:00',
      previous_claim_state: 'Human Review',
      claim_state: 'Human Review',
      internal_status: 'specialist_referral',
      queue_status: 'open',
      notes: '',
      decision_source: 'human',
      poc_note:
        'A POC review outcome. It does not approve a claim for payment, set a reserve, settle anything, or notify the customer.',
    })
    render(<App />)
    await openClaim(user)

    await user.selectOptions(
      await screen.findByLabelText(/^action$/i),
      'refer_to_specialist',
    )
    await user.type(screen.getByLabelText(/your name/i), 'A. Reviewer')
    await user.click(screen.getByRole('button', { name: /record decision/i }))

    expect(spy).toHaveBeenCalledWith(
      'CLM-2026-004217',
      expect.objectContaining({ action: 'refer_to_specialist', reviewer: 'A. Reviewer' }),
    )
    expect(await screen.findByText(/review action recorded/i)).toBeInTheDocument()
    expect(
      screen.getByText(/does not approve a claim for payment/i),
    ).toBeInTheDocument()
  })

  it('requires a reviewer name before recording anything', async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(client, 'performReviewAction')
    render(<App />)
    await openClaim(user)

    await user.click(await screen.findByRole('button', { name: /record decision/i }))

    expect(spy).not.toHaveBeenCalled()
    expect(await screen.findByText(/enter your name/i)).toBeInTheDocument()
  })

  it('states plainly what completing a review does and does not do', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    await user.selectOptions(await screen.findByLabelText(/^action$/i), 'complete_review')

    expect(
      screen.getByText(/does not approve a claim for payment, set a reserve/i),
    ).toBeInTheDocument()
  })

  it('keeps all of this out of the customer portal', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)
    await screen.findByText(/why this claim was escalated/i)

    await user.click(screen.getByRole('button', { name: /^claims assistant$/i }))

    expect(screen.queryByText(/why this claim was escalated/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/reviewer decision/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Emergency pathway')).not.toBeInTheDocument()
  })
})
