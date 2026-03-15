"""Unit tests for the Ghost Protocol match orchestrator."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core.dispatcher import _ERROR_STORE
from backend.core.match_state import MATCH_STATE_STORE
from backend.core.match_state import MatchState
from backend.core.orchestrator import MATCH_ORCHESTRATOR
import backend.core.orchestrator as orchestrator_module
from backend.main import app
from backend.routes.defender import _DEFENDER_STORE
from backend.routes.websocket import MATCH_EVENT_MANAGER


@pytest.fixture(autouse=True)
def isolate_orchestrator_state(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    monkeypatch.setattr(_DEFENDER_STORE, "_fallback_path", tmp_path / "defenders.json")
    monkeypatch.setattr(_DEFENDER_STORE, "_redis_client", None)
    monkeypatch.setattr(_ERROR_STORE, "_fallback_path", tmp_path / "defender-errors.json")
    monkeypatch.setattr(_ERROR_STORE, "_redis_client", None)
    monkeypatch.setattr(orchestrator_module, "DEFAULT_ATTACKS_PER_ROUND", 3)
    monkeypatch.setattr(orchestrator_module, "TRANSACTION_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(orchestrator_module, "ROUND_DELAY_SECONDS", 0.0)
    MATCH_EVENT_MANAGER.clear()


@pytest.mark.asyncio
async def test_orchestrator_runs_match_to_completion_with_police_ai():
    MATCH_STATE_STORE.save(
        MatchState(
            match_id="orchestrator-police-ai",
            scenario_name="Test Run",
            status="running",
            total_rounds=2,
            criminal_persona="amateur",
            defender_mode="police_ai",
        )
    )

    await MATCH_ORCHESTRATOR.run_match("orchestrator-police-ai")

    state = MATCH_STATE_STORE.load("orchestrator-police-ai")
    assert state is not None
    assert state.status == "complete"
    assert state.current_round == 2
    assert state.ended_at is not None
    assert len(state.attack_rounds) == 2
    assert len(state.defender_decisions) == 6
    assert len(state.transactions) == 6
    assert len(state.attack_rounds[0].caught_ids) >= 0
    assert len(state.attack_rounds[1].caught_ids) >= 0
    assert (
        state.score.true_positives
        + state.score.false_positives
        + state.score.false_negatives
        + state.score.true_negatives
    ) == len(state.defender_decisions)


def test_start_route_requires_registered_defender():
    client = TestClient(app)
    create_response = client.post(
        "/api/match/create",
        json={
            "scenario_name": "Test Run",
            "criminal_persona": "patient",
            "total_rounds": 2,
        },
    )
    match_id = create_response.json()["match_id"]

    start_response = client.post(f"/api/match/{match_id}/start")
    assert start_response.status_code == 409
    assert "registered defender" in start_response.json()["detail"].lower()


def test_start_route_streams_transaction_processed_events_over_websocket():
    client = TestClient(app)

    create_response = client.post(
        "/api/match/create",
        json={
            "scenario_name": "Test Run",
            "criminal_persona": "amateur",
            "total_rounds": 2,
        },
    )
    assert create_response.status_code == 200
    match_id = create_response.json()["match_id"]

    register_response = client.post(
        "/api/defender/register",
        json={"match_id": match_id, "use_police_ai": True},
    )
    assert register_response.status_code == 200

    with client.websocket_connect(f"/ws/match/{match_id}") as websocket:
        start_response = client.post(f"/api/match/{match_id}/start")
        assert start_response.status_code == 200

        streamed = []
        while len(streamed) < 3:
            message = websocket.receive_json()
            if message["type"] == "TRANSACTION_PROCESSED":
                streamed.append(message)

        assert [message["type"] for message in streamed] == [
            "TRANSACTION_PROCESSED",
            "TRANSACTION_PROCESSED",
            "TRANSACTION_PROCESSED",
        ]
        assert all("transaction" in message for message in streamed)
        assert all("defender_decision" in message for message in streamed)

    state = MATCH_STATE_STORE.load(match_id)
    assert state is not None
    assert state.status == "complete"
