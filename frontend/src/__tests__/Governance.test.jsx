/**
 * Phase 4 frontend tests — the governance dashboard and the claim-level panel.
 *
 * The backend is mocked. What these check is not that the numbers render, but
 * that the screen tells the truth about them:
 *
 *   - a failing audit is shown as failing, not smoothed into a summary
 *   - a SKIPPED check is visibly not a passed one
 *   - derived assurance is shown as LOW, with what LOW means
 *   - a PreNode denial (rerouted) and an Invariant violation (halted) are
 *     distinguishable, because that is the difference a reviewer acts on
 *   - lifting a terminal state requires a named person and evidence
 *   - none of this leaks into the customer portal
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App.jsx'
import * as client from '../api/client.js'

const CONFIGURATION = {
  specification: 'home-storm-claims-automation v0.4.0-poc',
  specification_active: true,
  governance_authority: 'Claims Governance Board (POC placeholder)',
  pre_nodes: [
    {
      name: 'automation-confidence',
      description:
        'Confidence must clear the robust Gamma threshold before a claim is handled automatically.',
      gamma_threshold: 1.1,
      assurance_level: 'LOW',
      fallback: 'ROUTE_TO_HUMAN_QUEUE',
      kind: 'soft_gate',
      note: 'A denial reroutes to a person.',
    },
  ],
  invariants: [
    {
      name: 'policy-in-force',
      description: 'A claim must not be handled automatically unless the policy was in force.',
      assurance_level: 'LOW',
      on_violation: 'claim-automation-suspended',
      kind: 'hard_rule',
      note: 'Non-bypassable.',
    },
    {
      name: 'automated-authority-limit',
      description: 'Automated claim handling must stay within the automated authority limit.',
      assurance_level: 'LOW',
      on_violation: 'claim-automation-suspended',
      kind: 'hard_rule',
      note: 'Non-bypassable.',
    },
  ],
  terminal_states: [
    {
      name: 'claim-automation-suspended',
      description: 'Automated claim handling halted.',
      entry_conditions: ['policy-in-force violated'],
      requires_human_authorised_transition: true,
    },
  ],
  decision_threshold: 0.8,
  effective_confidence_floor: 0.8148,
  gamma_threshold: 1.1,
  automated_authority_limit_nzd: 20000,
  assurance_level: 'LOW',
  assurance_basis: {
    f1_pre_commitment: true,
    f2_modification: 'NONE',
    derived_level: 'LOW',
  },
  assurance_note:
    'Derived by VSL from the F1/F2 facts, not asserted. LOW means output-layer control.',
  threshold_note:
    'POC-proposed threshold pending business approval - not an insurer-approved rule',
}

const DASHBOARD = {
  configuration: CONFIGURATION,
  counts: {
    total_entries: 13,
    by_type: { MONITOR: 4, PRE_NODE: 4, VERIFICATION: 4, TERMINAL: 1 },
    decisions: 4,
    claims_seen: 3,
    drift_flagged: 2,
    pre_node_denials: 1,
    invariant_violations: 1,
    terminal_states_entered: 1,
    terminal_states_open: 1,
    human_authorised_transitions: 0,
    actions_denied: 2,
  },
  integrity: {
    verified: true,
    entries: 13,
    checkpoint_sequence: 12,
    checkpoint_hash: 'a1b2c3d4e5f6a7b8',
    note: 'verify_integrity() answers whether these records were edited.',
  },
  audit: {
    all_passed: false,
    checks_passed: [
      'drift_flagged_monitor_has_pre_node',
      'pre_node_has_verification',
      'insufficient_verification_has_specification_update',
    ],
    checks_failed: ['terminal_has_human_authorised_transition'],
    checks_not_asserted: ['no_monitoring_gaps'],
    violations: { terminal_has_human_authorised_transition: ['entry-terminal-1'] },
    certificate_issued: false,
    note:
      'An open terminal state fails check 5 by design: automation was suspended and no person has authorised resuming it.',
  },
  suspended_claims: [
    {
      claim_id: 'CLM-2026-004900',
      terminal_state: 'claim-automation-suspended',
      invariant: 'policy-in-force',
      decision_id: 'dec-1',
      terminal_entry_id: 'entry-terminal-1',
      exit_route: 'human_authorised_transition_only',
    },
  ],
  denied_actions: [
    {
      entry_id: 'entry-terminal-1',
      claim_id: 'CLM-2026-004900',
      decision_id: 'dec-1',
      recorded_at: '2026-09-13T09:31:00+00:00',
      gate: 'policy-in-force',
      gate_kind: 'invariant',
      reason: 'The policy was not in force at the date of loss.',
      fallback: null,
      terminal_state: 'claim-automation-suspended',
    },
    {
      entry_id: 'entry-prenode-9',
      claim_id: 'CLM-2026-004217',
      decision_id: 'dec-2',
      recorded_at: '2026-09-13T09:28:00+00:00',
      gate: 'automation-confidence',
      gate_kind: 'pre_node',
      reason: 'Gamma 0.72 is below the robust threshold of 1.1.',
      fallback: 'ROUTE_TO_HUMAN_QUEUE',
      terminal_state: null,
    },
  ],
  recent_entries: [
    {
      sequence: 12,
      entry_id: 'entry-terminal-1',
      entry_type: 'TERMINAL',
      caused_by: 'entry-verify-1',
      decision_id: 'dec-1',
      instance_id: 'inst-1',
      identity_key: 'home-storm-claims-automation',
      timestamp: 1789000000,
      recorded_at: '2026-09-13T09:31:00+00:00',
      claim_id: 'CLM-2026-004900',
      payload: { invariant: 'policy-in-force' },
    },
    {
      sequence: 11,
      entry_id: 'entry-verify-1',
      entry_type: 'VERIFICATION',
      caused_by: 'entry-prenode-1',
      decision_id: 'dec-1',
      instance_id: 'inst-1',
      identity_key: 'home-storm-claims-automation',
      timestamp: 1789000000,
      recorded_at: '2026-09-13T09:31:00+00:00',
      claim_id: 'CLM-2026-004900',
      payload: { result: 'INSUFFICIENT' },
    },
  ],
  boundary_note:
    'Governance decides whether an automated step may proceed. It never decides a claim.',
}

const SUSPENDED_DETAIL = {
  claim_id: 'CLM-2026-004900',
  claim_state: 'Human Review',
  internal_status: 'automation_suspended',
  automation_suspended: true,
  governance: {
    action: 'suspended',
    permitted: false,
    decision_id: 'dec-1',
    claim_id: 'CLM-2026-004900',
    specification: 'home-storm-claims-automation v0.4.0-poc',
    pre_node: 'automation-confidence',
    pre_node_denied: false,
    denial_reason: null,
    invariant_violated: 'policy-in-force',
    terminal_state: 'claim-automation-suspended',
    fallback: null,
    assurance_level: 'LOW',
    gamma_threshold: 1.1,
    confidence: 0.91,
    confidence_floor: 0.8148,
    ledger_entry_ids: ['a', 'b', 'c', 'd', 'e'],
    side_effect_performed: false,
    automation_suspended: true,
  },
  queue_entry: {
    queue_id: 'RQ-1',
    claim_id: 'CLM-2026-004900',
    claim_state: 'Human Review',
    internal_status: 'automation_suspended',
    queue_status: 'open',
    priority: 'high',
    review_type: 'manual_review',
    primary_reason_code: 'E-05_POLICY_NOT_IN_FORCE',
    primary_reason_label: 'Policy not in force at the date of loss',
    reason_count: 1,
    reasons: [],
    explanation: [],
    routing_summary: 'Human review required.',
    recommended_next_step: 'manual_review_recommended',
    customer_name: 'Tane Ropata',
    policy_number: 'POL-HOME-20118',
    peril: 'storm',
    date_of_loss: '2026-09-10',
    estimated_claim_value: 8400,
    complexity_band: 'medium',
    risk_level: 'low',
    confidence: 0.91,
    created_at: '2026-09-13T09:31:00+00:00',
    updated_at: '2026-09-13T09:31:00+00:00',
    assigned_to: null,
    vulnerable_customer: false,
    emergency: false,
    automation_suspended: true,
    history: [],
  },
  customer_report: {
    customer: { full_name: 'Tane Ropata', policy_number: 'POL-HOME-20118' },
    property: { loss_address: {} },
    damage: { damaged_items: [] },
  },
  intelligence: null,
  available_actions: ['start_review'],
  decision_authority_note: "The reviewer's action is the decision.",
}

const SUSPENDED_QUEUE = {
  total: 1,
  open_count: 1,
  urgent_count: 0,
  entries: [SUSPENDED_DETAIL.queue_entry],
}

const openGovernance = async (user) => {
  await user.click(screen.getByRole('button', { name: /claims console/i }))
  await user.click(screen.getByRole('button', { name: /^governance$/i }))
}

describe('governance dashboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'getGovernanceDashboard').mockResolvedValue(DASHBOARD)
  })

  it('is not visible in the customer portal', () => {
    render(<App />)
    expect(screen.queryByText(/X-Verba/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/VerbaLedger/i)).not.toBeInTheDocument()
  })

  it('shows what is enforced, by name', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    // Named twice by design: once as a declared construct, once as the gate
    // that denied an action. Both belong on the page.
    expect(await screen.findAllByText(/automation-confidence/)).toHaveLength(2)
    expect(screen.getAllByText(/policy-in-force/).length).toBeGreaterThan(0)
    expect(screen.getByText(/automated-authority-limit/)).toBeInTheDocument()
    expect(
      screen.getByText(/home-storm-claims-automation v0\.4\.0-poc/),
    ).toBeInTheDocument()
  })

  it('distinguishes a soft gate from a hard rule', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(await screen.findByText(/PreNode — soft gate/)).toBeInTheDocument()
    expect(screen.getAllByText(/Invariant — hard rule/).length).toBe(2)
  })

  it('reports the derived assurance as LOW and says what LOW means', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(await screen.findByText('LOW')).toBeInTheDocument()
    // Once on the badge, once in the explanation beneath it.
    expect(screen.getAllByText(/output-layer control/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/not asserted/i).length).toBeGreaterThan(0)
  })

  it('shows a failing audit as failing rather than summarising it away', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(await screen.findByText(/1 check failing/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Every terminal state was lifted by a person/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/No certificate issued/i)).toBeInTheDocument()
    expect(
      screen.getByText(/the audit is not passing, and that is the point/i),
    ).toBeInTheDocument()
  })

  it('never lets a skipped check read as a passed one', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    const skipped = await screen.findByText(/no monitoring-gap threshold was given/i)
    const row = skipped.closest('li')
    expect(within(row).getByText(/^Not asserted$/i)).toBeInTheDocument()
    expect(within(row).queryByText(/^Pass$/i)).not.toBeInTheDocument()
  })

  it('distinguishes a rerouted PreNode denial from a halted Invariant violation', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(
      await screen.findByText(/PreNode — rerouted to a person/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Invariant — automation halted/i)).toBeInTheDocument()
    expect(screen.getByText(/Fallback: ROUTE_TO_HUMAN_QUEUE/)).toBeInTheDocument()
  })

  it('lists the claims whose automation is suspended and how they get out', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(await screen.findAllByText('CLM-2026-004900')).not.toHaveLength(0)
    expect(
      screen.getByText(/A claims authority must authorise the transition/i),
    ).toBeInTheDocument()
  })

  it('shows the ledger as a causal chain, not a timeline', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(await screen.findByText(/Ledger events/i)).toBeInTheDocument()
    expect(screen.getByText(/Chain intact/i)).toBeInTheDocument()
    expect(screen.getByText(/13 entries · tip #12/)).toBeInTheDocument()
    // Column header in the suspended table and the event label in the ledger.
    expect(screen.getAllByText(/Terminal state/).length).toBeGreaterThan(0)
  })

  it('states that governance never decides a claim', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    // Said in the lede and again in the closing note -- the one claim on this
    // page that is worth repeating.
    expect(
      (await screen.findAllByText(/It never decides a claim/i)).length,
    ).toBeGreaterThanOrEqual(2)
  })

  it('shows a safe message when the dashboard cannot be loaded', async () => {
    vi.spyOn(client, 'getGovernanceDashboard').mockRejectedValue(
      new client.ApiError({
        code: 'network_error',
        message: 'We could not reach our claims service.',
      }),
    )
    const user = userEvent.setup()
    render(<App />)
    await openGovernance(user)

    expect(
      await screen.findByText(/could not be loaded/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Traceback/i)).not.toBeInTheDocument()
  })
})

describe('a claim whose automation is suspended', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'getReviewQueue').mockResolvedValue(SUSPENDED_QUEUE)
    vi.spyOn(client, 'getClaimReview').mockResolvedValue(SUSPENDED_DETAIL)
  })

  const openClaim = async (user) => {
    await user.click(screen.getByRole('button', { name: /claims console/i }))
    await user.click(screen.getByRole('button', { name: /review queue/i }))
    await user.click(await screen.findByRole('button', { name: 'CLM-2026-004900' }))
  }

  it('is flagged in the queue before anyone opens it', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /claims console/i }))
    await user.click(screen.getByRole('button', { name: /review queue/i }))

    expect(await screen.findByText('Automation suspended')).toBeInTheDocument()
  })

  it('shows which Invariant was violated and which terminal state was entered', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(await screen.findByText(/Governance \(X-Verba \/ VSL\)/)).toBeInTheDocument()
    expect(screen.getByText('policy-in-force')).toBeInTheDocument()
    expect(screen.getAllByText(/claim-automation-suspended/).length).toBeGreaterThan(0)
  })

  it('says plainly that nothing lifts the suspension on its own', async () => {
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    expect(
      await screen.findByText(/no timeout, no retry, no confidence score/i),
    ).toBeInTheDocument()
  })

  it('requires a name and both pieces of evidence before re-enabling', async () => {
    const spy = vi.spyOn(client, 'reEnableAutomation')
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    await user.click(
      await screen.findByRole('button', { name: /authorise re-enablement/i }),
    )
    expect(spy).not.toHaveBeenCalled()
    expect(await screen.findByText(/enter your name/i)).toBeInTheDocument()

    await user.type(screen.getByLabelText(/your name/i, { selector: '#reenable_authorised_by' }), 'A. Reviewer')
    await user.type(screen.getByLabelText(/root-cause analysis/i), 'too short')
    await user.click(screen.getByRole('button', { name: /authorise re-enablement/i }))

    expect(spy).not.toHaveBeenCalled()
    expect(
      await screen.findByText(/both the root-cause analysis and the specification-update proposal are required/i),
    ).toBeInTheDocument()
  })

  it('records the re-enablement as a named person’s decision', async () => {
    const spy = vi.spyOn(client, 'reEnableAutomation').mockResolvedValue({
      claim_id: 'CLM-2026-004900',
      terminal_state: 'claim-automation-suspended',
      invariant: 'policy-in-force',
      authorised_by: 'A. Reviewer',
      authority: 'Claims Governance Board (POC placeholder)',
      human_authorised_transition_id: 'entry-hat-1',
      re_enablement_entry_id: 'entry-re-1',
      new_instance_id: 'inst-2',
      generation: 1,
      decision_source: 'human',
      poc_note:
        'Automation is re-enabled for this claim. The claim itself is unchanged.',
    })
    const user = userEvent.setup()
    render(<App />)
    await openClaim(user)

    await user.type(screen.getByLabelText(/your name/i, { selector: '#reenable_authorised_by' }), 'A. Reviewer')
    await user.type(
      screen.getByLabelText(/root-cause analysis/i),
      'The policy record carried a stale expiry date from the migration.',
    )
    await user.type(
      screen.getByLabelText(/specification-update proposal/i),
      'Validate policy expiry dates at ingest before any automated handling.',
    )
    await user.click(screen.getByRole('button', { name: /authorise re-enablement/i }))

    expect(spy).toHaveBeenCalledWith('CLM-2026-004900', {
      authorised_by: 'A. Reviewer',
      root_cause_analysis:
        'The policy record carried a stale expiry date from the migration.',
      specification_update_proposal:
        'Validate policy expiry dates at ingest before any automated handling.',
    })

    expect(
      await screen.findByText(/automation re-enabled for this claim/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/The claim itself is unchanged/i)).toBeInTheDocument()
  })
})


// =========================================================================
// CP-13 — the LLM commitment gate, as the console shows it
// =========================================================================

const REPORT_WITH_LLM_GATE = {
  claim_id: 'CLM-2026-004217',
  analysis_id: 'ANL-CP13',
  analysed_at: '2026-09-15T09:20:00+00:00',
  workflow_version: 'phase-4',
  claim_state: 'Submitted',
  claim_state_changed: false,
  is_recommendation_only: true,
  action_taken: 'none',
  claim_summary: { customer_name: 'Marama Whitcombe', policy_number: 'POL-HOME-20117' },
  recommended_next_step: 'manual_review_recommended',
  recommendation_summary: 'Human review required.',
  recommendation_reasons: [],
  overall_confidence: { value: 0.85, basis: 'lowest agent confidence' },
  degraded: false,
  trace: [],
  errors: [],
  llm_provider: 'gemini',
  llm_model: 'gemini-3.8-flash',
  llm_degraded: false,
  llm_governance: {
    gate: 'llm-narration',
    commitment_point: 'CP-13',
    governed_calls: 2,
    permitted: 1,
    blocked: 1,
    llm_calls_made: 1,
    invariants_violated: ['no-customer-data-egress'],
    terminal_states: ['claim-automation-suspended'],
    blocked_reasons: ['Identifiable policyholder data in the outbound payload.'],
    ledger_entry_ids: ['a', 'b', 'c'],
    note: 'The gate runs before the provider call. A blocked call was never made: no request was built and no key was read.',
  },
  agent_results: {
    intake: {
      agent: 'intake',
      status: 'complete',
      findings: [],
      recommendation: 'Ready for policy retrieval.',
      reasons: [],
      confidence: { value: 0.95, basis: 'Deterministic structuring.' },
      data_references: [],
      narrative: 'Storm damage to the roof.',
      narrative_source: 'gemini',
      is_recommendation_only: true,
      narration_governance: {
        action: 'proceed',
        permitted: true,
        gate: 'llm-narration',
        llm_called: true,
        provider: 'gemini',
        model: 'gemini-3.8-flash',
        degraded: false,
      },
    },
    policy: {
      agent: 'policy',
      status: 'complete',
      findings: [],
      recommendation: 'Proceed to validation.',
      reasons: [],
      confidence: { value: 0.9, basis: 'Read from the record.' },
      data_references: [],
      narrative: null,
      narrative_source: 'blocked by governance',
      is_recommendation_only: true,
      narration_governance: {
        action: 'blocked',
        permitted: false,
        gate: 'llm-narration',
        llm_called: false,
        invariant_violated: 'no-customer-data-egress',
        terminal_state: 'claim-automation-suspended',
        reason: 'Identifiable policyholder data in the outbound payload.',
      },
    },
  },
}

describe('the LLM commitment gate in the console', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT_WITH_LLM_GATE)
  })

  const runAnalysis = async (user) => {
    await user.click(screen.getByRole('button', { name: /claims console/i }))
    await user.type(screen.getByLabelText(/claim reference/i), 'CLM-2026-004217')
    await user.click(screen.getByRole('button', { name: /^run analysis$/i }))
  }

  it('shows PERMITTED/EXECUTED and DENIED/BLOCKED as separate facts', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect(await screen.findByText('PERMITTED')).toBeInTheDocument()
    expect(screen.getByText('DENIED')).toBeInTheDocument()
    expect(screen.getByText('EXECUTED')).toBeInTheDocument()
    expect(screen.getByText('BLOCKED')).toBeInTheDocument()
  })

  it('says plainly that a blocked call was never made', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect(
      (await screen.findAllByText(/never contacted|never made/i)).length,
    ).toBeGreaterThan(0)
    // Said twice by design: once on the blocked agent, once in the run summary.
    // It is the sentence the whole refactor exists to make true.
    expect(
      screen.getAllByText(/no request was built and no key was read/i).length,
    ).toBeGreaterThanOrEqual(2)
  })

  it('names the Invariant and the terminal state for the blocked call', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect(
      (await screen.findAllByText(/no-customer-data-egress/)).length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByText(/claim-automation-suspended/).length,
    ).toBeGreaterThan(0)
  })

  it('shows the model without ever showing a key', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect((await screen.findAllByText(/gemini-3\.8-flash/)).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toMatch(/AIza/)
  })

  it('summarises how many calls were permitted and how many were blocked', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect(
      await screen.findByText(/1 permitted · 1 blocked/),
    ).toBeInTheDocument()
  })
})


// =========================================================================
// The three verdicts must never be merged
// =========================================================================

const REPORT_42K = {
  ...REPORT_WITH_LLM_GATE,
  claim_id: 'CLM-2026-042000',
  routing: {
    outcome: 'HUMAN_REVIEW_REQUIRED',
    priority: 'high',
    review_type: 'manual_review',
    reasons: [],
    summary: 'Human review required — above the automated authority limit.',
  },
  llm_governance: {
    ...REPORT_WITH_LLM_GATE.llm_governance,
    governed_calls: 5,
    permitted: 5,
    blocked: 0,
    invariants_violated: [],
    terminal_states: [],
  },
  agent_results: { intake: REPORT_WITH_LLM_GATE.agent_results.intake },
  governance: {
    action: 'action_denied',
    permitted: false,
    automated_action_allowed: false,
    automated_action_attempted: false,
    observed_value: 42000,
    threshold_value: 20000,
    decision_id: 'dec-42k',
    claim_id: 'CLM-2026-042000',
    specification: 'home-storm-claims-automation v0.4.0-poc',
    pre_node: 'automation-confidence',
    pre_node_denied: false,
    invariant_violated: 'automated-authority-limit',
    terminal_state: null,
    assurance_level: 'LOW',
    ledger_entry_ids: ['a', 'b', 'c'],
    side_effect_performed: false,
    automation_suspended: false,
  },
}

describe('a NZD 42,000 claim', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client, 'analyseClaim').mockResolvedValue(REPORT_42K)
  })

  const runAnalysis = async (user) => {
    await user.click(screen.getByRole('button', { name: /claims console/i }))
    await user.type(screen.getByLabelText(/claim reference/i), 'CLM-2026-042000')
    await user.click(screen.getByRole('button', { name: /^run analysis$/i }))
  }

  it('never shows the automated action as permitted', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    const strip = (await screen.findByLabelText('Automated action governance'))
    expect(within(strip).getByText(/DENIED/)).toBeInTheDocument()
    expect(within(strip).queryByText(/^PERMITTED/)).not.toBeInTheDocument()
    expect(within(strip).getByText(/BLOCKED/)).toBeInTheDocument()
  })

  it('names INV-02 and shows the value against the limit', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    const strip = await screen.findByLabelText('Automated action governance')
    expect(within(strip).getByText(/automated-authority-limit/)).toBeInTheDocument()
    expect(within(strip).getByText(/\$42,000/)).toBeInTheDocument()
    expect(within(strip).getByText(/\$20,000/)).toBeInTheDocument()
  })

  it('keeps business routing, LLM governance and action governance distinct', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    // Business routing: a person. Both phrases appear more than once by design
    // -- "Human review required" as the routing outcome value AND inside the
    // summary sentence; "Business routing" in the routing line AND twice in the
    // governance strip's explanation of how the two differ -- so match all of
    // them, then scope the authority assertion to the routing line itself.
    const routingMentions = await screen.findAllByText(/Human Review Required/i)
    expect(routingMentions.length).toBeGreaterThanOrEqual(2)
    const routingAuthority = document.querySelector('.recommendation__authority')
    expect(routingAuthority).toHaveTextContent(/Business routing/)
    expect(routingAuthority).toHaveTextContent(/not by governance/)

    // LLM governance: permitted, and the call executed.
    expect(screen.getByText('PERMITTED')).toBeInTheDocument()
    expect(screen.getByText('EXECUTED')).toBeInTheDocument()

    // Automated action governance: denied.
    const strip = screen.getByLabelText('Automated action governance')
    expect(within(strip).getByText(/DENIED/)).toBeInTheDocument()
  })

  it('explains that nothing is suspended when routing and governance agree', async () => {
    const user = userEvent.setup()
    render(<App />)
    await runAnalysis(user)

    expect(
      await screen.findByText(/governance and the business rules agree/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Terminal state:/)).not.toBeInTheDocument()
  })
})
