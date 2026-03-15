"""Unit tests for Ghost Protocol report fetch and export routes."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.core.match_state import MATCH_STATE_STORE, MatchState
from backend.core.report_generator import REPORT_STORE
from backend.data.models import DefenderDecision, Transaction, TransactionType
from backend.main import app


@pytest.fixture(autouse=True)
def isolate_report_state(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    monkeypatch.setattr(REPORT_STORE, "_fallback_path", tmp_path / "reports.json")
    monkeypatch.setattr(REPORT_STORE, "_redis_client", None)


def _transaction(tx_id: str, amount: float, *, merchant: str, city: str) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=datetime(2026, 3, 15, 4, 15, 0).isoformat(),
        user_id="ghost_student",
        amount=amount,
        currency="CAD",
        merchant=merchant,
        category="electronics",
        location_city=city,
        location_country="Canada",
        transaction_type=TransactionType.PURCHASE,
        is_fraud=True,
        fraud_type="smurfing",
        notes="Synthetic missed fraud for report export testing.",
    )


def _store_completed_match(match_id: str = "report-match") -> MatchState:
    transactions = [
        _transaction("tx-1", 28.5, merchant="BestBuy Online", city="Toronto"),
        _transaction("tx-2", 31.25, merchant="BestBuy Online", city="Toronto"),
        _transaction("tx-3", 34.75, merchant="BestBuy Online", city="Toronto"),
    ]
    decisions = [
        DefenderDecision(
            transaction_id=transaction.id,
            decision="APPROVE",
            confidence=0.2,
            reason="Synthetic miss.",
        )
        for transaction in transactions
    ]
    state = MatchState(
        match_id=match_id,
        scenario_name="Post Game Report",
        status="complete",
        current_round=1,
        total_rounds=1,
        criminal_persona="botnet",
        transactions=transactions,
        defender_decisions=decisions,
        share_url=f"/match/{match_id}",
    )
    MATCH_STATE_STORE.save(state)
    return state


def test_get_report_returns_report_and_syncs_match_metadata():
    _store_completed_match()
    client = TestClient(app)

    response = client.get("/api/report/report-match")
    assert response.status_code == 200

    payload = response.json()
    assert payload["match_id"] == "report-match"
    assert payload["report_id"].startswith("report_")
    assert payload["security_gaps"]
    assert payload["recommendations"]

    synced_match = MATCH_STATE_STORE.load("report-match")
    assert synced_match is not None
    assert synced_match.report_id == payload["report_id"]
    assert synced_match.report_generated_at == payload["generated_at"]


def test_report_export_json_includes_raw_match_data_and_report_text():
    _store_completed_match()
    client = TestClient(app)

    response = client.get("/api/report/report-match/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment;" in response.headers["content-disposition"]
    assert "ghost-protocol-report-report-match.json" in response.headers["content-disposition"]

    payload = response.json()
    assert payload["format"] == "json"
    assert payload["match"]["match_id"] == "report-match"
    assert len(payload["match"]["transactions"]) == 3
    assert payload["report"]["match_id"] == "report-match"
    assert payload["report"]["report_id"].startswith("report_")
    assert "Executive Summary" in payload["report_text"]
    assert "Recommendations" in payload["report_text"]


def test_report_export_pdf_returns_downloadable_pdf():
    _store_completed_match()
    client = TestClient(app)

    response = client.get("/api/report/report-match/export?format=pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment;" in response.headers["content-disposition"]
    assert "ghost-protocol-report-report-match.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-1.4")
    assert b"Ghost Protocol Post-Game Report" in response.content
    assert b"report-match" in response.content


def test_report_routes_reject_incomplete_matches():
    MATCH_STATE_STORE.save(
        MatchState(
            match_id="incomplete-match",
            scenario_name="Incomplete Match",
            status="running",
            criminal_persona="patient",
        )
    )
    client = TestClient(app)

    report_response = client.get("/api/report/incomplete-match")
    assert report_response.status_code == 409
    assert "not complete" in report_response.json()["detail"].lower()

    export_response = client.get("/api/report/incomplete-match/export?format=json")
    assert export_response.status_code == 409


def test_report_routes_return_404_for_missing_matches():
    client = TestClient(app)

    report_response = client.get("/api/report/missing-match")
    assert report_response.status_code == 404

    export_response = client.get("/api/report/missing-match/export?format=pdf")
    assert export_response.status_code == 404
