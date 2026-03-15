"""
Ghost Protocol — Police AI Agent

Built-in Blue Team fallback for users who do not provide their own webhook.
Without a Groq API key it uses deterministic heuristics calibrated against
the Ghost World seed data. When GROQ_API_KEY is set, the same interface
automatically switches to Groq and falls back to heuristics on any error.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Iterable

from backend.config import GROQ_API_KEY, USE_MOCK_LLM
from backend.data.models import DefenderDecision, Transaction, TransactionType

SEED_TRANSACTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "transactions.json"
GROQ_POLICE_MODEL = "llama-3.1-8b-instant"
logger = logging.getLogger(__name__)
HIGH_RISK_MERCHANT_KEYWORDS = (
    "wire",
    "transfer",
    "coinbase",
    "crypto",
    "gift card",
    "atm",
    "loan",
    "cash advance",
)

POLICE_SYSTEM_PROMPT = """
You are a bank fraud investigator operating inside an adversarial simulation.
Your primary goal is to catch fraud reliably. False positives matter, but a missed coordinated attack is worse.

You will receive:
- The transaction itself
- Recent transaction history
- User baseline statistics derived from historical behavior
- Backend heuristic risk signals

Decision policy:
- Return DENY when there is 1 severe signal or 2+ moderate signals.
- Severe signals include:
  - first-seen country combined with transfer or withdrawal activity
  - amount above the user's historical max by more than 20%
  - amount above 3x the user's median historical amount
  - rapid micro-transaction bursts
  - unusual location plus unusual category or unusual money-movement channel
  - overnight activity (3AM-5AM) plus any other out-of-pattern behavior
- Moderate signals include:
  - unusual city
  - unusual category
  - unusual transaction type
  - repeated merchant hits
  - concentrated recent spending against a narrow merchant/category set
- If the backend heuristic section says deny_recommended_by_backend=true, only APPROVE if the transaction clearly matches the user's baseline despite those signals.
- If uncertain between APPROVE and DENY, choose DENY in this simulation.

Reasons must reference the concrete signals that drove the decision. Keep the reason short and specific.

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

