import { useState } from 'react'
import ClaimsAssistant from './assistant/ClaimsAssistant.jsx'
import ClaimWizard from './claim/ClaimWizard.jsx'
import StaffConsole from './staff/StaffConsole.jsx'

/**
 * Three experiences, deliberately separated.
 *
 *   assistant — Phase 5. The conversational FNOL journey, and the default: a
 *               customer should be able to say what happened rather than fill
 *               in a form.
 *   form      — the original six-step wizard, KEPT. It is the accessible
 *               fallback and the thing every Phase 1-4 test still exercises;
 *               deleting a working journey to make a new one look like the only
 *               option is not an improvement.
 *   staff     — the claims console. Internal analysis, clearly marked.
 *
 * The customer views show nothing internal: no risk indicators, no policy
 * interpretation, no confidence scores, and no governance vocabulary.
 *
 * The separation is architectural, not enforced: there is no authentication,
 * and the switch below is a demonstration affordance. Phase 6 adds identity and
 * access management.
 */
export default function App() {
  const [view, setView] = useState('assistant')
  const isStaff = view === 'staff'

  return (
    <div className={`app${isStaff ? ' app--staff' : ''}`}>
      <header className="masthead">
        <div className="masthead__inner">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true" />
            <span className="brand__name">Insurance Claims</span>
          </div>

          <nav className="viewswitch" aria-label="Demonstration views">
            <button
              type="button"
              className={`viewswitch__btn${view === 'assistant' ? ' viewswitch__btn--active' : ''}`}
              onClick={() => setView('assistant')}
              aria-pressed={view === 'assistant'}
            >
              Claims assistant
            </button>
            <button
              type="button"
              className={`viewswitch__btn${view === 'form' ? ' viewswitch__btn--active' : ''}`}
              onClick={() => setView('form')}
              aria-pressed={view === 'form'}
            >
              Claim form
            </button>
            <button
              type="button"
              className={`viewswitch__btn${isStaff ? ' viewswitch__btn--active' : ''}`}
              onClick={() => setView('staff')}
              aria-pressed={isStaff}
            >
              Claims console
            </button>
          </nav>
        </div>
      </header>

      {isStaff ? (
        <div className="internal-banner" role="note">
          Internal view — claims staff. Not visible to customers.
        </div>
      ) : null}

      <main className="main">
        <div className="main__inner">
          {isStaff ? (
            <StaffConsole />
          ) : view === 'form' ? (
            <ClaimWizard />
          ) : (
            <ClaimsAssistant />
          )}
        </div>
      </main>

      <footer className="footer">
        <div className="footer__inner">
          <p>
            Proof of concept — synthetic data only. No real insurer, customer, policy or
            claim data is used. AI output is analysis and recommendation only; no claim is
            approved, declined or settled by this system.
          </p>
        </div>
      </footer>
    </div>
  )
}
