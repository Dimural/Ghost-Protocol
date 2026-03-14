"""Unit tests for Ghost Protocol defender registration."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.data.models import DefenderDecision
from backend.main import app
from backend.routes.defender import WebhookProbeError, _DEFENDER_STORE


@pytest.fixture(autouse=True)
def isolate_defender_store(tmp_path, monkeypatch):
    monkeypatch.setattr(_DEFENDER_STORE, "_fallback_path", tmp_path / "defenders.json")
    monkeypatch.setattr(_DEFENDER_STORE, "_redis_client", None)


def test_register_defender_tests_and_persists_webhook(monkeypatch):
    async def fake_probe(webhook_url: str, payload: dict[str, object]) -> DefenderDecision:
        assert webhook_url == "http://localhost:9000/score"
        assert payload["merchant"] == "Metro"
        assert payload["transaction_type"] == "purchase"
        assert "is_fraud" not in payload
        return DefenderDecision(
            transaction_id=str(payload["transaction_id"]),
            decision="APPROVE",
            confidence=0.98,
            reason="registration test accepted",
        )

    monkeypatch.setattr("backend.routes.defender._probe_defender_webhook", fake_probe)
    client = TestClient(app)

    response = client.post(
        "/api/defender/register",
        json={
            "match_id": "match-123",
            "webhook_url": "http://localhost:9000/score",
            "use_police_ai": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "registered"

    registration = _DEFENDER_STORE.load("match-123")
    assert registration is not None
    assert registration.mode == "webhook"
    assert registration.webhook_url == "http://localhost:9000/score"
    assert registration.last_test_decision is not None
    assert registration.last_test_decision.decision == "APPROVE"


def test_register_defender_rejects_invalid_webhook_url():
    client = TestClient(app)

    response = client.post(
        "/api/defender/register",
        json={
            "match_id": "match-124",
            "webhook_url": "not-a-url",
            "use_police_ai": False,
        },
    )

    assert response.status_code == 422


def test_register_defender_surfaces_unreachable_webhook(monkeypatch):
    async def unreachable(_webhook_url: str, _payload: dict[str, object]) -> DefenderDecision:
        raise WebhookProbeError(
            "Webhook is unreachable at http://localhost:9000/score: ConnectError.",
            status_code=502,
        )

    monkeypatch.setattr("backend.routes.defender._probe_defender_webhook", unreachable)
    client = TestClient(app)

    response = client.post(
        "/api/defender/register",
        json={
            "match_id": "match-125",
            "webhook_url": "http://localhost:9000/score",
            "use_police_ai": False,
        },
    )

    assert response.status_code == 502
    assert "unreachable" in response.json()["detail"].lower()
    assert _DEFENDER_STORE.load("match-125") is None


def test_register_defender_supports_police_ai_without_webhook():
    client = TestClient(app)

    response = client.post(
        "/api/register-defender",
        json={"match_id": "match-police", "use_police_ai": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "registered"

    registration = _DEFENDER_STORE.load("match-police")
    assert registration is not None
    assert registration.mode == "police_ai"
    assert registration.webhook_url is None
    assert registration.last_test_decision is None
