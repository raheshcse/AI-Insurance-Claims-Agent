/**
 * Phase 2 frontend tests — the internal claims console.
 *
 * The backend is mocked; these are about what a claims employee sees, and about
 * the separation between the internal view and the customer portal.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import * as client from '../api/client.js'

const REPORT = {
  claim_id: 'CLM-2026-004217',
  analysis_id: 'ANL-9F2A71C40D3B',
  analysed_at: '2026-09-13T09:20:00+00:00',
  workflow_version: 'phase-2',
  claim_state: 'Submitted',
  claim_summary: {
    policy_number: 'POL-HOME-20117',
    customer_name: 'Marama Whitcombe',
    peril: 'storm',
    date_of_loss: '2026-09-12',
    loss_address: '18 Kauri Point Road, Titirangi, Auckland 0604',
    damaged_item_count: 1,
    damage_areas: ['Roof'],
  },
  agent_results: {
    intake: {
      agent: 'intake',
      status: 'complete',
      findings: [],
      recommendation: 'The FNOL is structured and ready for policy retrieval.',
      reasons: [],
      confidence: { value: 0.95, basis: 'Deterministic structuring.' },
      data_references: [],
      next_step: 'policy_retrieval',
      narrative: 'Storm damage to the roof.',
      narrative_source: 'stub',
      is_recommendation_only: true,
    },
    policy: {
      agent: 'policy',
      status: 'complete',
      findings: [
        {
          code: 'EXCESS_APPLIES',
          summary: 'An excess of NZD 1,000 applies to this claim.',
          severity: 'info',
          detail: null,
          data_reference: 'wording 3.1',
          assumption: null,
        },
      ],
      recommendation: 'Cover appears to apply. Proceed to validation.',
      reasons: [],
      confidence: { value: 0.9, basis: 'Read from the record.' },
      data_references: [],
      next_step: 'validation',
      is_recommendation_only: true,
    },
    validation: {
      agent: 'validation',
      status: 'complete',
      findings: [],
      recommendation: 'The claim has the information needed to be assessed.',
      reasons: [],
      confidence: { value: 0.9, basis: 'Deterministic checks.' },
      data_references: [],
      next_step: 'assessment',
      is_recommendation_only: true,
    },
    assessment: {
      agent: 'assessment',
      status: 'complete',
      findings: [
        {
          code: 'HIGH_VALUE',
          summary: 'The estimate of NZD 14,000 is above the proposed threshold.',
          severity: 'attention',
          detail: null,
          data_reference: 'docs/DECISION_TABLE.md 2.4',
          assumption: 'POC-proposed threshold pending business approval',
        },
      ],
      recommendation: 'A claims specialist should handle this claim.',
      reasons: [],
      confidence: { value: 0.85, basis: 'Deterministic banding.' },
      data_references: [],
      next_step: 'manual_review',
      is_recommendation_only: true,
    },
    fraud_risk: {
      agent: 'fraud_risk',
      status: 'complete',
      findings: [],
      recommendation: 'A claims specialist should review this claim.',
      reasons: [],
      confidence: { value: 0.85, basis: 'Rules evaluated against history.' },
      data_references: [],
      next_step: 'manual_review',
      is_recommendation_only: true,
    },
  },
  policy_assessment: {
    facts: {
      policy_id: 'POL-HOME-20117',
      policy_status: 'active',
      inception_date: '2024-08-01',
      expiry_date: '2027-08-01',
      covered_perils: ['storm'],
      dwelling_sum_insured: 750000,
      contents_sum_insured: 85000,
      standard_excess: 500,
      storm_excess: 1000,
      exclusion_codes: [],
      condition_codes: [],
      optional_covers: [],
      insured_address: '18 Kauri Point Road, Titirangi, Auckland 0604',
    },
    interpretation: {
      policy_found: true,
      in_force_at_date_of_loss: true,
      peril_covered: true,
      address_matches_insured_address: true,
      applicable_excess: 1000,
      exclusions_possibly_engaged: [],
      cover_certainty: 'clear',
      relevant_wording_refs: ['2.1', '3.1'],
      caveat: 'An AI reading of policy wording. Not a cover decision.',
    },
  },
  validation_result: {
    validation_status: 'complete',
    missing_information: [],
    inconsistencies: [],
    checks_performed: [],
  },
  damage_assessment: {
    incident_category: 'roof_damage',
    complexity_band: 'medium',
    complexity_factors: [],
    urgency_band: 'standard',
    severity_indicators: [],
    estimated_claim_value: 14000,
    estimate_basis: "The customer's overall estimate.",
    value_band: 'high_value',
    net_of_excess_estimate: 13000,
  },
  risk_assessment: {
    risk_level: 'medium',
    indicators: [
      {
        rule_id: 'RISK-INCEPT-01',
        name: 'Claim soon after policy inception',
        detail: 'The loss occurred 19 day(s) after the policy started.',
        severity: 'standard',
        data_reference: 'policies.jsonl:POL-HOME-20117',
        customer_visible: false,
      },
    ],
    historical_claims_considered: 2,
    framing_note:
      'Risk indicators are prompts for a human to look more closely. They are not evidence of fraud.',
  },
  recommended_next_step: 'manual_review_recommended',
  recommendation_summary: 'A claims specialist should review this claim.',
  recommendation_reasons: ['A risk indicator is present.'],
  overall_confidence: {
    value: 0.85,
    basis: 'The lowest agent confidence.',
    clears_poc_threshold: true,
    threshold_note: 'Reported only.',
  },
  recommended_claim_state: 'Assessment',
  is_recommendation_only: true,
  action_taken: 'none',
  claim_state_changed: false,
  boundary_note:
    'This is analysis, not a decision. No claim has been approved, declined, settled or progressed, and no customer has been contacted.',
  trace: [
    { agent: 'intake', status: 'complete', next_step: 'policy_retrieval', duration_ms: 1 },
    { agent: 'policy', status: 'complete', next_step: 'validation', duration_ms: 2 },
    { agent: 'validation', status: 'complete', next_step: 'assessment', duration_ms: 1 },
    { agent: 'assessment', status: 'complete', next_step: 'risk_check', duration_ms: 1 },
    { agent: 'fraud_risk', status: 'complete', next_step: 'manual_review', duration_ms: 2 },
  ],
  errors: [],
  degraded: false,
  llm_provider: 'stub',
}

const openConsole = async (user) => {
  await user.click(screen.getByRole('button', { name: /claims console/i }))
}

const runAnalysis = async (user, claimId = 'CLM-2026-004217') => {
  await user.type(screen.getByLabelText(/claim reference/i), claimId)
  await user.click(screen.getByRole('button', { name: /^run analysis$/i }))
}

describe('claims console', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('is not the default view — customers see the assistant', () => {
    // Phase 5 changed WHICH customer view is the default, not the property
    // being asserted: a customer never lands on the claims console.
    render(<App />)
    expect(
      screen.getByRole('region', { name: /ai insurance claims assistant/i }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/internal view/i)).not.toBeInTheDocument()
  })

  it('marks itself as internal when opened', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openConsole(user)

    expect(screen.getByRole('heading', { name: /claims console/i })).toBeInTheDocument()
    expect(screen.getByText(/internal view — claims staff/i)).toBeInTheDocument()
  })

  it('runs the workflow and shows the recommendation', async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    expect(spy).toHaveBeenCalledWith('CLM-2026-004217', { force: false })
    expect(await screen.findByText(/manual review recommended/i)).toBeInTheDocument()
    expect(
      screen.getByText('A claims specialist should review this claim.', {
        selector: '.recommendation__summary',
      }),
    ).toBeInTheDocument()
  })

  it('states the recommendation/action boundary prominently', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    const notes = await screen.findAllByRole('note')
    const boundary = notes.find((note) => /analysis only/i.test(note.textContent))
    expect(boundary).toBeDefined()
    expect(within(boundary).getByText(/analysis only/i)).toBeInTheDocument()
    expect(screen.getByText(/unchanged by this analysis/i)).toBeInTheDocument()
  })

  it('shows all five agent panels', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    for (const name of [/^intake$/i, /^policy$/i, /^validation$/i, /^assessment$/i, /fraud & risk/i]) {
      expect(await screen.findByRole('heading', { name })).toBeInTheDocument()
    }
  })

  it('shows policy findings, validation, assessment bands and risk indicators', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    expect(await screen.findByText(/an excess of nzd 1,000 applies/i)).toBeInTheDocument()
    expect(screen.getByText(/roof damage/i)).toBeInTheDocument()
    expect(screen.getByText(/claim soon after policy inception/i)).toBeInTheDocument()
    expect(screen.getByText(/overall confidence 85%/i)).toBeInTheDocument()
  })

  it('marks findings that rest on a POC-proposed threshold', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    expect(await screen.findByText(/poc assumption/i)).toBeInTheDocument()
  })

  it('marks risk indicators as employee-only and frames them as prompts', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    expect(await screen.findByText(/employee only/i)).toBeInTheDocument()
    expect(screen.getByText(/not evidence of fraud/i)).toBeInTheDocument()
  })

  it('warns when the analysis came back degraded', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue({
      ...REPORT,
      degraded: true,
      risk_assessment: null,
    })
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    expect(await screen.findByText(/analysis incomplete/i)).toBeInTheDocument()
    expect(
      screen.getByText(/treat the absence of findings as unknown/i),
    ).toBeInTheDocument()
  })

  it('shows a safe message when the analysis cannot run', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockRejectedValue(
      new client.ApiError({
        code: 'claim_analysis_failed',
        message: 'Nothing about the claim has changed.',
      }),
    )
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText(/nothing about the claim has changed/i)).toBeInTheDocument()
  })

  it('asks for a claim reference before running', async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(client, 'analyseClaim')
    render(<App />)
    await openConsole(user)
    await user.click(screen.getByRole('button', { name: /^run analysis$/i }))

    expect(spy).not.toHaveBeenCalled()
    expect(await screen.findByText(/enter a claim reference/i)).toBeInTheDocument()
  })

  it('keeps internal analysis out of the customer portal', async () => {
    const user = userEvent.setup()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT)
    render(<App />)
    await openConsole(user)
    await runAnalysis(user)
    expect(await screen.findByText(/claim soon after policy inception/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^claims assistant$/i }))

    expect(screen.queryByText(/claim soon after policy inception/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/employee only/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/risk signal/i)).not.toBeInTheDocument()
  })
})
