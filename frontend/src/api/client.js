/**
 * Backend client.
 *
 * The UI never talks to a model or to a data store directly -- everything goes
 * through the FastAPI backend. That boundary is what lets Phase 4 put a
 * governance gate behind the API without the frontend changing.
 */

const API_BASE_URL = (
  import.meta.env?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export class ApiError extends Error {
  constructor({ code, message, fields }) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.fields = fields ?? null
  }
}

const OFFLINE_MESSAGE =
  'We could not reach our claims service. Your claim has not been submitted. ' +
  'Please check your connection and try again.'

const GENERIC_MESSAGE =
  'Something went wrong while lodging your claim. Your claim has not been ' +
  'submitted. Please try again shortly.'

export async function submitClaim(payload) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/claims`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new ApiError({ code: 'network_error', message: OFFLINE_MESSAGE })
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    throw new ApiError({
      code: body?.error ?? 'submission_failed',
      message: body?.message ?? GENERIC_MESSAGE,
      fields: body?.fields,
    })
  }

  return body
}

const ANALYSIS_MESSAGE =
  'The automated analysis could not be completed. Nothing about the claim has ' +
  'changed, and it can be reviewed manually.'

/**
 * Run the claims intelligence workflow. INTERNAL — claims staff only.
 * Returns a recommendation; it changes nothing about the claim.
 */
export async function analyseClaim(claimId, { force = false } = {}) {
  let response
  try {
    response = await fetch(
      `${API_BASE_URL}/api/claims/${encodeURIComponent(claimId)}/analyze`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force_reanalysis: force }),
      },
    )
  } catch {
    throw new ApiError({ code: 'network_error', message: OFFLINE_MESSAGE })
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    throw new ApiError({
      code: body?.error ?? 'analysis_failed',
      message: body?.message ?? ANALYSIS_MESSAGE,
      fields: body?.fields,
    })
  }

  return body
}

/**
 * The human review queue. INTERNAL — claims staff only.
 */
export async function getReviewQueue({ status, priority } = {}) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (priority) params.set('priority', priority)
  const query = params.toString()

  return requestJson(`${API_BASE_URL}/api/review-queue${query ? `?${query}` : ''}`, {
    fallback: 'The review queue could not be loaded.',
  })
}

/** Everything a reviewer needs for one claim. INTERNAL. */
export async function getClaimReview(claimId) {
  return requestJson(
    `${API_BASE_URL}/api/review-queue/${encodeURIComponent(claimId)}`,
    { fallback: 'This claim could not be loaded for review.' },
  )
}

/**
 * Record a POC review action. INTERNAL.
 * Records what a reviewer decided; it approves, settles and pays nothing.
 */
export async function performReviewAction(claimId, body) {
  return requestJson(
    `${API_BASE_URL}/api/review-queue/${encodeURIComponent(claimId)}/action`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      fallback: 'The review action could not be recorded.',
    },
  )
}

/**
 * Lift a governance TerminalState. INTERNAL — a claims authority only.
 *
 * There is no automatic recovery from a terminal state. This records a named
 * person authorising automation to run again on one claim, with the evidence
 * the framework requires. It decides nothing about the claim itself.
 */
export async function reEnableAutomation(claimId, body) {
  return requestJson(
    `${API_BASE_URL}/api/review-queue/${encodeURIComponent(claimId)}/re-enable-automation`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      fallback: 'Automation could not be re-enabled for this claim.',
    },
  )
}

/**
 * The governance dashboard. INTERNAL — claims staff only.
 * Read-only: nothing under /api/governance changes governance state.
 */
export async function getGovernanceDashboard({ limit } = {}) {
  const query = limit ? `?limit=${encodeURIComponent(limit)}` : ''
  return requestJson(`${API_BASE_URL}/api/governance${query}`, {
    fallback: 'The governance dashboard could not be loaded.',
  })
}

/** One claim's governance trail, oldest first. INTERNAL. */
export async function getGovernanceTrail(claimId) {
  return requestJson(
    `${API_BASE_URL}/api/governance/ledger/${encodeURIComponent(claimId)}`,
    { fallback: 'The governance trail for this claim could not be loaded.' },
  )
}

/** Shared fetch + error translation, so every caller fails the same way. */
async function requestJson(url, { fallback, ...init } = {}) {
  let response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError({ code: 'network_error', message: OFFLINE_MESSAGE })
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    throw new ApiError({
      code: body?.error ?? 'request_failed',
      message: body?.message ?? fallback ?? GENERIC_MESSAGE,
      fields: body?.fields,
    })
  }

  return body
}

export async function getHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`)
    return response.ok
  } catch {
    return false
  }
}

// ---------------------------------------------------------------------------
// Phase 5 — the conversational claims assistant. CUSTOMER-FACING.
//
// The turn responses carry an internal `governance` object. The customer UI
// does not read it: a customer is never shown VSL, Gamma, a PreNode, an
// Invariant or the ledger. It is there for the claims console and the tests.
// ---------------------------------------------------------------------------

const ASSISTANT_MESSAGE =
  'We could not reach the claims assistant. Nothing has been submitted — ' +
  'please try again in a moment.'

/** Open a conversation. Creates no claim. */
export async function startConversation() {
  return requestJson(`${API_BASE_URL}/api/assistant/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
    fallback: ASSISTANT_MESSAGE,
  })
}

/** Send one customer message. NEVER creates a claim, whatever is said. */
export async function sendAssistantMessage(conversationId, message) {
  return requestJson(
    `${API_BASE_URL}/api/assistant/conversations/${encodeURIComponent(
      conversationId,
    )}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      fallback: ASSISTANT_MESSAGE,
    },
  )
}

/** Read the structured conversation state back. */
export async function getConversation(conversationId) {
  return requestJson(
    `${API_BASE_URL}/api/assistant/conversations/${encodeURIComponent(conversationId)}`,
    { fallback: 'We could not load your conversation.' },
  )
}

/**
 * Confirm the summary and create the claim.
 *
 * The ONLY call in this client that creates a claim, and it is reached only
 * when the customer presses Submit after reading the summary.
 */
export async function confirmConversation(conversationId) {
  return requestJson(
    `${API_BASE_URL}/api/assistant/conversations/${encodeURIComponent(
      conversationId,
    )}/confirm`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmed: true }),
      fallback:
        'Your claim could not be submitted. Nothing has been lodged — please try again.',
    },
  )
}
