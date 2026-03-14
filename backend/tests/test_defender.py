"""Unit tests for Ghost Protocol defender registration."""
from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.agents.police_agent import PoliceAgent
from backend.core.dispatcher import WebhookDispatcher
from backend.data.models import DefenderDecision
from backend.data.models import Transaction, TransactionType
from backend.main import app
from backend.routes.defender import WebhookProbeError, _DEFENDER_STORE


@pytest.fixture(autouse=True)
def isolate_defender_store(tmp_path, monkeypatch):
    monkeypatch.setattr(_DEFENDER_STORE, "_fallback_path", tmp_path / "defenders.json")
    monkeypatch.setattr(_DEFENDER_STORE, "_redis_client", None)


@pytest.fixture
def sample_transaction() -> Transaction:
    return Transaction(
        id="txn-001",
        timestamp=datetime(2026, 3, 14, 17, 35, 0).isoformat(),
        user_id="ghost_student",
        amount=149.75,
        currency="CAD",
        merchant="Apple Store Online",
        category="electronics",
        location_city="Toronto",
        location_country="Canada",
        transaction_type=TransactionType.PURCHASE,
        is_fraud=True,
        fraud_type="card_cloning",
        notes="Ground truth should never leave the backend.",
    )


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


@pytest.mark.asyncio
async def test_dispatch_sends_transaction_without_is_fraud_field(sample_transaction):
    captured_payload: dict[str, object] = {}
    webhook_app = FastAPI()

    @webhook_app.post("/defender")
    async def defender_endpoint(request: Request):
        captured_payload.update(await request.json())
        return {
            "transaction_id": captured_payload["transaction_id"],
            "decision": "DENY",
            "confidence": 0.87,
        }

    dispatcher = WebhookDispatcher(transport=httpx.ASGITransport(app=webhook_app))
    decision = await dispatcher.dispatch(
        transaction=sample_transaction,
        defender_url="http://testserver/defender",
    )

    assert decision.decision == "DENY"
    assert captured_payload["transaction_id"] == sample_transaction.id
    assert captured_payload["amount"] == sample_transaction.amount
    assert captured_payload["merchant"] == sample_transaction.merchant
    assert captured_payload["transaction_type"] == sample_transaction.transaction_type.value
    assert "is_fraud" not in captured_payload
    assert "fraud_type" not in captured_payload
    assert "notes" not in captured_payload


@pytest.mark.asyncio
async def test_dispatch_handles_timeout(monkeypatch, sample_transaction):
    dispatcher = WebhookDispatcher()

    async def timed_out(_defender_url: str, _payload: dict[str, object], _timeout_seconds: int):
        raise httpx.ReadTimeout("defender timed out")

    monkeypatch.setattr(dispatcher, "_post_json", timed_out)

    decision = await dispatcher.dispatch(
        transaction=sample_transaction,
        defender_url="http://localhost:9000/score",
        timeout_seconds=5,
    )

    assert decision.decision == "APPROVE"
    assert decision.confidence == 0.0
    assert "Timeout:" in decision.reason
    assert dispatcher.error_events[-1].error_type == "timeout"


@pytest.mark.asyncio
async def test_dispatch_handles_http_error_without_crashing(monkeypatch, sample_transaction):
    dispatcher = WebhookDispatcher()
    request = httpx.Request("POST", "http://localhost:9000/score")
    response = httpx.Response(500, request=request)

    async def upstream_error(
        _defender_url: str,
        _payload: dict[str, object],
        _timeout_seconds: int,
    ):
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(dispatcher, "_post_json", upstream_error)

    decision = await dispatcher.dispatch(
        transaction=sample_transaction,
        defender_url="http://localhost:9000/score",
    )

    assert decision.decision == "APPROVE"
    assert "HTTP 500" in decision.reason
    assert dispatcher.error_events[-1].error_type == "http_error"


