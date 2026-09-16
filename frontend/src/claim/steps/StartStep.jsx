export default function StartStep({ onStart }) {
  return (
    <section className="panel" aria-labelledby="start-heading">
      <p className="eyebrow">Home insurance</p>
      <h1 id="start-heading">Make a storm damage claim</h1>
      <p className="lede">
        If storm weather has damaged your home, you can lodge a claim here. It usually
        takes about ten minutes, and you can see everything you have entered before
        you submit it.
      </p>

      <h2 className="subheading">What happens next</h2>
      <ol className="steps-explainer">
        <li>
          <strong>Tell us about the damage.</strong> Your details, the property affected,
          and what the storm damaged.
        </li>
        <li>
          <strong>Review everything.</strong> Check your answers and go back to change
          anything before you submit.
        </li>
        <li>
          <strong>Submit your claim.</strong> We give you a claim reference straight away
          and confirm it has been lodged.
        </li>
        <li>
          <strong>We take it from there.</strong> A claims specialist reviews your claim
          and contacts you about next steps.
        </li>
      </ol>

      <h2 className="subheading">What you will need</h2>
      <ul className="bullets">
        <li>Your policy number</li>
        <li>The date the damage happened</li>
        <li>A description of what was damaged, area by area</li>
        <li>Photos, if you have them — you can add these later too</li>
      </ul>

      <div className="actions">
        <button type="button" className="btn btn--primary" onClick={onStart}>
          Start a claim
        </button>
      </div>

      <p className="footnote">
        If someone is hurt or your home is unsafe, contact emergency services first,
        then call us.
      </p>
    </section>
  )
}
