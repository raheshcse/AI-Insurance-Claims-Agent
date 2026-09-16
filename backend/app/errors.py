"""Application errors.

Every error that reaches a customer is translated into an ErrorDetail with a
stable code and plain-language message. Python exception text and stack traces
never leave the process -- a Phase 1 requirement.
"""

from __future__ import annotations


class ClaimsAppError(Exception):
    """Base class for expected, handled application errors."""

    code = "claims_error"
    customer_message = (
        "Something went wrong while handling your claim. Please try again."
    )
    http_status = 500


class ClaimCreationError(ClaimsAppError):
    code = "claim_creation_failed"
    customer_message = (
        "We could not lodge your claim just now. Nothing has been submitted -- "
        "please try again in a moment."
    )
    http_status = 503


class ClaimNotFoundError(ClaimsAppError):
    code = "claim_not_found"
    customer_message = "We could not find a claim with that reference."
    http_status = 404


class ClaimAnalysisError(ClaimsAppError):
    """The claims intelligence workflow could not complete.

    Fails closed: the message says explicitly that nothing has changed, so a
    failed analysis can never be read as a result.
    """

    code = "claim_analysis_failed"
    customer_message = (
        "The automated analysis could not be completed for this claim. Nothing "
        "about the claim has changed, and it can be reviewed manually."
    )
    http_status = 503


class AnalysisNotFoundError(ClaimsAppError):
    code = "analysis_not_found"
    customer_message = "This claim has not been analysed yet."
    http_status = 404


class QueueEntryNotFoundError(ClaimsAppError):
    code = "review_entry_not_found"
    customer_message = "This claim is not in the human review queue."
    http_status = 404


class InvalidReviewActionError(ClaimsAppError):
    """A review action that the claim state or queue state does not permit.

    Refused rather than forced: the claim state model is authoritative, and a
    reviewer being told why is better than a claim quietly ending up somewhere
    the lifecycle does not allow.
    """

    code = "invalid_review_action"
    customer_message = "That review action is not available for this claim."
    http_status = 409

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.customer_message)
        if message:
            self.customer_message = message
