import { useCallback, useEffect, useRef, useState } from 'react'
import {
  confirmConversation,
  getConversation,
  sendAssistantMessage,
  startConversation,
} from '../api/client.js'

/**
 * The AI Insurance Claims Assistant — the customer's whole journey.
 *
 * WHAT A CUSTOMER SEES, AND WHAT THEY DO NOT
 *
 * They see a conversation, what has been collected, what is still needed, how
 * far along they are, a summary, and a confirmation step. They do not see VSL,
 * Gamma, a PreNode, an Invariant, the VerbaLedger, or the name of any agent.
 * Every turn response carries a `governance` object; this component never
 * reads it. Governance belongs in the claims console.
 *
 * NOTHING IS SUBMITTED UNTIL THE CUSTOMER PRESSES SUBMIT
 *
 * Typing "yes" does not lodge a claim. The Submit button calls a different
 * endpoint, and it only appears once the backend reports `claim_ready`. So the
 * customer's intent to submit is a deliberate action, not a phrase a model
 * decided was affirmative.
 */
export default function ClaimsAssistant() {
  const [conversation, setConversation] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState(true)
  const [error, setError] = useState(null)
  const [created, setCreated] = useState(null)

  const endRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    startConversation()
      .then((turn) => {
        if (cancelled) return
        setConversation(turn.conversation)
        setMessages(turn.conversation.messages ?? [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setStarting(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, busy])

  const send = useCallback(
    async (event) => {
      event?.preventDefault?.()
      const text = draft.trim()
      if (!text || busy || !conversation) return

      setError(null)
      setBusy(true)
      // Show the customer's own message immediately. The server echoes the
      // authoritative transcript back; this is only so the UI does not appear
      // to swallow what they typed while the turn is in flight.
      setMessages((current) => [...current, { role: 'customer', text }])
      setDraft('')

      try {
        const turn = await sendAssistantMessage(conversation.conversation_id, text)
        setConversation(turn.conversation)
        setMessages(turn.conversation.messages ?? [])
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
        inputRef.current?.focus?.()
      }
    },
    [busy, conversation, draft],
  )

  const submitClaim = useCallback(async () => {
    if (!conversation || busy) return
    setError(null)
    setBusy(true)
    try {
      const result = await confirmConversation(conversation.conversation_id)
      setCreated(result)
      setConversation(result.conversation)
      setMessages(result.conversation.messages ?? [])
    } catch (err) {
      setError(err.message)
      // Re-read the state: a refusal means the server knows something the UI
      // does not, and guessing at it would show the wrong buttons.
      try {
        setConversation(await getConversation(conversation.conversation_id))
      } catch {
        /* the error above is the one worth showing */
      }
    } finally {
      setBusy(false)
    }
  }, [busy, conversation])

  if (starting) {
    return (
      <section className="assistant" aria-label="AI Insurance Claims Assistant">
        <p className="assistant__loading" role="status">
          Connecting you to the claims assistant…
        </p>
      </section>
    )
  }

  if (!conversation) {
    return (
      <section className="assistant" aria-label="AI Insurance Claims Assistant">
        <div className="alert alert--error" role="alert">
          <p className="alert__title">We could not start a conversation</p>
          <p>{error ?? 'Please refresh the page and try again.'}</p>
        </div>
      </section>
    )
  }

  const ready = conversation.claim_ready && !created
  const done = Boolean(created)

  return (
    <section className="assistant" aria-label="AI Insurance Claims Assistant">
      <header className="assistant__header">
        <div>
          <h1 className="assistant__title">Claims assistant</h1>
          <p className="assistant__subtitle">
            Tell us what happened in your own words. We&apos;ll ask for anything
            we still need.
          </p>
        </div>
        <Progress
          collected={conversation.collected_count}
          total={conversation.required_count}
          done={done}
        />
      </header>

      <div className="assistant__body">
        <div className="assistant__conversation">
          <div className="assistant__thread" role="log" aria-live="polite">
            {messages.map((message, index) => (
              <Bubble key={index} role={message.role} text={message.text} />
            ))}
            {busy ? (
              <div className="bubble bubble--assistant bubble--typing" role="status">
                <span className="bubble__dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="sr-only">The assistant is typing</span>
              </div>
            ) : null}
            <div ref={endRef} />
          </div>

          {error ? (
            <div className="alert alert--error" role="alert">
              <p className="alert__title">Something went wrong</p>
              <p>{error}</p>
            </div>
          ) : null}

          {done ? (
            <ClaimCreated created={created} />
          ) : ready ? (
            <ConfirmationBar onSubmit={submitClaim} busy={busy} />
          ) : (
            <form className="assistant__composer" onSubmit={send}>
              <label className="sr-only" htmlFor="assistant-input">
                Your message
              </label>
              <textarea
                id="assistant-input"
                ref={inputRef}
                className="assistant__input"
                rows={2}
                value={draft}
                placeholder="Type your answer…"
                disabled={busy}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) send(event)
                }}
              />
              <button
                type="submit"
                className="btn btn--primary assistant__send"
                disabled={busy || !draft.trim()}
              >
                {busy ? 'Sending…' : 'Send'}
              </button>
            </form>
          )}
        </div>

        <aside className="assistant__panel" aria-label="Claim details so far">
          <Collected items={conversation.collected_information} />
          <Missing items={conversation.missing_information} />
          <Uncertain items={conversation.uncertain_information} />
          <p className="assistant__authority">{conversation.assistant_authority_note}</p>
        </aside>
      </div>
    </section>
  )
}

