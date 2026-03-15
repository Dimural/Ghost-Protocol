"""
Ghost Protocol — Police AI Agent

Built-in Blue Team fallback for users who do not provide their own webhook.
Without a Gemini API key it uses deterministic heuristics calibrated against
the Ghost World seed data. When GEMINI_API_KEY is set, the same interface
automatically switches to Gemini and falls back to heuristics on any error.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Iterable

from backend.config import GEMINI_FLASH_MODEL, USE_MOCK_LLM
from backend.data.models import DefenderDecision, Transaction, TransactionType
from backend.gemini_client import GEMINI_CLIENT, summarize_exception

SEED_TRANSACTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "transactions.json"

POLICE_SYSTEM_PROMPT = """
You are a vigilant bank fraud investigator.
You analyze individual transactions and decide if they are fraudulent.

You know the user's recent spending history.
Flag a transaction as suspicious if it:
- Is significantly larger than the user's typical transactions
- Occurs in an unusual location (different country/city from history)
- Happens at an unusual time (3AM-5AM)
- Is in an unusual merchant category for this user
- Follows rapid repeated transactions to same merchant

Be careful not to flag normal behavior — false positives are costly.

Return ONLY: {"decision": "APPROVE" or "DENY", "confidence": 0.0-1.0, "reason": "brief explanation"}
No markdown. Pure JSON only.
""".strip()

POLICE_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["APPROVE", "DENY"],
        },
        "confidence": {
            "type": "number",
        },
        "reason": {
            "type": "string",
        },
    },
    "required": ["decision", "confidence", "reason"],
}


@dataclass
class PoliceBenchmarkResult:
    accuracy: float
    avg_latency_ms: float
    total_transactions: int
    fraud_recall: float
    false_positive_rate: float


@dataclass
class UserBaselineProfile:
    median_amount: float
    max_amount: float
    categories: set[str]
    countries: set[str]
    cities: set[str]
    transaction_types: set[str]


@dataclass
class RiskAssessment:
    score: float
    reasons: list[str]


class PoliceAgent:
    """Built-in fallback defender that scores transactions against user history."""

    def __init__(self) -> None:
        self.system_prompt = POLICE_SYSTEM_PROMPT
        self.last_reasoning: str = ""
        self.last_runtime_mode: str = "mock" if USE_MOCK_LLM else "gemini"
        self._seed_transactions_cache: list[Transaction] | None = None
        self._baseline_profiles_cache: dict[str, UserBaselineProfile] | None = None

    async def evaluate_transaction(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction] | None = None,
    ) -> DefenderDecision:
        recent_transactions = recent_transactions or []

        try:
            if USE_MOCK_LLM:
                decision = self._evaluate_with_rules(transaction, recent_transactions)
                self.last_runtime_mode = "mock"
            else:
                decision = await self._evaluate_with_gemini(transaction, recent_transactions)
                self.last_runtime_mode = "gemini"
        except Exception as exc:
            decision = self._evaluate_with_rules(transaction, recent_transactions)
            self.last_reasoning = (
                f"Gemini evaluation failed: {summarize_exception(exc)}; "
                f"fell back to local heuristic police logic."
            )
            if decision.reason:
                decision.reason = f"{decision.reason} | Gemini fallback engaged."
            self.last_runtime_mode = "mock"

        return decision

    async def benchmark_seed_dataset(
        self,
        transactions: list[Transaction] | None = None,
    ) -> PoliceBenchmarkResult:
        dataset = transactions or self._load_seed_transactions()
        ordered = sorted(dataset, key=lambda tx: tx.timestamp)

        history_by_user: dict[str, list[Transaction]] = defaultdict(list)
        latencies_ms: list[float] = []
        correct = 0
        true_positives = 0
        false_positives = 0
        total_fraud = 0
        total_legit = 0

        for transaction in ordered:
            recent_history = history_by_user[transaction.user_id][-5:]
            started = perf_counter()
            decision = await self.evaluate_transaction(transaction, recent_history)
            latencies_ms.append((perf_counter() - started) * 1000.0)

            predicted_fraud = decision.decision == "DENY"
            if predicted_fraud == transaction.is_fraud:
                correct += 1
            if transaction.is_fraud:
                total_fraud += 1
                if predicted_fraud:
                    true_positives += 1
            else:
                total_legit += 1
                if predicted_fraud:
                    false_positives += 1

            history_by_user[transaction.user_id].append(transaction)

        return PoliceBenchmarkResult(
            accuracy=correct / len(ordered) if ordered else 0.0,
            avg_latency_ms=sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0,
            total_transactions=len(ordered),
            fraud_recall=true_positives / total_fraud if total_fraud else 0.0,
            false_positive_rate=false_positives / total_legit if total_legit else 0.0,
        )

    def _evaluate_with_rules(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
    ) -> DefenderDecision:
        baseline = self._baseline_profile_for_user(transaction.user_id)
        assessment = self._assess_risk(transaction, recent_transactions, baseline)
        decision = "DENY" if assessment.score >= 0.55 else "APPROVE"
        confidence = self._confidence_from_score(assessment.score, decision)
        reason = self._format_reason(assessment.reasons, decision)
        self.last_reasoning = reason
        return DefenderDecision(
            transaction_id=transaction.id,
            decision=decision,
            confidence=confidence,
            reason=reason,
        )

    async def _evaluate_with_gemini(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
    ) -> DefenderDecision:
        payload = await self._run_gemini_prompt(transaction, recent_transactions)
        if isinstance(payload, dict):
            decision_value = payload.get("decision")
            if isinstance(decision_value, str):
                payload["decision"] = decision_value.upper()
            payload["transaction_id"] = transaction.id
            decision = DefenderDecision.model_validate(payload)
            self.last_reasoning = decision.reason or "Gemini produced a defender decision."
            return decision
        raise ValueError("Gemini response did not produce a JSON object.")

    def _assess_risk(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
        baseline: UserBaselineProfile | None,
    ) -> RiskAssessment:
        score = 0.0
        reasons: list[str] = []

        if baseline is not None:
            if transaction.amount > baseline.max_amount * 1.2:
                score += 0.45
                reasons.append("amount is well above this user's normal ceiling")
            elif transaction.amount > baseline.median_amount * 2.8:
                score += 0.25
                reasons.append("amount is much larger than the user's normal spend")

            if transaction.category not in baseline.categories:
                score += 0.30
                reasons.append("merchant category is new for this user")

            if transaction.location_country not in baseline.countries:
                score += 0.45
                reasons.append("transaction country is outside the user's history")
            elif transaction.location_city not in baseline.cities:
                score += 0.25
                reasons.append("transaction city is unusual for this user")

            if transaction.transaction_type.value not in baseline.transaction_types:
                score += 0.20
                reasons.append("transaction type is unusual for this user")

            if (
                transaction.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL)
                and transaction.category not in baseline.categories
            ):
                score += 0.25
                reasons.append("money-movement pattern does not match the user's profile")
        else:
            if transaction.location_country != "Canada":
                score += 0.45
                reasons.append("transaction is outside the expected home country")
            if transaction.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL):
                score += 0.20
                reasons.append("transaction uses a higher-risk money movement channel")
            if transaction.amount > 500:
                score += 0.20
                reasons.append("transaction amount is unusually large")

        recent_assessment = self._assess_recent_velocity(transaction, recent_transactions)
        score += recent_assessment.score
        reasons.extend(recent_assessment.reasons)

        hour = datetime.fromisoformat(transaction.timestamp).hour
        if 3 <= hour <= 5:
            score += 0.15
            reasons.append("transaction happened during a low-trust overnight window")

        return RiskAssessment(score=min(score, 1.0), reasons=reasons)

    def _assess_recent_velocity(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
    ) -> RiskAssessment:
        if not recent_transactions:
            return RiskAssessment(score=0.0, reasons=[])

        score = 0.0
        reasons: list[str] = []

        same_merchant_count = sum(
            1 for prior in recent_transactions if prior.merchant == transaction.merchant
        )
        if same_merchant_count >= 2:
            score += 0.20
            reasons.append("recent history shows repeated hits to the same merchant")

        burst_window = recent_transactions[-3:] + [transaction]
        if len(burst_window) == 4:
            timestamps = [datetime.fromisoformat(item.timestamp) for item in burst_window]
            duration_seconds = (max(timestamps) - min(timestamps)).total_seconds()
            small_amounts = all(item.amount < 60 for item in burst_window)
            limited_merchants = len({item.merchant for item in burst_window}) <= 2
            if duration_seconds <= 45 * 60 and small_amounts and limited_merchants:
                score += 0.20
                reasons.append("recent pattern looks like a micro-transaction burst")

        return RiskAssessment(score=score, reasons=reasons)

    def _baseline_profile_for_user(self, user_id: str) -> UserBaselineProfile | None:
        profiles = self._baseline_profiles()
        return profiles.get(user_id)

    def _baseline_profiles(self) -> dict[str, UserBaselineProfile]:
        if self._baseline_profiles_cache is not None:
            return self._baseline_profiles_cache

        grouped: dict[str, list[Transaction]] = defaultdict(list)
        for transaction in self._load_seed_transactions():
            if transaction.is_fraud:
                continue
            grouped[transaction.user_id].append(transaction)

        profiles: dict[str, UserBaselineProfile] = {}
        for user_id, transactions in grouped.items():
            amounts = [tx.amount for tx in transactions]
            profiles[user_id] = UserBaselineProfile(
                median_amount=median(amounts),
                max_amount=max(amounts),
                categories={tx.category for tx in transactions},
                countries={tx.location_country for tx in transactions},
                cities={tx.location_city for tx in transactions},
                transaction_types={tx.transaction_type.value for tx in transactions},
            )

        self._baseline_profiles_cache = profiles
        return profiles

    def _load_seed_transactions(self) -> list[Transaction]:
        if self._seed_transactions_cache is None:
            payload = json.loads(SEED_TRANSACTIONS_PATH.read_text())
            self._seed_transactions_cache = [Transaction(**row) for row in payload]
        return self._seed_transactions_cache

    async def _run_gemini_prompt(
        self,
        transaction: Transaction,
        recent_transactions: Iterable[Transaction],
    ) -> Any:
        history_summary = self._recent_history_summary(recent_transactions)
        prompt = (
            "Analyze this transaction and return only JSON.\n\n"
            f"Transaction:\n"
            f"- amount: {transaction.amount:.2f} {transaction.currency}\n"
            f"- merchant: {transaction.merchant}\n"
            f"- category: {transaction.category}\n"
            f"- location: {transaction.location_city}, {transaction.location_country}\n"
            f"- transaction_type: {transaction.transaction_type.value}\n"
            f"- timestamp: {transaction.timestamp}\n\n"
            f"Recent history:\n{history_summary}\n"
        )
        return await GEMINI_CLIENT.generate_json(
            model=GEMINI_FLASH_MODEL,
            system_prompt=self.system_prompt,
            prompt=prompt,
            response_schema=POLICE_DECISION_SCHEMA,
            temperature=0.2,
            max_output_tokens=1024,
        )

    def _recent_history_summary(self, recent_transactions: Iterable[Transaction]) -> str:
        recent_list = list(recent_transactions)
        if not recent_list:
            return "- No recent transactions available."
        return "\n".join(
            f"- {tx.timestamp}: {tx.merchant} ${tx.amount:.2f} in {tx.location_city} "
            f"({tx.category}, {tx.transaction_type.value})"
            for tx in recent_list[-5:]
        )

    def _confidence_from_score(self, score: float, decision: str) -> float:
        if decision == "DENY":
            return round(min(0.99, 0.55 + (score * 0.35)), 2)
        return round(max(0.51, 0.95 - (score * 0.45)), 2)

    def _format_reason(self, reasons: list[str], decision: str) -> str:
        unique_reasons = list(dict.fromkeys(reasons))
        if not unique_reasons:
            if decision == "DENY":
                return "Denied due to elevated risk signals."
            return "Approved because the transaction fits the user's normal profile."

        if decision == "DENY":
            return "Denied because " + "; ".join(unique_reasons[:3]) + "."
        return "Approved because no strong fraud signals were detected."

    def _strip_markdown_fences(self, value: str) -> str:
        cleaned = value.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        return cleaned.strip()
