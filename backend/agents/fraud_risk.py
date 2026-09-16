"""Fraud & Risk Agent.

Evaluates the synthetic risk rules against the claim, the policy and the
customer's claim history, and reports **risk indicators**.

Language is a design constraint here, not a style preference. The requirements
say the system identifies risk without accusing the customer, so this agent:

  * calls its outputs *indicators*, *potential concerns* and *elevated signals*;
  * never says fraud, never says the customer did anything;
  * marks every indicator `customer_visible=False`, structurally;
  * recommends *review*, never a decision.

An indicator is a reason for a person to look. It is not evidence, and two
indicators are not proof of anything.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from agents.base import ClaimsAgent
from agents.contracts import (
    AgentResult,
    AgentStatus,
    Finding,
    RiskIndicator,
    RiskPayload,
    Severity,
)
from app.domain.thresholds import POC_ASSUMPTION_NOTE, Thresholds
from app.repositories.reference_data import MissingDatasetError, SyntheticReferenceData


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


class FraudRiskAgent(ClaimsAgent):
    name = "fraud_risk"

    def __init__(self, llm, reference_data: SyntheticReferenceData, thresholds: Thresholds) -> None:  # noqa: ANN001
        super().__init__(llm)
        self._data = reference_data
        self._t = thresholds

    def analyse(self, context: dict[str, Any]) -> tuple[AgentResult, dict[str, Any] | None]:
        claim = context["claim"]
        fnol = claim.get("fnol") or {}
        damage = fnol.get("damage") or {}

        intake = context.get("intake_payload") or {}
        policy_payload = context.get("policy_payload") or {}
        facts = policy_payload.get("facts") or {}

        try:
            rules = {rule["rule_id"]: rule for rule in self._data.risk_rules()}
        except MissingDatasetError as exc:
            return self._degraded(exc), RiskPayload(risk_level="low").model_dump(mode="json")

        policy_id = facts.get("policy_id")
        policy_record = self._data.find_policy(policy_id) if policy_id else None
        customer_id = policy_record.get("customer_id") if policy_record else None

        history: list[dict[str, Any]] = []
        if customer_id:
            try:
                history = self._data.historical_claims(customer_id)
            except MissingDatasetError:
                history = []

        loss_date = _parse_date(damage.get("date_of_loss"))
        indicators: list[RiskIndicator] = []

        def add(rule_id: str, detail: str, reference: str) -> None:
            rule = rules.get(rule_id)
            if not rule:
                return
            indicators.append(
                RiskIndicator(
                    rule_id=rule_id,
                    name=rule["name"],
                    detail=detail,
                    severity=rule.get("severity", "standard"),
                    data_reference=reference,
                )
            )

        # -- policy-timing signals -----------------------------------------
        if policy_record and loss_date:
            inception = _parse_date(policy_record.get("inception_date"))
            rule = rules.get("RISK-INCEPT-01")
            if inception and rule:
                days = (loss_date - inception).days
                if 0 <= days <= int(rule.get("threshold_days", 60)):
                    add(
                        "RISK-INCEPT-01",
                        f"The loss occurred {days} day(s) after the policy started.",
                        f"policies.jsonl:{policy_record['policy_id']}",
                    )

            change = _parse_date(policy_record.get("recent_cover_change_date"))
            rule = rules.get("RISK-COVER-01")
            if change and rule:
                days = abs((loss_date - change).days)
                if days <= int(rule.get("threshold_days", 45)):
                    add(
                        "RISK-COVER-01",
                        f"Cover was changed {days} day(s) from the date of loss.",
                        f"policies.jsonl:{policy_record['policy_id']}",
                    )

        # -- history signals -------------------------------------------------
        peril = str(damage.get("peril") or "").lower()
        rule = rules.get("RISK-FREQ-01")
        if rule and history:
            window_months = int(rule.get("window_months", 24))
            cutoff_year_months = window_months
            same_peril = []
            for record in history:
                record_date = _parse_date(record.get("date_of_loss"))
                if not record_date or not loss_date:
                    continue
                months_apart = (loss_date.year - record_date.year) * 12 + (
                    loss_date.month - record_date.month
                )
                if 0 <= months_apart <= cutoff_year_months and str(
                    record.get("peril", "")
                ).lower() == peril:
                    same_peril.append(record)
            if len(same_peril) >= int(rule.get("threshold_count", 2)):
                add(
                    "RISK-FREQ-01",
                    f"{len(same_peril)} prior {peril} claim(s) in the last {window_months} months.",
                    "historical_claims.jsonl",
                )

        if any(r.get("outcome") == "declined" for r in history):
            declined = [r for r in history if r.get("outcome") == "declined"]
            add(
                "RISK-DECLINE-01",
                f"{len(declined)} prior claim(s) were declined. Context only.",
                "historical_claims.jsonl",
            )

        if any(r.get("fraud_flag_raised") for r in history):
            add(
                "RISK-PRIORFLAG-01",
                "A prior claim in this history was flagged for review.",
                "historical_claims.jsonl",
            )

        # -- claim-shape signals ----------------------------------------------
        itemised = intake.get("itemised_estimate_total")
        overall = intake.get("customer_estimated_value")
        rule = rules.get("RISK-VALUE-01")
        if rule and itemised and overall and itemised > 0:
            multiplier = float(rule.get("multiplier", 3.0))
            if overall > itemised * multiplier:
                add(
                    "RISK-VALUE-01",
                    (
                        f"The overall estimate (NZD {overall:,.0f}) is more than "
                        f"{multiplier:g}x the itemised total (NZD {itemised:,.0f})."
                    ),
                    "claim.fnol.damage",
                )

        rule = rules.get("RISK-DESC-01")
        words = int(intake.get("description_word_count") or 0)
        if rule and overall and words < int(rule.get("min_words", 15)):
            if overall > self._t.low_value_automation_band:
                add(
                    "RISK-DESC-01",
                    (
                        f"A {words}-word description accompanies an estimate of "
                        f"NZD {overall:,.0f}."
                    ),
                    "claim.fnol.damage.incident_description",
                )

        rule = rules.get("RISK-LIMIT-01")
        sum_insured = facts.get("dwelling_sum_insured")
        if rule and overall and sum_insured:
            ratio = float(rule.get("ratio", 0.8))
            if overall >= float(sum_insured) * ratio:
                add(
                    "RISK-LIMIT-01",
                    (
                        f"The estimate is {overall / float(sum_insured):.0%} of the dwelling "
                        f"sum insured."
                    ),
                    f"policies.jsonl:{facts.get('policy_id')}",
                )

        # -- banding ------------------------------------------------------------
        severe_count = sum(1 for i in indicators if i.severity == "severe")
        if severe_count or len(indicators) >= self._t.risk_high_indicator_count:
            risk_level = "high"
        elif len(indicators) >= self._t.risk_medium_indicator_count:
            risk_level = "medium"
        else:
            risk_level = "low"

        findings = [
            Finding(
                code="RISK_INDICATOR",
                summary=indicator.name,
                severity=Severity.CONCERN if indicator.severity == "severe" else Severity.ATTENTION,
                detail=indicator.detail,
                data_reference=indicator.data_reference,
            )
            for indicator in indicators
        ]
        findings.append(
            Finding(
                code=f"RISK_LEVEL_{risk_level.upper()}",
                summary=f"Overall risk signal: {risk_level}.",
                severity=Severity.INFO if risk_level == "low" else Severity.ATTENTION,
                detail=(
                    f"{len(indicators)} indicator(s), {severe_count} of them severe, banded "
                    f"using proposed POC rules."
                ),
                data_reference="docs/DECISION_TABLE.md 2.3",
                assumption=POC_ASSUMPTION_NOTE,
            )
        )

        if risk_level == "high":
            recommendation = (
                "Refer to a specialist reviewer. Several risk indicators are present and "
                "warrant a closer look before the claim progresses. This is not a finding "
                "of fraud."
            )
            next_step = "specialist_review"
        elif risk_level == "medium":
            recommendation = (
                "A claims specialist should review this claim. One risk indicator is "
                "present, which is a prompt to look rather than a concern in itself."
            )
            next_step = "manual_review"
        else:
            recommendation = "No risk indicators were triggered by the available data."
            next_step = "continue"

        reasons = [
            f"{len(history)} historical claim(s) considered.",
            f"{len(rules)} risk rule(s) evaluated.",
            f"{len(indicators)} indicator(s) triggered.",
        ]

        confidence_value = 0.85 if history else 0.6
        if not policy_record:
            confidence_value = 0.45

        narrative, source, narration_governance = self.narrate(
            context=context,
            purpose="risk indicator summary for a claims employee",
            headline=f"Risk signal: {risk_level}",
            points=reasons + [f"{i.name}: {i.detail}" for i in indicators],
            caveat=(
                "Indicators are prompts to review. They are not evidence of fraud and "
                "must not be shared with or implied to the customer."
            ),
        )

        payload = RiskPayload(
            risk_level=risk_level,
            indicators=indicators,
            historical_claims_considered=len(history),
        )

        result = AgentResult(
            agent=self.name,
            status=AgentStatus.COMPLETE if history or policy_record else AgentStatus.DEGRADED,
            findings=findings,
            recommendation=recommendation,
            reasons=reasons,
            confidence=self.confidence(
                confidence_value,
                basis=(
                    "Rules are deterministic; confidence reflects how much history and "
                    "policy context was available to evaluate them against."
                ),
            ),
            data_references=["risk_rules.jsonl", "historical_claims.jsonl"],
            next_step=next_step,
            narrative=narrative,
            narrative_source=source,
            narration_governance=narration_governance,
        )
        return result, payload.model_dump(mode="json")

    def _degraded(self, exc: MissingDatasetError) -> AgentResult:
        return AgentResult(
            agent=self.name,
            status=AgentStatus.DEGRADED,
            recommendation=(
                "The risk check could not run. A claims specialist should review this "
                "claim rather than treating the absence of indicators as a clear result."
            ),
            reasons=[f"The {exc.dataset} dataset is not available."],
            confidence=None,
            next_step="manual_review",
            error="The risk check could not be completed.",
        )
