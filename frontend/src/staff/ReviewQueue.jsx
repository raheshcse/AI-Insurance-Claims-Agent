/**
 * Human review queue. INTERNAL — claims staff only.
 *
 * Ordering is not cosmetic: urgent first, then high, then oldest first. A queue
 * that buries the emergency claim under twenty routine ones is worse than no
 * queue, so the backend sorts and the UI shows the priority plainly.
 */

import { useCallback, useEffect, useState } from 'react'
import { Alert } from '../components/FormControls.jsx'
import { getReviewQueue } from '../api/client.js'

const money = (value) =>
  value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat('en-NZ', {
        style: 'currency',
        currency: 'NZD',
        maximumFractionDigits: 0,
      }).format(Number(value))

const titleise = (value) =>
  String(value ?? '')
    .replace(/_/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase())

const STATUS_FILTERS = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_review', label: 'In review' },
  { value: 'closed', label: 'Closed' },
]

export default function ReviewQueue({ onOpenClaim }) {
  const [queue, setQueue] = useState(null)
  const [status, setStatus] = useState('open')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setQueue(await getReviewQueue({ status: status || undefined }))
    } catch (apiError) {
      setQueue(null)
      setError({ message: apiError.message })
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    load()
  }, [load])

  return (
    <section className="panel panel--staff" aria-labelledby="queue-heading">
      <p className="eyebrow eyebrow--internal">Internal — claims staff</p>
      <h1 id="queue-heading">Human review queue</h1>
      <p className="lede">
        Claims the routing rules sent to a person, and why. Urgent first. Nothing in
        this queue has been approved, declined or settled.
      </p>

      <div className="queue-toolbar">
        <div className="queue-filters" role="group" aria-label="Filter by status">
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter.value || 'all'}
              type="button"
              className={`chip-btn${status === filter.value ? ' chip-btn--active' : ''}`}
              onClick={() => setStatus(filter.value)}
              aria-pressed={status === filter.value}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <button type="button" className="btn btn--secondary" onClick={load} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {queue ? (
        <p className="queue-counts">
          <strong>{queue.total}</strong> shown · <strong>{queue.open_count}</strong> awaiting a
          reviewer
          {queue.urgent_count > 0 ? (
            <span className="queue-counts__urgent"> · {queue.urgent_count} urgent</span>
          ) : null}
        </p>
      ) : null}

      {error ? (
        <Alert tone="error" title="The queue could not be loaded">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      {queue && queue.entries.length === 0 ? (
        <p className="muted console-hint">
          Nothing in the queue for this filter. Run an analysis on a claim that needs a
          person and it will appear here.
        </p>
      ) : null}

      <ul className="queue">
        {(queue?.entries ?? []).map((entry) => (
          <li key={entry.queue_id} className={`queue__row queue__row--${entry.priority}`}>
            <div className="queue__main">
              <div className="queue__titleline">
                <button
                  type="button"
                  className="queue__claim"
                  onClick={() => onOpenClaim(entry.claim_id)}
                >
                  {entry.claim_id}
                </button>
                <span className={`chip chip--priority chip--${entry.priority}`}>
                  {entry.priority}
                </span>
                {entry.review_type ? (
                  <span className="chip chip--internal">{titleise(entry.review_type)}</span>
                ) : null}
                <span className={`status-tag status-tag--${entry.queue_status}`}>
                  {titleise(entry.queue_status)}
                </span>
                {entry.automation_suspended ? (
                  <span className="chip chip--deny">Automation suspended</span>
                ) : null}
              </div>

              <p className="queue__reason">
                <strong>{entry.primary_reason_label ?? 'Escalated'}</strong>
                {entry.reason_count > 1 ? (
                  <span className="muted"> · +{entry.reason_count - 1} more reason(s)</span>
                ) : null}
              </p>

              <p className="queue__meta">
                {entry.customer_name} · {entry.policy_number} · {entry.date_of_loss} ·{' '}
                {money(entry.estimated_claim_value)} · complexity{' '}
                {entry.complexity_band ?? '—'} · risk {entry.risk_level ?? '—'}
                {entry.confidence !== null && entry.confidence !== undefined
                  ? ` · confidence ${(entry.confidence * 100).toFixed(0)}%`
                  : ''}
              </p>
            </div>

            <div className="queue__side">
              <span className="status-pill">{entry.claim_state}</span>
              {entry.assigned_to ? (
                <span className="muted">with {entry.assigned_to}</span>
              ) : null}
              <button
                type="button"
                className="btn btn--secondary btn--small"
                onClick={() => onOpenClaim(entry.claim_id)}
              >
                Review
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
