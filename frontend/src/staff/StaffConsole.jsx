/**
 * Claims console. INTERNAL — claims staff only.
 *
 * Three tabs since Phase 4: analyse a claim, work the review queue, and read the
 * governance record. Kept in its own folder, behind its own view, with its own
 * visual treatment, because it shows policy interpretation, risk indicators and
 * vulnerability flags that must never reach a customer. There is no
 * authentication in the POC — that is Phase 6, and it is stated on screen rather
 * than assumed away.
 */

import { useState } from 'react'
import { Alert, Field, TextInput } from '../components/FormControls.jsx'
import { analyseClaim } from '../api/client.js'
import IntelligenceReport from './IntelligenceReport.jsx'
import ReviewQueue from './ReviewQueue.jsx'
import ClaimReview from './ClaimReview.jsx'
import GovernanceDashboard from './GovernanceDashboard.jsx'

const TABS = [
  { id: 'analyse', label: 'Analyse a claim' },
  { id: 'queue', label: 'Review queue' },
  { id: 'governance', label: 'Governance' },
]

function AnalyseTab() {
  const [claimId, setClaimId] = useState('')
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)

  const run = async ({ force }) => {
    const reference = claimId.trim()
    if (!reference) {
      setError({ message: 'Enter a claim reference to analyse.' })
      return
    }

    setRunning(true)
    setError(null)
    try {
      setReport(await analyseClaim(reference, { force }))
    } catch (apiError) {
      setReport(null)
      setError({ message: apiError.message })
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <h1 id="console-heading">Claims console</h1>
      <p className="lede">
        Run the claims intelligence workflow over a submitted claim. The agents analyse
        it, the routing rules decide where it goes, and a claim needing a person is
        moved to Human Review and placed in the queue.
      </p>

      <div className="console-form">
        <Field
          label="Claim reference"
          htmlFor="claim_reference"
          hint="For example CLM-2026-138004"
        >
          <TextInput
            id="claim_reference"
            value={claimId}
            onChange={setClaimId}
            hint="reference"
            placeholder="CLM-2026-000000"
          />
        </Field>

        <div className="console-actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => run({ force: false })}
            disabled={running}
          >
            {running ? 'Running…' : 'Run analysis'}
          </button>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => run({ force: true })}
            disabled={running}
          >
            Re-run
          </button>
        </div>
      </div>

      {error ? (
        <Alert tone="error" title="The analysis could not be run">
          <p>{error.message}</p>
        </Alert>
      ) : null}

      {report ? <IntelligenceReport report={report} /> : null}

      {!report && !error ? (
        <p className="muted console-hint">
          Lodge a claim in the customer portal first, then paste its reference here.
        </p>
      ) : null}
    </>
  )
}

export default function StaffConsole() {
  const [tab, setTab] = useState('analyse')
  const [openClaimId, setOpenClaimId] = useState(null)

  if (openClaimId) {
    return (
      <ClaimReview
        claimId={openClaimId}
        onBack={() => setOpenClaimId(null)}
      />
    )
  }

  return (
    <>
      <nav className="tabs" aria-label="Claims console sections">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={`tabs__btn${tab === entry.id ? ' tabs__btn--active' : ''}`}
            onClick={() => setTab(entry.id)}
            aria-pressed={tab === entry.id}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {tab === 'queue' ? (
        <ReviewQueue onOpenClaim={setOpenClaimId} />
      ) : tab === 'governance' ? (
        <GovernanceDashboard />
      ) : (
        <section className="panel panel--staff" aria-labelledby="console-heading">
          <p className="eyebrow eyebrow--internal">Internal — claims staff</p>
          <AnalyseTab />
          <p className="footnote">
            No authentication protects this view in the POC. Access control for claims
            staff is Phase 6.
          </p>
        </section>
      )}
    </>
  )
}
