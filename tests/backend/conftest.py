"""Shared fixtures for the Phase 1 backend tests.

Tests run against an in-memory repository so nothing touches the development
JSONL store.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.api.dependencies import get_claim_service  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.claim_repository import InMemoryClaimRepository  # noqa: E402
from app.services.claim_service import ClaimService  # noqa: E402

# Phase 2 fixtures live in their own module so the Phase 1 set stays untouched.
from tests.backend.conftest_phase2 import *  # noqa: E402,F401,F403

# Phase 4 governance fixtures, likewise. The ledger isolation there is autouse
# and applies to the whole suite: every phase's tests now run the gate, and a
# test run must not append to a real ledger.
from tests.backend.conftest_phase4 import *  # noqa: E402,F401,F403

# Phase 5 conversational-assistant fixtures.
from tests.backend.conftest_phase5 import *  # noqa: E402,F401,F403


@pytest.fixture
def repository() -> InMemoryClaimRepository:
    return InMemoryClaimRepository()


@pytest.fixture
def client(repository: InMemoryClaimRepository) -> TestClient:
    app.dependency_overrides[get_claim_service] = lambda: ClaimService(repository)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def valid_fnol() -> dict:
    """A complete storm-damage FNOL, matching docs/SYNTHETIC_DATA_SPEC.md 4.2."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    return {
        "customer": {
            "full_name": "Marama Whitcombe",
            "email": "m.whitcombe@example.invalid",
            "phone": "+64 20 900 0142",
            "policy_number": "POL-HOME-20117",
            "preferred_contact_method": "email",
        },
        "property": {
            "loss_address": {
                "address_line_1": "18 Kauri Point Road",
                "suburb": "Titirangi",
                "city": "Auckland",
                "postcode": "0604",
            },
            "property_habitable": True,
            "temporary_accommodation_needed": False,
        },
        "damage": {
            "date_of_loss": yesterday,
            "time_of_loss": "21:30:00",
            "peril": "storm",
            "incident_description": (
                "Overnight storm tore tiles off the north side of the roof and "
                "water came through the ceiling in the back bedroom."
            ),
            "damaged_items": [
                {
                    "area": "Roof",
                    "item": "Roof tiles",
                    "description": "Around fifteen tiles lifted and broken on the north slope.",
                    "estimated_value": 3200,
                }
            ],
            "damage_ongoing": False,
            "anyone_injured": False,
            "utilities_affected": [],
            "emergency_repairs_done": True,
            "third_party_involved": False,
            "photos_supplied": True,
            "customer_estimated_value": 4200,
        },
    }
