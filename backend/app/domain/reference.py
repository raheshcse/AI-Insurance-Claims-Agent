"""Claim reference generation.

Format: CLM-YYYY-NNNNNN  (docs/SYNTHETIC_DATA_SPEC.md section 4.1)

[POC-PROPOSED] The reference format is a Phase 0 proposal and is not an
insurer-approved scheme. It is isolated here so it can be replaced in one place.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

CLAIM_REFERENCE_PREFIX = "CLM"
_SEQUENCE_DIGITS = 6
_SEQUENCE_UPPER_BOUND = 10**_SEQUENCE_DIGITS


def generate_claim_reference(now: datetime | None = None) -> str:
    """Generate a unique-enough synthetic claim reference for the POC.

    Uses a cryptographically strong random suffix rather than a counter, because
    the POC store is file-backed and has no sequence. A production system would
    take this from the claims system of record.
    """
    moment = now or datetime.now(timezone.utc)
    sequence = secrets.randbelow(_SEQUENCE_UPPER_BOUND)
    return f"{CLAIM_REFERENCE_PREFIX}-{moment.year}-{sequence:0{_SEQUENCE_DIGITS}d}"
