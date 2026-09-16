"""Access to the synthetic reference datasets.

Everything here is synthetic (docs/SYNTHETIC_DATA_SPEC.md). The agents depend on
this repository rather than on file paths, so Phase 6 can swap it for a policy
administration system without touching agent logic.

A missing dataset is not an exception: `MissingDatasetError` is raised and the
calling agent degrades honestly rather than the workflow crashing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


class MissingDatasetError(RuntimeError):
    """A required synthetic dataset is absent or unreadable."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Synthetic dataset not available: {name}")
        self.dataset = name


def _read_jsonl(path: Path, name: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise MissingDatasetError(name)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        raise MissingDatasetError(name)
    return records


class SyntheticReferenceData:
    """Reads the synthetic datasets the Phase 2 agents consume."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = Path(directory or get_settings().synthetic_data_dir)

    # -- policies ---------------------------------------------------------

    def policies(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir / "policies.jsonl", "policies")

    def find_policy(self, policy_number: str) -> dict[str, Any] | None:
        wanted = (policy_number or "").strip().upper()
        for policy in self.policies():
            if str(policy.get("policy_id", "")).upper() == wanted:
                return policy
        return None

    # -- customers --------------------------------------------------------

    def customers(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir / "customers.jsonl", "customers")

    def find_customer(self, customer_id: str) -> dict[str, Any] | None:
        for customer in self.customers():
            if customer.get("customer_id") == customer_id:
                return customer
        return None

    # -- policy wordings --------------------------------------------------

    def wording(self, wording_id: str) -> dict[str, Any] | None:
        for record in _read_jsonl(self._dir / "policy_wordings.jsonl", "policy_wordings"):
            if record.get("wording_id") == wording_id:
                return record
        return None

    def wording_sections(
        self, wording_id: str, *, peril: str, exclusion_codes: list[str]
    ) -> list[dict[str, Any]]:
        """Sections relevant to this peril, plus any named exclusions.

        Retrieval is by structured match, not similarity search. For a POC with a
        single wording that is honest and reproducible; a vector store is a
        later-phase decision, not a Phase 2 requirement.
        """
        record = self.wording(wording_id)
        if not record:
            return []
        wanted_exclusions = set(exclusion_codes)
        relevant = []
        for section in record.get("sections", []):
            applies = section.get("applies_to")
            if applies in {peril, "all"} or section.get("exclusion_code") in wanted_exclusions:
                relevant.append(section)
        return relevant

    # -- historical claims ------------------------------------------------

    def historical_claims(self, customer_id: str) -> list[dict[str, Any]]:
        records = _read_jsonl(self._dir / "historical_claims.jsonl", "historical_claims")
        return [r for r in records if r.get("customer_id") == customer_id]

    # -- risk rules -------------------------------------------------------

    def risk_rules(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._dir / "risk_rules.jsonl", "risk_rules")


@lru_cache
def get_reference_data() -> SyntheticReferenceData:
    return SyntheticReferenceData()