@pytest.mark.asyncio
async def test_dispatch_batch_collects_all_decisions(sample_transaction):
    webhook_app = FastAPI()

    @webhook_app.post("/defender")
    async def defender_endpoint(request: Request):
        payload = await request.json()
        return {
            "transaction_id": payload["transaction_id"],
            "decision": "APPROVE",
            "confidence": 0.55,
        }

    second_transaction = sample_transaction.model_copy(
        update={"id": "txn-002", "merchant": "BestBuy", "amount": 89.99}
    )
    dispatcher = WebhookDispatcher(transport=httpx.ASGITransport(app=webhook_app))

    decisions = await dispatcher.dispatch_batch(
        transactions=[sample_transaction, second_transaction],
        defender_url="http://testserver/defender",
    )

    assert [decision.transaction_id for decision in decisions] == ["txn-001", "txn-002"]
    assert all(decision.decision == "APPROVE" for decision in decisions)


@pytest.mark.asyncio
async def test_police_ai_catches_obvious_fraud():
    agent = PoliceAgent()
    recent_history = [
        Transaction(
            id="hist-1",
            timestamp=datetime(2026, 3, 14, 9, 0, 0).isoformat(),
            user_id="ghost_professional",
            amount=42.50,
            currency="CAD",
            merchant="Tim Hortons",
            category="restaurants",
            location_city="Toronto",
            location_country="Canada",
            transaction_type=TransactionType.PURCHASE,
            is_fraud=False,
        ),
        Transaction(
            id="hist-2",
            timestamp=datetime(2026, 3, 14, 11, 15, 0).isoformat(),
            user_id="ghost_professional",
            amount=18.20,
            currency="CAD",
            merchant="Starbucks",
            category="restaurants",
            location_city="Toronto",
            location_country="Canada",
            transaction_type=TransactionType.PURCHASE,
            is_fraud=False,
        ),
    ]
    suspicious_transaction = Transaction(
        id="fraud-1",
        timestamp=datetime(2026, 3, 15, 3, 30, 0).isoformat(),
        user_id="ghost_professional",
        amount=4200.0,
        currency="CAD",
        merchant="TD Bank Wire Transfer",
        category="transfer",
        location_city="Lagos",
        location_country="Nigeria",
        transaction_type=TransactionType.TRANSFER,
        is_fraud=True,
        fraud_type="identity_theft",
    )

    decision = await agent.evaluate_transaction(suspicious_transaction, recent_history)

    assert decision.decision == "DENY"
    assert decision.confidence >= 0.7
    assert decision.reason is not None
    assert "Denied because" in decision.reason


@pytest.mark.asyncio
async def test_police_ai_approves_normal_transaction():
    agent = PoliceAgent()
    recent_history = [
        Transaction(
            id="hist-3",
            timestamp=datetime(2026, 3, 14, 8, 30, 0).isoformat(),
            user_id="ghost_student",
            amount=9.85,
            currency="CAD",
            merchant="Tim Hortons",
            category="food delivery",
            location_city="Toronto",
            location_country="Canada",
            transaction_type=TransactionType.PURCHASE,
            is_fraud=False,
        ),
        Transaction(
            id="hist-4",
            timestamp=datetime(2026, 3, 14, 12, 10, 0).isoformat(),
            user_id="ghost_student",
            amount=3.35,
            currency="CAD",
            merchant="TTC Presto",
            category="transit",
            location_city="Toronto",
            location_country="Canada",
            transaction_type=TransactionType.PURCHASE,
            is_fraud=False,
        ),
    ]
    normal_transaction = Transaction(
        id="legit-1",
        timestamp=datetime(2026, 3, 14, 18, 0, 0).isoformat(),
        user_id="ghost_student",
        amount=21.40,
        currency="CAD",
        merchant="Uber Eats",
        category="food delivery",
        location_city="Toronto",
        location_country="Canada",
        transaction_type=TransactionType.PURCHASE,
        is_fraud=False,
    )

    decision = await agent.evaluate_transaction(normal_transaction, recent_history)

    assert decision.decision == "APPROVE"
    assert decision.confidence >= 0.51
    assert decision.reason is not None
    assert decision.reason.startswith("Approved because")


@pytest.mark.asyncio
async def test_police_ai_seed_accuracy_exceeds_baseline():
    agent = PoliceAgent()

    benchmark = await agent.benchmark_seed_dataset()

    assert benchmark.total_transactions == 1050
    assert benchmark.accuracy >= 0.60
    assert benchmark.fraud_recall >= 0.60
    assert benchmark.avg_latency_ms < 3000.0
