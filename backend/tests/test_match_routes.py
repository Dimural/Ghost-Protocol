"""Unit tests for Ghost Protocol match management routes."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.core.match_state import MATCH_STATE_STORE
from backend.main import app


@pytest.fixture(autouse=True)
def isolate_match_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)


def test_create_start_and_get_match_routes():
    client = TestClient(app)

    create_response = client.post(
        "/api/match/create",
        json={
            "scenario_name": "test-scenario",
            "criminal_persona": "patient",
            "total_rounds": 3,
        },
    )
    assert create_response.status_code == 200
    create_payload = create_response.json()

    assert create_payload["status"] == "setup"
    assert create_payload["share_url"] == f"/match/{create_payload['match_id']}"

    start_response = client.post(f"/api/match/{create_payload['match_id']}/start")
    assert start_response.status_code == 200
    start_payload = start_response.json()

    assert start_payload["match_id"] == create_payload["match_id"]
    assert start_payload["status"] == "running"
    assert start_payload["scenario_name"] == "test-scenario"
    assert start_payload["criminal_persona"] == "patient"
    assert start_payload["total_rounds"] == 3

    get_response = client.get(f"/api/match/{create_payload['match_id']}")
    assert get_response.status_code == 200
    get_payload = get_response.json()

    assert get_payload["match_id"] == create_payload["match_id"]
    assert get_payload["status"] == "running"
    assert get_payload["share_url"] == create_payload["share_url"]


def test_pause_and_reset_keep_match_configuration():
    client = TestClient(app)

    create_response = client.post(
        "/api/match/create",
        json={
            "scenario_name": "The Long Con",
            "criminal_persona": "botnet",
            "total_rounds": 4,
        },
    )
    match_id = create_response.json()["match_id"]

    pause_response = client.post(f"/api/match/{match_id}/pause")
    assert pause_response.status_code == 200
    pause_payload = pause_response.json()

    assert pause_payload["status"] == "paused"
    assert pause_payload["scenario_name"] == "The Long Con"
    assert pause_payload["criminal_persona"] == "botnet"
    assert pause_payload["total_rounds"] == 4

    reset_response = client.post(f"/api/match/{match_id}/reset")
    assert reset_response.status_code == 200
    reset_payload = reset_response.json()

    assert reset_payload["status"] == "setup"
    assert reset_payload["scenario_name"] == "The Long Con"
    assert reset_payload["criminal_persona"] == "botnet"
    assert reset_payload["total_rounds"] == 4
    assert reset_payload["transactions"] == []
    assert reset_payload["defender_decisions"] == []
    assert reset_payload["attack_rounds"] == []
    assert reset_payload["score"]["true_positives"] == 0
    assert reset_payload["score"]["false_positives"] == 0
    assert reset_payload["score"]["false_negatives"] == 0
    assert reset_payload["score"]["true_negatives"] == 0


def test_match_routes_return_404_for_missing_match():
    client = TestClient(app)

    get_response = client.get("/api/match/missing-match")
    assert get_response.status_code == 404

    start_response = client.post("/api/match/missing-match/start")
    assert start_response.status_code == 404

    pause_response = client.post("/api/match/missing-match/pause")
    assert pause_response.status_code == 404

    reset_response = client.post("/api/match/missing-match/reset")
    assert reset_response.status_code == 404
