import { useMemo, useState } from 'react'
import ProgressSteps from '../components/ProgressSteps.jsx'
import { Alert } from '../components/FormControls.jsx'
import { submitClaim } from '../api/client.js'
import {
  STEPS,
  createEmptyClaim,
  hasEmergencySignal,
  toSubmissionPayload,
} from './claimForm.js'
import { hasErrors, validateStep } from './validation.js'
import StartStep from './steps/StartStep.jsx'
import CustomerStep from './steps/CustomerStep.jsx'
import PropertyStep from './steps/PropertyStep.jsx'
import DamageStep from './steps/DamageStep.jsx'
import ReviewStep from './steps/ReviewStep.jsx'
import ConfirmationStep from './steps/ConfirmationStep.jsx'

export default function ClaimWizard() {
  const [stepIndex, setStepIndex] = useState(0)
  const [claim, setClaim] = useState(createEmptyClaim)
  const [errors, setErrors] = useState({})
  const [submitError, setSubmitError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  const step = STEPS[stepIndex]
  const showEmergencyNotice = useMemo(() => hasEmergencySignal(claim), [claim])

  const goTo = (index) => {
    setErrors({})
    setStepIndex(index)
    if (typeof window !== 'undefined' && window.scrollTo) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const goToStepId = (stepId) => {
    const index = STEPS.findIndex((candidate) => candidate.id === stepId)
    if (index >= 0) goTo(index)
  }

  const handleNext = () => {
    const stepErrors = validateStep(step.id, claim)
    if (hasErrors(stepErrors)) {
      setErrors(stepErrors)
      return
    }
    goTo(stepIndex + 1)
  }

  const handleBack = () => goTo(Math.max(0, stepIndex - 1))

  const handleSubmit = async () => {
    // Re-validate every data step, not just the current one: the customer may
    // have edited an earlier step from the review screen.
    const combined = ['customer', 'property', 'damage'].reduce((acc, id) => {
      const stepErrors = validateStep(id, claim)
      return hasErrors(stepErrors) ? { ...acc, [id]: stepErrors } : acc
    }, {})

    if (hasErrors(combined)) {
      const firstStep = Object.keys(combined)[0]
      setErrors(combined[firstStep])
      goToStepId(firstStep)
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    try {
      const response = await submitClaim(toSubmissionPayload(claim))
      setResult(response)
    } catch (error) {
      setSubmitError({ message: error.message, fields: error.fields })
    } finally {
      setSubmitting(false)
    }
  }

  const handleStartAnother = () => {
    setClaim(createEmptyClaim())
    setResult(null)
    setSubmitError(null)
    setErrors({})
    setStepIndex(0)
  }

  if (result) {
    return <ConfirmationStep result={result} onStartAnother={handleStartAnother} />
  }

  return (
    <>
      {stepIndex > 0 ? <ProgressSteps steps={STEPS} currentIndex={stepIndex} /> : null}

      {hasErrors(errors) && step.id !== 'start' ? (
        <Alert tone="error" title="Please check the highlighted fields">
          <p>We need a little more before we can continue.</p>
        </Alert>
      ) : null}

      {step.id === 'start' ? <StartStep onStart={() => goTo(1)} /> : null}

      {step.id === 'customer' ? (
        <CustomerStep
          customer={claim.customer}
          errors={errors}
          onChange={(customer) => setClaim({ ...claim, customer })}
        />
      ) : null}

      {step.id === 'property' ? (
        <PropertyStep
          property={claim.property}
          errors={errors}
          onChange={(property) => setClaim({ ...claim, property })}
        />
      ) : null}

      {step.id === 'damage' ? (
        <DamageStep
          damage={claim.damage}
          errors={errors}
          onChange={(damage) => setClaim({ ...claim, damage })}
          showSafetyNotice={showEmergencyNotice}
        />
      ) : null}

      {step.id === 'review' ? (
        <ReviewStep claim={claim} onEditStep={goToStepId} submitError={submitError} />
      ) : null}

      {step.id !== 'start' ? (
        <div className="wizard-actions">
          <button type="button" className="btn btn--secondary" onClick={handleBack}>
            Back
          </button>

          {step.id === 'review' ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? 'Submitting…' : 'Submit claim'}
            </button>
          ) : (
            <button type="button" className="btn btn--primary" onClick={handleNext}>
              Continue
            </button>
          )}
        </div>
      ) : null}
    </>
  )
}
