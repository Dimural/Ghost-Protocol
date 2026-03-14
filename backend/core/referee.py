"""
Ghost Protocol — Referee Engine

Scores defender decisions against Ghost World ground truth one transaction at a
time and emits serializable events for the upcoming WebSocket layer.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

from pydantic import BaseModel

from backend.data.models import DefenderDecision, Transaction

if TYPE_CHECKING:
    from backend.core.match_state import MatchState

OutcomeLabel = Literal["true_positive", "false_positive", "false_negative", "true_negative"]
EventEmitter = Callable[[dict[str, object]], Awaitable[None] | None]


class MatchScore(BaseModel):
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    false_negative_amount_total: float = 0.0
    false_positive_amount_total: float = 0.0

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        if denominator == 0:
            return 0.0
        return self.true_positives / denominator

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        if denominator == 0:
            return 0.0
        return self.true_positives / denominator

    @property
    def f1_score(self) -> float:
        precision = self.precision
        recall = self.recall
        if precision == 0.0 and recall == 0.0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @property
    def money_lost(self) -> float:
        return self.false_negative_amount_total

    @property
    def money_blocked_legitimately(self) -> float:
        return self.false_positive_amount_total

    def with_outcome(self, outcome: OutcomeLabel, amount: float) -> "MatchScore":
        update: dict[str, int | float] = {}
        if outcome == "true_positive":
            update["true_positives"] = self.true_positives + 1
        elif outcome == "false_positive":
            update["false_positives"] = self.false_positives + 1
            update["false_positive_amount_total"] = self.false_positive_amount_total + amount
        elif outcome == "false_negative":
            update["false_negatives"] = self.false_negatives + 1
            update["false_negative_amount_total"] = self.false_negative_amount_total + amount
        else:
            update["true_negatives"] = self.true_negatives + 1

        return self.model_copy(update=update)

    def to_payload(self) -> dict[str, int | float]:
        payload = super().model_dump(mode="json")
        payload["precision"] = self.precision
        payload["recall"] = self.recall
        payload["f1_score"] = self.f1_score
        payload["money_lost"] = self.money_lost
        payload["money_blocked_legitimately"] = self.money_blocked_legitimately
        return payload

    def model_dump(self, *args, **kwargs) -> dict[str, object]:
        payload = super().model_dump(*args, **kwargs)
        payload["precision"] = self.precision
        payload["recall"] = self.recall
        payload["f1_score"] = self.f1_score
        payload["money_lost"] = self.money_lost
        payload["money_blocked_legitimately"] = self.money_blocked_legitimately
        return payload


class TransactionProcessedEvent(BaseModel):
    type: Literal["TRANSACTION_PROCESSED"] = "TRANSACTION_PROCESSED"
    transaction: Transaction
    defender_decision: DefenderDecision
    is_correct: bool
    outcome: OutcomeLabel
    score: MatchScore


@dataclass(frozen=True)
class ScoreTransactionResult:
    match_state: "MatchState"
    event: TransactionProcessedEvent


class RefereeEngine:
    """Apply defender decisions to the canonical match state."""

    async def score_transaction(
        self,
        match_state: "MatchState",
        transaction: Transaction,
        defender_decision: DefenderDecision,
        *,
        emitter: EventEmitter | None = None,
    ) -> ScoreTransactionResult:
        updated_state, event = self._apply_decision(match_state, transaction, defender_decision)
        await self._emit(event, emitter)
        return ScoreTransactionResult(match_state=updated_state, event=event)

    async def score_transaction_for_match(
        self,
        match_id: str,
        transaction: Transaction,
        defender_decision: DefenderDecision,
        *,
        emitter: EventEmitter | None = None,
    ) -> ScoreTransactionResult:
        from backend.core.match_state import MATCH_STATE_STORE

        match_state = MATCH_STATE_STORE.load(match_id)
        if match_state is None:
            raise ValueError(f"Match '{match_id}' was not found.")

        result = await self.score_transaction(
            match_state,
            transaction,
            defender_decision,
            emitter=emitter,
        )
        MATCH_STATE_STORE.save(result.match_state)
        return result

    async def score_batch(
        self,
        match_state: "MatchState",
        scored_transactions: list[tuple[Transaction, DefenderDecision]],
        *,
        emitter: EventEmitter | None = None,
    ) -> ScoreTransactionResult:
        current_state = match_state
        latest_event: TransactionProcessedEvent | None = None

        for transaction, decision in scored_transactions:
            current_state, latest_event = self._apply_decision(current_state, transaction, decision)
            await self._emit(latest_event, emitter)

        if latest_event is None:
            raise ValueError("score_batch requires at least one transaction/decision pair.")

        return ScoreTransactionResult(match_state=current_state, event=latest_event)

    async def score_batch_for_match(
        self,
        match_id: str,
        scored_transactions: list[tuple[Transaction, DefenderDecision]],
        *,
        emitter: EventEmitter | None = None,
    ) -> ScoreTransactionResult:
        from backend.core.match_state import MATCH_STATE_STORE

        match_state = MATCH_STATE_STORE.load(match_id)
        if match_state is None:
            raise ValueError(f"Match '{match_id}' was not found.")

        result = await self.score_batch(
            match_state,
            scored_transactions,
            emitter=emitter,
        )
        MATCH_STATE_STORE.save(result.match_state)
        return result

    def classify_decision(
        self,
        transaction: Transaction,
        defender_decision: DefenderDecision,
    ) -> OutcomeLabel:
        if defender_decision.transaction_id != transaction.id:
            raise ValueError("Defender decision transaction_id did not match the transaction being scored.")

        denied = defender_decision.decision == "DENY"
        if transaction.is_fraud and denied:
            return "true_positive"
        if not transaction.is_fraud and denied:
            return "false_positive"
        if transaction.is_fraud and not denied:
            return "false_negative"
        return "true_negative"

    def _apply_decision(
        self,
        match_state: "MatchState",
        transaction: Transaction,
        defender_decision: DefenderDecision,
    ) -> tuple["MatchState", TransactionProcessedEvent]:
        if defender_decision.transaction_id != transaction.id:
            raise ValueError("Defender decision transaction_id did not match the transaction being scored.")

        if any(
            existing.transaction_id == defender_decision.transaction_id
            for existing in match_state.defender_decisions
        ):
            raise ValueError(f"Transaction '{transaction.id}' has already been scored for this match.")

        outcome = self.classify_decision(transaction, defender_decision)
        updated_score = match_state.score.with_outcome(outcome, transaction.amount)

        transactions = list(match_state.transactions)
        if all(existing.id != transaction.id for existing in transactions):
            transactions.append(transaction)

        updated_state = match_state.model_copy(
            update={
                "transactions": transactions,
                "defender_decisions": [*match_state.defender_decisions, defender_decision],
                "score": updated_score,
            }
        )
        event = TransactionProcessedEvent(
            transaction=transaction,
            defender_decision=defender_decision,
            is_correct=outcome in {"true_positive", "true_negative"},
            outcome=outcome,
            score=updated_score,
        )
        return updated_state, event

    async def _emit(
        self,
        event: TransactionProcessedEvent,
        emitter: EventEmitter | None,
    ) -> None:
        if emitter is None:
            return

        payload = event.model_dump(mode="json")
        payload["score"] = event.score.to_payload()
        emitted = emitter(payload)
        if inspect.isawaitable(emitted):
            await emitted
