export default function ProgressSteps({ steps, currentIndex }) {
  return (
    <nav className="progress" aria-label="Claim progress">
      <ol className="progress__list">
        {steps.map((step, index) => {
          const state =
            index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'upcoming'
          return (
            <li key={step.id} className={`progress__step progress__step--${state}`}>
              <span className="progress__marker" aria-hidden="true">
                {index < currentIndex ? '✓' : index + 1}
              </span>
              <span className="progress__label">{step.label}</span>
              {index === currentIndex ? <span className="sr-only">(current step)</span> : null}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
