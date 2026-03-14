"""Unit tests for Ghost Protocol referee scoring logic."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

import pytest

from backend.core.match_state import MATCH_STATE_STORE
from backend.core.match_state import MatchState
from backend.core.referee import RefereeEngine
from backend.data.models import DefenderDecision
from backend.data.models import Transaction
from backend.data.models import TransactionType


@pytest.fixture(autouse=True)
def isolate_match_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    MATCH_STATE_STORE.delete("match-score")
    MATCH_STATE_STORE.delete("match-persisted")


def _transaction(tx_id: str, amount: float, *, is_fraud: bool) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=datetime(2026, 3, 14, 19, 0, 0).isoformat(),
        user_id="ghost_student",
        amount=amount,
        currency="CAD",
        merchant="Metro",
        category="groceries",
        location_city="Toronto",
        location_country="Canada",
        transaction_type=TransactionType.PURCHASE,
        is_fraud=is_fraud,
        fraud_type="card_cloning" if is_fraud else None,
        notes="Synthetic scoring test transaction.",
    )


def _decision(tx_id: str, decision: Literal["APPROVE", "DENY"]) -> DefenderDecision:
    return DefenderDecision(
        transaction_id=tx_id,
        decision=decision,
        confidence=0.88,
        reason="Synthetic decision",
    )


@pytest.mark.asyncio
async def test_score_calculates_correctly():
    engine = RefereeEngine()
    state = MatchState(match_id="match-score", status="running")

    tx_tp = _transaction("tx-tp", 125.0, is_fraud=True)
    tx_fp = _transaction("tx-fp", 62.5, is_fraud=False)
    tx_fn = _transaction("tx-fn", 310.0, is_fraud=True)
    tx_tn = _transaction("tx-tn", 19.0, is_fraud=False)

    state = (
        await engine.score_batch(
            state,
            [
                (tx_tp, _decision(tx_tp.id, "DENY")),
                (tx_fp, _decision(tx_fp.id, "DENY")),
                (tx_fn, _decision(tx_fn.id, "APPROVE")),
                (tx_tn, _decision(tx_tn.id, "APPROVE")),
            ],
        )
    ).match_state

    assert state.score.true_positives == 1
    assert state.score.false_positives == 1
    assert state.score.false_negatives == 1
    assert state.score.true_negatives == 1
    assert state.score.precision == 0.5
    assert state.score.recall == 0.5
    assert state.score.f1_score == 0.5
    assert state.score.money_lost == 310.0
    assert state.score.money_blocked_legitimately == 62.5


@pytest.mark.asyncio
async def test_score_updates_and_emits_after_every_transaction():
    engine = RefereeEngine()
    state = MatchState(match_id="match-score", status="running")
    emitted_events: list[dict[str, object]] = []

    tx_one = _transaction("tx-one", 400.0, is_fraud=True)
    tx_two = _transaction("tx-two", 55.0, is_fraud=False)

    async def capture(payload: dict[str, object]) -> None:
        emitted_events.append(payload)

    first = await engine.score_transaction(
        state,
        tx_one,
        _decision(tx_one.id, "DENY"),
        emitter=capture,
    )
    second = await engine.score_transaction(
        first.match_state,
        tx_two,
        _decision(tx_two.id, "APPROVE"),
        emitter=capture,
    )

    assert len(emitted_events) == 2
    assert emitted_events[0]["type"] == "TRANSACTION_PROCESSED"
    assert emitted_events[0]["score"]["true_positives"] == 1
    assert emitted_events[1]["score"]["true_negatives"] == 1
    assert emitted_events[1]["score"]["precision"] == 1.0
    assert emitted_events[1]["score"]["recall"] == 1.0
    assert second.match_state.score.true_positives == 1
    assert second.match_state.score.true_negatives == 1
    assert len(second.match_state.defender_decisions) == 2


@pytest.mark.asyncio
async def test_score_transaction_for_match_persists_updated_score():
    engine = RefereeEngine()
    transaction = _transaction("tx-persisted", 222.0, is_fraud=True)
    initial_state = MatchState(
        match_id="match-persisted",
        status="running",
        transactions=[transaction],
    )
    MATCH_STATE_STORE.save(initial_state)

    result = await engine.score_transaction_for_match(
        "match-persisted",
        transaction,
        _decision(transaction.id, "APPROVE"),
    )

    assert result.event.outcome == "false_negative"
    persisted = MATCH_STATE_STORE.load("match-persisted")
    assert persisted is not None
    assert persisted.score.false_negatives == 1
    assert persisted.score.money_lost == 222.0
    assert persisted.defender_decisions[0].transaction_id == transaction.id


@pytest.mark.asyncio
async def test_score_transaction_rejects_duplicate_scoring():
    engine = RefereeEngine()
    transaction = _transaction("tx-duplicate", 48.0, is_fraud=False)
    decision = _decision(transaction.id, "APPROVE")
    state = MatchState(match_id="match-score", status="running")

    first = await engine.score_transaction(state, transaction, decision)

    with pytest.raises(ValueError, match="already been scored"):
        await engine.score_transaction(first.match_state, transaction, decision)