function Progress({ collected, total, done }) {
  const pct = total ? Math.round((collected / total) * 100) : 0
  return (
    <div className="assistant__progress">
      <div
        className="assistant__progressbar"
        role="progressbar"
        aria-valuenow={done ? total : collected}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label="Claim details collected"
      >
        <span style={{ width: `${done ? 100 : pct}%` }} />
      </div>
      <p className="assistant__progresstext">
        {done ? 'Claim submitted' : `${collected} of ${total} details collected`}
      </p>
    </div>
  )
}

function Bubble({ role, text }) {
  const mine = role === 'customer'
  return (
    <div className={`bubble bubble--${mine ? 'customer' : 'assistant'}`}>
      <span className="bubble__who">{mine ? 'You' : 'Claims assistant'}</span>
      <p className="bubble__text">{text}</p>
    </div>
  )
}

function Collected({ items }) {
  if (!items?.length) {
    return (
      <div className="panel">
        <h2 className="panel__title">Your claim so far</h2>
        <p className="panel__empty">Nothing recorded yet — tell us what happened.</p>
      </div>
    )
  }
  return (
    <div className="panel">
      <h2 className="panel__title">Your claim so far</h2>
      <dl className="panel__list">
        {items.map((item) => (
          <div className="panel__row" key={item.field}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function Missing({ items }) {
  if (!items?.length) return null
  return (
    <div className="panel panel--missing">
      <h2 className="panel__title">Still to come</h2>
      <ul className="panel__tags">
        {items.map((item) => (
          <li key={item.field}>{item.label}</li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Shown separately from "still to come" on purpose.
 *
 * "We have not asked yet" and "you told us and we could not use it" mean
 * different things to a customer, and merging them makes the assistant look
 * like it was not listening.
 */
function Uncertain({ items }) {
  if (!items?.length) return null
  return (
    <div className="panel panel--uncertain">
      <h2 className="panel__title">We need to check</h2>
      <ul className="panel__checks">
        {items.map((item) => (
          <li key={item.field}>
            <strong>{item.label}</strong>
            <span className="panel__said">You said: “{item.said}”</span>
            <span className="panel__why">{item.why}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConfirmationBar({ onSubmit, busy }) {
  return (
    <div className="assistant__confirm" role="region" aria-label="Confirm your claim">
      <p className="assistant__confirmtext">
        Please check the summary above. Nothing has been submitted yet.
      </p>
      <button
        type="button"
        className="btn btn--primary"
        onClick={onSubmit}
        disabled={busy}
      >
        {busy ? 'Submitting…' : 'Submit this claim'}
      </button>
    </div>
  )
}

function ClaimCreated({ created }) {
  return (
    <div className="assistant__created" role="status">
      <p className="assistant__createdlabel">Claim submitted</p>
      <p className="assistant__claimid">{created.claim_id}</p>
      <p className="assistant__creatednote">
        Keep this reference. A claims specialist will review the details you
        provided and contact you about what happens next.
      </p>
      <p className="assistant__poc">{created.poc_note}</p>
    </div>
  )
}