POLICE_BATCH_DECISION_SCHEMA = {
    "type": "array",
    "items": POLICE_DECISION_SCHEMA,
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
        self.last_runtime_mode: str = "mock" if USE_MOCK_LLM else "groq"
        self._seed_transactions_cache: list[Transaction] | None = None
        self._baseline_profiles_cache: dict[str, UserBaselineProfile] | None = None

    async def evaluate_transaction(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction] | None = None,
    ) -> DefenderDecision:
        decisions = await self.evaluate_batch(
            [transaction],
            recent_history_by_id={transaction.id: recent_transactions or []},
        )
        return decisions[0]

    async def evaluate_batch(
        self,
        transactions: list[Transaction],
        recent_history_by_id: dict[str, list[Transaction]] | None = None,
    ) -> list[DefenderDecision]:
        """
        Evaluate all transactions in one API call instead of one call per transaction.
        In mock mode, falls back to calling _evaluate_with_rules() for each transaction.
        """
        if not transactions:
            return []

        recent_history_by_id = recent_history_by_id or {}

        if USE_MOCK_LLM:
            decisions = [
                self._evaluate_with_rules(transaction, recent_history_by_id.get(transaction.id, []))
                for transaction in transactions
            ]
            self.last_runtime_mode = "mock"
            self.last_reasoning = self._summarize_batch_reasoning(decisions)
            return decisions

        try:
            decisions = await self._evaluate_with_groq_batch(transactions, recent_history_by_id)
            decisions = [
                self._apply_decision_guardrails(
                    transaction,
                    recent_history_by_id.get(transaction.id, []),
                    decision,
                )
                for transaction, decision in zip(transactions, decisions)
            ]
            self.last_runtime_mode = "groq"
            self.last_reasoning = self._summarize_batch_reasoning(decisions)
            return decisions
        except Exception as exc:
            decisions = [
                self._evaluate_with_rules(transaction, recent_history_by_id.get(transaction.id, []))
                for transaction in transactions
            ]
            if self._is_rate_limited_error(exc):
                logger.warning(
                    "Groq police batch evaluation hit a rate limit; falling back to local rules."
                )
                self.last_reasoning = (
                    "Groq rate limit reached; continuing with local heuristic police logic."
                )
                suffix = "Local fallback active because Groq rate limits were reached."
            else:
                self.last_reasoning = (
                    f"Groq batch evaluation failed: {self._summarize_exception(exc)}; "
                    f"fell back to local heuristic police logic."
                )
                suffix = "Groq fallback engaged."
            for decision in decisions:
                if decision.reason:
                    decision.reason = f"{decision.reason} | {suffix}"
            self.last_runtime_mode = "mock"
            return decisions

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

    async def _evaluate_with_groq_batch(
        self,
        transactions: list[Transaction],
        recent_history_by_id: dict[str, list[Transaction]],
    ) -> list[DefenderDecision]:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=GROQ_API_KEY)
        prompt = self._build_batch_prompt(transactions, recent_history_by_id)

        try:
            response = await client.chat.completions.create(
                model=GROQ_POLICE_MODEL,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        except Exception as exc:
            if self._is_rate_limited_error(exc):
                logger.warning(
                    "Groq police batch evaluation rate-limited; using local fallback."
                )
                raise RuntimeError(
                    "Groq police batch evaluation hit a 429 rate limit."
                ) from exc
            raise

        raw_text = (response.choices[0].message.content or "").strip()
        cleaned = self._strip_markdown_fences(raw_text)
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            payload = payload.get("decisions")
        if not isinstance(payload, list):
            raise ValueError("Groq police response did not produce a JSON array.")
        if len(payload) != len(transactions):
            raise ValueError(
                "Groq police batch response length did not match the transaction count."
            )

        decisions: list[DefenderDecision] = []
        for transaction, item in zip(transactions, payload):
            if not isinstance(item, dict):
                raise ValueError("Groq police batch response contained a non-object decision.")
            decision_payload = dict(item)
            decision_value = decision_payload.get("decision")
            if isinstance(decision_value, str):
                decision_payload["decision"] = decision_value.upper()
            decision_payload["transaction_id"] = transaction.id
            decisions.append(DefenderDecision.model_validate(decision_payload))

        return decisions

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

        hour = self._parse_timestamp(transaction.timestamp).hour
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
        elif same_merchant_count >= 1 and transaction.amount >= 40:
            score += 0.10
            reasons.append("merchant is repeating with elevated spend")

        same_category_count = sum(
            1 for prior in recent_transactions if prior.category == transaction.category
        )
        recent_total = sum(item.amount for item in recent_transactions[-4:]) + transaction.amount
        if same_category_count >= 3 and recent_total >= 120:
            score += 0.15
            reasons.append("recent activity is concentrating in one category")

        burst_window = recent_transactions[-3:] + [transaction]
        if len(burst_window) == 4:
            timestamps = [self._parse_timestamp(item.timestamp) for item in burst_window]
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

    def _build_batch_prompt(
        self,
        transactions: list[Transaction],
        recent_history_by_id: dict[str, list[Transaction]],
    ) -> str:
        numbered_transactions = [
            self._build_prompt_transaction_context(
                index=index,
                transaction=transaction,
                recent_transactions=recent_history_by_id.get(transaction.id, []),
            )
            for index, transaction in enumerate(transactions, start=1)
        ]
        return (
            "Analyze every transaction below and return ONLY a JSON array of defender decisions in the "
            "exact same order.\n"
            "Each decision must contain: transaction_id, decision, confidence, reason.\n"
            "Use the provided user_baseline and heuristic_assessment sections as hard evidence.\n"
            "If deny_recommended_by_backend is true, you should normally return DENY unless the transaction "
            "very clearly matches the baseline.\n"
            "Do not include markdown, code fences, or explanatory text.\n\n"
            f"Transactions:\n{json.dumps(numbered_transactions, indent=2)}\n\n"
            f"Return schema:\n{json.dumps(POLICE_BATCH_DECISION_SCHEMA, indent=2)}"
        )

    def _build_prompt_transaction_context(
        self,
        *,
        index: int,
        transaction: Transaction,
        recent_transactions: list[Transaction],
    ) -> dict[str, object]:
        baseline = self._baseline_profile_for_user(transaction.user_id)
        assessment = self._assess_risk(transaction, recent_transactions, baseline)
        severe_signals = self._severe_risk_signals(
            transaction,
            recent_transactions,
            baseline,
            assessment,
        )

        return {
            "index": index,
            "transaction_id": transaction.id,
            "transaction": {
                "amount": round(transaction.amount, 2),
                "currency": transaction.currency,
                "merchant": transaction.merchant,
                "category": transaction.category,
                "location_city": transaction.location_city,
                "location_country": transaction.location_country,
                "transaction_type": transaction.transaction_type.value,
                "timestamp": transaction.timestamp,
            },
            "recent_history_summary": self._recent_history_summary(recent_transactions),
            "recent_history_metrics": {
                "recent_transaction_count": len(recent_transactions[-5:]),
                "recent_total_amount": round(sum(item.amount for item in recent_transactions[-5:]), 2),
                "same_merchant_hits": sum(
                    1 for item in recent_transactions if item.merchant == transaction.merchant
                ),
                "same_category_hits": sum(
                    1 for item in recent_transactions if item.category == transaction.category
                ),
                "distinct_recent_merchants": len({item.merchant for item in recent_transactions[-5:]}),
            },
            "user_baseline": self._baseline_prompt_payload(baseline),
            "heuristic_assessment": {
                "risk_score": round(assessment.score, 2),
                "risk_reasons": assessment.reasons or ["no strong backend risk signals"],
                "severe_signals": severe_signals,
                "deny_recommended_by_backend": bool(
                    severe_signals or assessment.score >= 0.72 or len(assessment.reasons) >= 3
                ),
            },
        }

    def _baseline_prompt_payload(
        self,
        baseline: UserBaselineProfile | None,
    ) -> dict[str, object]:
        if baseline is None:
            return {
                "available": False,
                "summary": "No long-term baseline available for this user.",
            }

        return {
            "available": True,
            "median_amount": round(baseline.median_amount, 2),
            "max_amount": round(baseline.max_amount, 2),
            "known_categories": sorted(baseline.categories)[:8],
            "known_cities": sorted(baseline.cities)[:6],
            "known_countries": sorted(baseline.countries)[:4],
            "known_transaction_types": sorted(baseline.transaction_types),
        }

    def _recent_history_summary(self, recent_transactions: Iterable[Transaction]) -> str:
        recent_list = list(recent_transactions)
        if not recent_list:
            return "- No recent transactions available."
        return "\n".join(
            f"- {tx.timestamp}: {tx.merchant} ${tx.amount:.2f} in {tx.location_city} "
            f"({tx.category}, {tx.transaction_type.value})"
            for tx in recent_list[-5:]
        )

    def _apply_decision_guardrails(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
        decision: DefenderDecision,
    ) -> DefenderDecision:
        baseline = self._baseline_profile_for_user(transaction.user_id)
        assessment = self._assess_risk(transaction, recent_transactions, baseline)
        severe_signals = self._severe_risk_signals(
            transaction,
            recent_transactions,
            baseline,
            assessment,
        )

        if decision.decision == "APPROVE" and (
            severe_signals or assessment.score >= 0.72 or len(assessment.reasons) >= 3
        ):
            reasons = severe_signals or assessment.reasons or ["multiple correlated fraud signals"]
            return DefenderDecision(
                transaction_id=transaction.id,
                decision="DENY",
                confidence=max(decision.confidence, self._confidence_from_score(max(assessment.score, 0.78), "DENY")),
                reason=(
                    "Denied because "
                    + "; ".join(list(dict.fromkeys(reasons))[:3])
                    + ". | Backend override after strong fraud correlation."
                ),
            )

        if decision.reason:
            return decision

        return decision.model_copy(
            update={
                "reason": self._format_reason(assessment.reasons, decision.decision),
            }
        )

    def _severe_risk_signals(
        self,
        transaction: Transaction,
        recent_transactions: list[Transaction],
        baseline: UserBaselineProfile | None,
        assessment: RiskAssessment,
    ) -> list[str]:
        signals: list[str] = []
        recent_transactions = recent_transactions[-5:]
        same_category_hits = sum(1 for item in recent_transactions if item.category == transaction.category)
        recent_window_total = sum(item.amount for item in recent_transactions) + transaction.amount
        hour = self._parse_timestamp(transaction.timestamp).hour
        lowered_merchant = transaction.merchant.lower()

        if baseline is not None:
            if transaction.amount > baseline.max_amount * 1.2:
                signals.append("amount exceeds the user's historical max by more than 20%")
            if transaction.amount > baseline.median_amount * 3.0:
                signals.append("amount exceeds three times the user's normal median spend")
            if (
                transaction.location_country not in baseline.countries
                and transaction.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL)
            ):
                signals.append("first-seen country is paired with transfer-style money movement")
            if (
                transaction.location_country not in baseline.countries
                and transaction.category not in baseline.categories
            ):
                signals.append("new country and new merchant category appeared together")
            if recent_window_total > baseline.max_amount * 1.4 and same_category_hits >= 3:
                signals.append("recent concentrated spend already exceeds the user's usual ceiling")
        else:
            if transaction.location_country != "Canada" and transaction.amount > 250:
                signals.append("foreign high-value transaction without a historical baseline")

        if "recent pattern looks like a micro-transaction burst" in assessment.reasons:
            signals.append("rapid micro-transaction burst pattern is present")

        if 3 <= hour <= 5 and (assessment.score >= 0.65 or len(assessment.reasons) >= 3):
            signals.append("overnight timing is paired with other out-of-pattern behavior")

        if any(keyword in lowered_merchant for keyword in HIGH_RISK_MERCHANT_KEYWORDS):
            signals.append("merchant name matches a high-risk money-movement pattern")

        return list(dict.fromkeys(signals))

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

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _summarize_batch_reasoning(self, decisions: list[DefenderDecision]) -> str:
        denied = sum(1 for decision in decisions if decision.decision == "DENY")
        approved = len(decisions) - denied
        return (
            f"Evaluated {len(decisions)} transactions in batch: "
            f"{denied} denied, {approved} approved."
        )

    def _is_rate_limited_error(self, exc: Exception) -> bool:
        error_str = str(exc).lower()
        return any(token in error_str for token in ("429", "rate", "quota", "limit"))

    def _summarize_exception(self, exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__
