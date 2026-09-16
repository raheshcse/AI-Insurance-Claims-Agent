"""Business thresholds used by the Phase 2 agents.

=============================================================================
EVERY VALUE HERE IS A POC PROPOSAL, NOT AN INSURER-APPROVED THRESHOLD.

They come from docs/DECISION_TABLE.md, where each is tagged [POC-PROPOSED] and
listed in section 7 as requiring business approval. Nothing here should be
presented to a stakeholder as a real insurance rule. Agent outputs carry the
`assumption` marker so the distinction survives into the UI.
=============================================================================

TEMPORARY HOME. docs/GOVERNANCE_POLICY_CATALOGUE.md places the decision
boundary and the authority limit in `governance/policy.py` from Phase 4, where
they become governance policy read by PreNodes and Invariants. Phase 2 needs
them before that module is allowed to exist, so they live here and read the
same environment variables. Phase 4 moves them; nothing else changes, because
every agent reads them through this module rather than inlining numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Thresholds:
    """POC-proposed business thresholds. Currency: NZD."""

    # -- Value bands (docs/DECISION_TABLE.md 2.4) -------------------------
    low_value_automation_band: float = field(
        default_factory=lambda: _float_env("LOW_VALUE_AUTOMATION_BAND_NZD", 5_000)
    )
    high_value_review_threshold: float = field(
        default_factory=lambda: _float_env("HIGH_VALUE_REVIEW_THRESHOLD_NZD", 10_000)
    )
    automated_authority_limit: float = field(
        default_factory=lambda: _float_env("AUTOMATED_AUTHORITY_LIMIT_NZD", 20_000)
    )
    high_complexity_value: float = field(
        default_factory=lambda: _float_env("HIGH_COMPLEXITY_VALUE_NZD", 20_000)
    )

    # -- Confidence (docs/DECISION_TABLE.md 2.2) --------------------------
    # The business decision boundary. In Phase 4 the PreNode's Gamma is computed
    # relative to THIS value, never a hard-coded 0.5.
    decision_threshold: float = field(
        default_factory=lambda: _float_env("DECISION_THRESHOLD", 0.80)
    )
    calibration_error: float = field(
        default_factory=lambda: _float_env("CONFIDENCE_CALIBRATION_ERROR", 0.10)
    )

    # -- Complexity (docs/DECISION_TABLE.md 2.1) --------------------------
    low_complexity_max_items: int = field(
        default_factory=lambda: _int_env("LOW_COMPLEXITY_MAX_ITEMS", 1)
    )
    high_complexity_min_items: int = field(
        default_factory=lambda: _int_env("HIGH_COMPLEXITY_MIN_ITEMS", 3)
    )

    # -- Risk banding (docs/DECISION_TABLE.md 2.3) ------------------------
    risk_medium_indicator_count: int = field(
        default_factory=lambda: _int_env("RISK_MEDIUM_INDICATOR_COUNT", 1)
    )
    risk_high_indicator_count: int = field(
        default_factory=lambda: _int_env("RISK_HIGH_INDICATOR_COUNT", 2)
    )

    @property
    def effective_confidence_floor(self) -> float:
        """The confidence a claim must reach for the Phase 4 PreNode to pass.

        Derived, not asserted: VSL-Core's ROBUST_GAMMA_DEFAULT_THRESHOLD is 1.1,
        and Gamma is the prediction's odds relative to the odds at the decision
        boundary. Solving gamma >= 1.1 for p at boundary t gives:

            p >= (1.1 * t/(1-t)) / (1 + 1.1 * t/(1-t))

        At t = 0.80 that is 0.8148. Phase 2 does not gate on this -- no PreNode
        exists yet -- but the assessment reports whether a claim clears it, so
        the Phase 4 behaviour is visible before it is enforced.
        """
        t = min(max(self.decision_threshold, 1e-6), 1 - 1e-6)
        boundary_odds = t / (1 - t)
        required_odds = 1.1 * boundary_odds
        return required_odds / (1 + required_odds)


def get_thresholds() -> Thresholds:
    """Read thresholds fresh so tests and demos can vary them via the env."""
    return Thresholds()


# Marker attached to every agent finding derived from a value above, so the
# distinction between "POC assumption" and "insurer rule" survives into the API
# response and the UI.
POC_ASSUMPTION_NOTE = (
    "POC-proposed threshold pending business approval - not an insurer-approved rule"
)
