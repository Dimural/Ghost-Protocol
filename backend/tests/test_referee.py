"""Unit tests for Ghost Protocol referee scoring, persistence, and live events."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from backend.core.blind_spot_detector import BlindSpotDetector
from backend.core.match_state import MATCH_STATE_STORE
from backend.core.match_state import MatchState
from backend.core.referee import RefereeEngine
from backend.data.models import DefenderDecision
from backend.data.models import Transaction
from backend.data.models import TransactionType
from backend.main import app
from backend.routes.websocket import MATCH_EVENT_MANAGER, build_match_event_emitter


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.storage.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.storage[key] = value
        return True

    def delete(self, key: str) -> int:
        existed = key in self.storage
        self.storage.pop(key, None)
        return 1 if existed else 0


@pytest.fixture(autouse=True)
def isolate_match_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    MATCH_EVENT_MANAGER.clear()
    MATCH_STATE_STORE.delete("match-score")
    MATCH_STATE_STORE.delete("match-persisted")
    MATCH_STATE_STORE.delete("match-redis")
    MATCH_STATE_STORE.delete("match-ws-referee")


def _transaction(
    tx_id: str,
    amount: float,
    *,
    is_fraud: bool,
    timestamp: str | None = None,
    merchant: str = "Metro",
    category: str = "groceries",
    location_city: str = "Toronto",
    location_country: str = "Canada",
    fraud_type: str | None = None,
) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=timestamp or datetime(2026, 3, 14, 19, 0, 0).isoformat(),
        user_id="ghost_student",
        amount=amount,
        currency="CAD",
        merchant=merchant,
        category=category,
        location_city=location_city,
        location_country=location_country,
        transaction_type=TransactionType.PURCHASE,
        is_fraud=is_fraud,
        fraud_type=fraud_type if is_fraud else None,
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


@pytest.mark.asyncio
async def test_blind_spot_detector_finds_patterns():
    engine = RefereeEngine()
    detector = BlindSpotDetector()
    state = MatchState(match_id="match-score", status="running")

    false_negative_transactions = [
        _transaction(
            "fn-1",
            18.0,
            is_fraud=True,
            timestamp=datetime(2026, 3, 14, 1, 5, 0).isoformat(),
            merchant="Best Buy",
            category="electronics",
            location_city="Toronto",
            location_country="Canada",
            fraud_type="smurfing",
        ),
        _transaction(
            "fn-2",
            22.0,
            is_fraud=True,
            timestamp=datetime(2026, 3, 14, 1, 35, 0).isoformat(),
            merchant="Best Buy",
            category="electronics",
            location_city="Toronto",
            location_country="Canada",
            fraud_type="smurfing",
        ),
        _transaction(
            "fn-3",
            27.0,
            is_fraud=True,
            timestamp=datetime(2026, 3, 14, 2, 10, 0).isoformat(),
            merchant="Newegg",
            category="electronics",
            location_city="Toronto",
            location_country="Canada",
            fraud_type="smurfing",
        ),
    ]
    caught_transaction = _transaction(
        "tp-1",
        850.0,
        is_fraud=True,
        merchant="Apple Store",
        category="electronics",
        fraud_type="card_cloning",
    )

    result = await engine.score_batch(
        state,
        [
            *[(transaction, _decision(transaction.id, "APPROVE")) for transaction in false_negative_transactions],
            (caught_transaction, _decision(caught_transaction.id, "DENY")),
        ],
    )

    blind_spots = detector.detect(result.match_state)
    blind_spots_by_category = {blind_spot.category: blind_spot for blind_spot in blind_spots}

    assert len(blind_spots) >= 5

    merchant_category_spot = blind_spots_by_category["merchant_category"]
    assert merchant_category_spot.pattern == "electronics"
    assert merchant_category_spot.missed_count == 3
    assert merchant_category_spot.total_amount == 67.0
    assert merchant_category_spot.example_transaction.id == "fn-1"
    assert "electronics category" in merchant_category_spot.description

    amount_range_spot = blind_spots_by_category["amount_range"]
    assert amount_range_spot.pattern == "$10-$49.99"

    time_of_day_spot = blind_spots_by_category["time_of_day"]
    assert time_of_day_spot.pattern == "12 AM-5:59 AM"

    location_spot = blind_spots_by_category["location"]
    assert location_spot.pattern == "Toronto, Canada"

    fraud_type_spot = blind_spots_by_category["fraud_type"]
    assert fraud_type_spot.pattern == "smurfing"


def test_match_state_serializes_to_redis(monkeypatch, tmp_path):
    fake_redis = FakeRedis()
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", fake_redis)
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")

    transaction = _transaction("tx-redis", 145.0, is_fraud=True, fraud_type="card_cloning")
    decision = _decision(transaction.id, "DENY")
    state = MatchState(
        match_id="match-redis",
        status="running",
        transactions=[transaction],
        defender_decisions=[decision],
    )

    MATCH_STATE_STORE.save(state)
    loaded = MATCH_STATE_STORE.load("match-redis")

    assert "match:match-redis" in fake_redis.storage
    assert loaded is not None
    assert loaded.match_id == "match-redis"
    assert loaded.transactions[0].id == transaction.id
    assert loaded.defender_decisions[0].transaction_id == decision.transaction_id
    assert not (tmp_path / "matches.json").exists()


def test_websocket_emits_on_transaction_processed():
    MATCH_STATE_STORE.save(MatchState(match_id="match-ws-referee", status="running"))
    client = TestClient(app)
    engine = RefereeEngine()
    transaction = _transaction("tx-ws-ref", 199.0, is_fraud=True, fraud_type="card_cloning")

    with client.websocket_connect("/ws/match/match-ws-referee") as websocket:
        assert MATCH_EVENT_MANAGER.connection_count("match-ws-referee") == 1

        asyncio.run(
            engine.score_transaction_for_match(
                "match-ws-referee",
                transaction,
                _decision(transaction.id, "DENY"),
                emitter=build_match_event_emitter("match-ws-referee"),
            )
        )

        message = websocket.receive_json()
        assert message["type"] == "TRANSACTION_PROCESSED"
        assert message["transaction"]["id"] == transaction.id
        assert message["defender_decision"]["transaction_id"] == transaction.id
        assert message["defender_decision"]["decision"] == "DENY"
        assert message["is_correct"] is True
        assert message["outcome"] == "true_positive"
        assert message["score"]["true_positives"] == 1
        assert message["score"]["precision"] == 1.0
        assert message["score"]["recall"] == 1.0

    assert MATCH_EVENT_MANAGER.connection_count("match-ws-referee") == 0
