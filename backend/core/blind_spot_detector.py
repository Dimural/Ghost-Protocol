"""
Ghost Protocol — Blind Spot Detector

Identifies repeated fraud patterns that the defender consistently misses so
later reporting layers can explain exactly where the defense failed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.core.match_state import MATCH_STATE_STORE, MatchState
from backend.data.models import Transaction

BlindSpotCategory = Literal[
    "amount_range",
    "time_of_day",
    "location",
    "merchant_category",
    "fraud_type",
]


class BlindSpot(BaseModel):
    category: BlindSpotCategory
    pattern: str
    description: str
    missed_count: int
    total_amount: float
    transaction_ids: list[str]
    example_transaction: Transaction


class BlindSpotDetector:
    """Analyze false negatives and surface repeated missed-fraud patterns."""

    def __init__(self, min_occurrences: int = 3) -> None:
        self.min_occurrences = min_occurrences

    def detect(self, match_state: MatchState) -> list[BlindSpot]:
        false_negatives = self._collect_false_negatives(match_state)
        if len(false_negatives) < self.min_occurrences:
            return []

        grouped: dict[tuple[BlindSpotCategory, str], list[Transaction]] = defaultdict(list)
        labels: dict[tuple[BlindSpotCategory, str], str] = {}

        for transaction in false_negatives:
            for category, key, label in self._group_dimensions(transaction):
                grouped[(category, key)].append(transaction)
                labels[(category, key)] = label

        blind_spots: list[BlindSpot] = []
        for group_key, transactions in grouped.items():
            if len(transactions) < self.min_occurrences:
                continue

            category, _ = group_key
            label = labels[group_key]
            blind_spots.append(
                BlindSpot(
                    category=category,
                    pattern=label,
                    description=self._describe(category, label),
                    missed_count=len(transactions),
                    total_amount=round(sum(tx.amount for tx in transactions), 2),
                    transaction_ids=[tx.id for tx in transactions],
                    example_transaction=transactions[0],
                )
            )

        return sorted(
            blind_spots,
            key=lambda spot: (-spot.missed_count, -spot.total_amount, spot.category, spot.pattern),
        )

    def detect_for_match(self, match_id: str) -> list[BlindSpot]:
        match_state = MATCH_STATE_STORE.load(match_id)
        if match_state is None:
            raise ValueError(f"Match '{match_id}' was not found.")
        return self.detect(match_state)

    def _collect_false_negatives(self, match_state: MatchState) -> list[Transaction]:
        transactions_by_id = {transaction.id: transaction for transaction in match_state.transactions}
        false_negatives: list[Transaction] = []

        for defender_decision in match_state.defender_decisions:
            transaction = transactions_by_id.get(defender_decision.transaction_id)
            if transaction is None:
                continue
            if transaction.is_fraud and defender_decision.decision == "APPROVE":
                false_negatives.append(transaction)

        return false_negatives

    def _group_dimensions(
        self,
        transaction: Transaction,
    ) -> list[tuple[BlindSpotCategory, str, str]]:
        amount_key, amount_label = self._amount_range(transaction.amount)
        time_key, time_label = self._time_of_day(transaction.timestamp)

        location_label = self._location_label(transaction)
        merchant_category = transaction.category.strip().lower()
        fraud_type = (transaction.fraud_type or "unknown").strip().lower().replace("_", " ")

        return [
            ("amount_range", amount_key, amount_label),
            ("time_of_day", time_key, time_label),
            ("location", location_label.lower(), location_label),
            ("merchant_category", merchant_category, merchant_category),
            ("fraud_type", fraud_type, fraud_type),
        ]

    def _amount_range(self, amount: float) -> tuple[str, str]:
        if amount < 10:
            return ("under_10", "under $10")
        if amount < 50:
            return ("10_to_49", "$10-$49.99")
        if amount < 100:
            return ("50_to_99", "$50-$99.99")
        if amount < 500:
            return ("100_to_499", "$100-$499.99")
        if amount < 1000:
            return ("500_to_999", "$500-$999.99")
        return ("1000_plus", "$1,000+")

    def _time_of_day(self, timestamp: str) -> tuple[str, str]:
        hour = self._parse_timestamp(timestamp).hour
        if 0 <= hour < 6:
            return ("overnight", "12 AM-5:59 AM")
        if 6 <= hour < 12:
            return ("morning", "6 AM-11:59 AM")
        if 12 <= hour < 18:
            return ("afternoon", "12 PM-5:59 PM")
        return ("evening", "6 PM-11:59 PM")

    def _location_label(self, transaction: Transaction) -> str:
        city = transaction.location_city.strip()
        country = transaction.location_country.strip()
        if city and country:
            return f"{city}, {country}"
        return city or country or "unknown location"

    def _describe(self, category: BlindSpotCategory, label: str) -> str:
        if category == "amount_range":
            return f"Fraud transactions in the {label} range were consistently missed."
        if category == "time_of_day":
            return f"Fraud transactions occurring between {label} were consistently missed."
        if category == "location":
            return f"Fraud transactions originating from {label} were consistently missed."
        if category == "merchant_category":
            return f"Fraud transactions in the {label} category were consistently missed."
        return f"Fraud transactions matching the {label} pattern were consistently missed."

    def _parse_timestamp(self, timestamp: str) -> datetime:
        normalized = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
