"""Unit tests for Ghost Protocol live match WebSocket streaming."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from backend.core.match_state import MATCH_STATE_STORE
from backend.core.match_state import MatchState
from backend.core.referee import RefereeEngine
from backend.data.models import DefenderDecision
from backend.data.models import Transaction
from backend.data.models import TransactionType
from backend.main import app
from backend.routes.websocket import MATCH_EVENT_MANAGER, build_match_event_emitter


@pytest.fixture(autouse=True)
def isolate_state_and_websocket_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    monkeypatch.setattr("backend.agents.criminal_agent.USE_MOCK_LLM", True)
    MATCH_STATE_STORE.delete("match-ws")
    MATCH_STATE_STORE.delete("match-adapt-ws")
    MATCH_EVENT_MANAGER.clear()


def _transaction(tx_id: str, amount: float, *, is_fraud: bool) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=datetime(2026, 3, 14, 19, 30, 0).isoformat(),
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
        notes="Synthetic websocket test transaction.",
    )


def _decision(tx_id: str, decision: Literal["APPROVE", "DENY"]) -> DefenderDecision:
    return DefenderDecision(
        transaction_id=tx_id,
        decision=decision,
        confidence=0.92,
        reason="Synthetic websocket test decision",
    )


def test_websocket_emits_transaction_processed_event():
    MATCH_STATE_STORE.save(MatchState(match_id="match-ws", status="running"))
    client = TestClient(app)
    engine = RefereeEngine()
    transaction = _transaction("tx-ws", 199.0, is_fraud=True)

    with client.websocket_connect("/ws/match/match-ws") as websocket:
        assert MATCH_EVENT_MANAGER.connection_count("match-ws") == 1

        asyncio.run(
            engine.score_transaction_for_match(
                "match-ws",
                transaction,
                _decision(transaction.id, "DENY"),
                emitter=build_match_event_emitter("match-ws"),
            )
        )

        message = websocket.receive_json()
        assert message["type"] == "TRANSACTION_PROCESSED"
        assert message["transaction"]["id"] == transaction.id
        assert message["defender_decision"]["decision"] == "DENY"
        assert message["is_correct"] is True
        assert message["outcome"] == "true_positive"
        assert message["score"]["true_positives"] == 1
        assert message["score"]["precision"] == 1.0
        assert message["score"]["recall"] == 1.0

    assert MATCH_EVENT_MANAGER.connection_count("match-ws") == 0
    persisted = MATCH_STATE_STORE.load("match-ws")
    assert persisted is not None
    assert persisted.score.true_positives == 1


def test_websocket_receives_attacker_adapting_event_and_cleans_up_disconnect():
    client = TestClient(app)

    generate_response = client.post(
        "/api/attack/generate",
        json={
            "match_id": "match-adapt-ws",
            "persona": "patient",
            "count": 3,
            "total_rounds": 3,
        },
    )
    assert generate_response.status_code == 200
    first_wave = generate_response.json()["attacks"]

    with client.websocket_connect("/ws/match/match-adapt-ws") as websocket:
        assert MATCH_EVENT_MANAGER.connection_count("match-adapt-ws") == 1

        adapt_response = client.post(
            "/api/attack/adapt",
            json={
                "match_id": "match-adapt-ws",
                "caught_ids": [first_wave[0]["id"]],
            },
        )

        assert adapt_response.status_code == 200
        message = websocket.receive_json()
        assert message["type"] == "ATTACKER_ADAPTING"
        assert message["round"] == 2
        assert message["total_rounds"] == 3
        assert "ATTACKER IS ADAPTING" in message["title"]
        assert message["banner_message"]
        assert message["verified"] is True
        assert "Verified adaptation" in message["evidence_summary"]

    assert MATCH_EVENT_MANAGER.connection_count("match-adapt-ws") == 0
