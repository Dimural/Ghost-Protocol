"""Unit tests for the canonical Ghost Protocol match state manager."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from backend.core.match_state import AttackRound
from backend.core.match_state import MATCH_STATE_STORE
from backend.core.match_state import MatchScore
from backend.core.match_state import MatchState
from backend.data.models import DefenderDecision
from backend.data.models import Transaction
from backend.data.models import TransactionType
from backend.main import app


@pytest.fixture(autouse=True)
def isolate_match_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    MATCH_STATE_STORE.delete("match-roundtrip")
    MATCH_STATE_STORE.delete("match-legacy")
    MATCH_STATE_STORE.delete("match-criminal")
    MATCH_STATE_STORE.delete("match-adapt")
    MATCH_STATE_STORE.delete("match-expired-criminal")


def _transaction(tx_id: str, amount: float, *, is_fraud: bool) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=datetime(2026, 3, 14, 18, 30, 0).isoformat(),
        user_id="ghost_professional",
        amount=amount,
        currency="CAD",
        merchant="Apple Store Online",
        category="electronics",
        location_city="Toronto",
        location_country="Canada",
        transaction_type=TransactionType.PURCHASE,
        is_fraud=is_fraud,
        fraud_type="card_cloning" if is_fraud else None,
        notes="Synthetic transaction for match state tests.",
    )


def test_match_state_store_round_trips_state():
    fraud_tx = _transaction("txn-fraud", 249.99, is_fraud=True)
    legit_tx = _transaction("txn-legit", 39.50, is_fraud=False)
    decision = DefenderDecision(
        transaction_id=fraud_tx.id,
        decision="DENY",
        confidence=0.91,
        reason="Test decision",
    )

    state = MatchState(
        match_id="match-roundtrip",
        scenario_name="The Long Con",
        status="running",
        current_round=1,
        total_rounds=3,
        transactions=[fraud_tx, legit_tx],
        defender_decisions=[decision],
        score=MatchScore(true_positives=1, true_negatives=1),
        attack_rounds=[
            AttackRound(
                round=1,
                attacks=[fraud_tx],
                strategy_notes="Wave one",
            )
        ],
        criminal_persona="patient",
        target_persona_id="ghost_professional",
        known_defender_rules=["Flag foreign transactions"],
    )

    MATCH_STATE_STORE.save(state)
    loaded = MATCH_STATE_STORE.load("match-roundtrip")

    assert loaded is not None
    assert loaded.match_id == "match-roundtrip"
    assert loaded.scenario_name == "The Long Con"
    assert loaded.transactions[0].id == "txn-fraud"
    assert loaded.transactions[1].is_fraud is False
    assert loaded.defender_decisions[0].decision == "DENY"
    assert loaded.score.true_positives == 1
    assert loaded.score.true_negatives == 1
    assert loaded.attack_rounds[0].strategy_notes == "Wave one"


def test_match_state_store_migrates_legacy_criminal_payload():
    legacy_payload = {
        "match-legacy": {
            "match_id": "match-legacy",
            "criminal_persona": "botnet",
            "target_persona_id": "ghost_student",
            "known_defender_rules": ["Flag transfers above $1000"],
            "total_rounds": 3,
            "current_round": 2,
            "status": "running",
            "last_attacks": [_transaction("legacy-last", 9.0, is_fraud=True).model_dump(mode="json")],
            "attack_rounds": [
                {
                    "round": 1,
                    "attacks": [_transaction("legacy-1", 799.0, is_fraud=True).model_dump(mode="json")],
                    "caught_ids": ["legacy-1"],
                    "strategy_notes": "Obvious opening attack",
                    "created_at": datetime(2026, 3, 14, 17, 45, 0).isoformat(),
                },
                {
                    "round": 2,
                    "attacks": [_transaction("legacy-2", 9.0, is_fraud=True).model_dump(mode="json")],
                    "caught_ids": [],
                    "adaptation_reasoning": "Switch to micro-transactions",
                    "created_at": datetime(2026, 3, 14, 17, 50, 0).isoformat(),
                },
            ],
            "latest_notification": {
                "type": "ATTACKER_ADAPTING",
                "title": "🔴 ATTACKER IS ADAPTING...",
                "round": 2,
                "total_rounds": 3,
                "reasoning": "Switch to micro-transactions",
                "banner_message": "🔴 ATTACKER IS ADAPTING... Round 2 of 3\nSwitch to micro-transactions",
                "created_at": datetime(2026, 3, 14, 17, 50, 0).isoformat(),
            },
            "updated_at": datetime(2026, 3, 14, 17, 50, 0).isoformat(),
        }
    }
    MATCH_STATE_STORE._fallback_path.write_text(json.dumps(legacy_payload, indent=2))

    loaded = MATCH_STATE_STORE.load("match-legacy")

    assert loaded is not None
    assert loaded.match_id == "match-legacy"
    assert loaded.current_round == 2
    assert loaded.criminal_persona == "botnet"
    assert loaded.target_persona_id == "ghost_student"
    assert len(loaded.attack_rounds) == 2
    assert len(loaded.transactions) == 2
    assert loaded.transactions[0].id == "legacy-1"
    assert loaded.transactions[1].id == "legacy-2"
    assert loaded.latest_notification is not None
    assert loaded.latest_notification.round == 2


def test_generate_attack_persists_canonical_match_state():
    client = TestClient(app)

    response = client.post(
        "/api/attack/generate",
        json={
            "match_id": "match-criminal",
            "persona": "patient",
            "count": 4,
            "total_rounds": 3,
            "known_defender_rules": ["Flag foreign transactions"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    state = MATCH_STATE_STORE.load("match-criminal")

    assert state is not None
    assert state.match_id == "match-criminal"
    assert state.status == "running"
    assert state.current_round == 1
    assert state.total_rounds == 3
    assert state.criminal_persona == "patient"
    assert state.target_persona_id == payload["target_persona_id"]
    assert len(state.attack_rounds) == 1
    assert len(state.transactions) == 4
    assert state.score.true_positives == 0
    assert state.score.false_negatives == 0


def test_adapt_attack_appends_next_round_into_match_state():
    client = TestClient(app)

    generate_response = client.post(
        "/api/attack/generate",
        json={
            "match_id": "match-adapt",
            "persona": "botnet",
            "count": 3,
            "total_rounds": 3,
        },
    )
    assert generate_response.status_code == 200

    first_wave = generate_response.json()["attacks"]
    caught_ids = [first_wave[0]["id"]]

    adapt_response = client.post(
        "/api/attack/adapt",
        json={
            "match_id": "match-adapt",
            "caught_ids": caught_ids,
        },
    )

    assert adapt_response.status_code == 200
    state = MATCH_STATE_STORE.load("match-adapt")

    assert state is not None
    assert state.current_round == 2
    assert len(state.attack_rounds) == 2
    assert state.attack_rounds[0].caught_ids == caught_ids
    assert len(state.transactions) == 6
    assert state.latest_notification is not None
    assert state.latest_notification.round == 2


def test_expired_match_blocks_attack_generation_and_adaptation():
    expired_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    MATCH_STATE_STORE.save(
        MatchState(
            match_id="match-expired-criminal",
            scenario_name="Archived Match",
            status="complete",
            expires_at=expired_at,
            criminal_persona="patient",
        )
    )

    client = TestClient(app)

    generate_response = client.post(
        "/api/attack/generate",
        json={
            "match_id": "match-expired-criminal",
            "persona": "patient",
            "count": 4,
            "total_rounds": 3,
        },
    )
    assert generate_response.status_code == 409
    assert "archived" in generate_response.json()["detail"].lower()

    expired_state = MATCH_STATE_STORE.load("match-expired-criminal")
    assert expired_state is not None
    expired_state = expired_state.model_copy(
        update={
            "status": "running",
            "current_round": 1,
            "transactions": [_transaction("expired-attack", 49.0, is_fraud=True)],
            "attack_rounds": [
                AttackRound(
                    round=1,
                    attacks=[_transaction("expired-attack", 49.0, is_fraud=True)],
                    strategy_notes="Seeded archived attack wave",
                )
            ],
        }
    )
    MATCH_STATE_STORE.save(expired_state)

    adapt_response = client.post(
        "/api/attack/adapt",
        json={
            "match_id": "match-expired-criminal",
            "caught_ids": ["expired-attack"],
        },
    )
    assert adapt_response.status_code == 409
    assert "archived" in adapt_response.json()["detail"].lower()
