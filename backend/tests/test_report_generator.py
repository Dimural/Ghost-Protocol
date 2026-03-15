"""Unit tests for Ghost Protocol post-game report generation."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.core.match_state import MATCH_STATE_STORE, MatchState
from backend.core.report_generator import REPORT_GENERATOR, REPORT_STORE
from backend.data.models import DefenderDecision, Transaction, TransactionType


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
        notes="Synthetic missed fraud for report testing.",
    )


@pytest.mark.asyncio
async def test_report_generator_builds_and_persists_mock_report():
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

    MATCH_STATE_STORE.save(
        MatchState(
            match_id="report-match",
            scenario_name="Post Game Report",
            status="complete",
            current_round=1,
            total_rounds=1,
            criminal_persona="botnet",
            transactions=transactions,
            defender_decisions=decisions,
        )
    )

    report = await REPORT_GENERATOR.generate_for_match("report-match", force=True)

    assert report.match_id == "report-match"
    assert report.runtime_mode == "mock"
    assert report.total_fraud_transactions == 3
    assert report.missed == 3
    assert report.blind_spots
    assert report.security_gaps
    assert report.risk_rating in {"HIGH", "CRITICAL"}
    assert report.critical_vulnerabilities
    assert report.recommendations
    assert report.recommended_fixes
    first_gap = report.security_gaps[0]
    assert first_gap.pattern_name
    assert first_gap.transactions_exploited >= 3
    assert first_gap.total_money_slipped_through > 0
    assert first_gap.example_transaction.merchant_label.startswith("redacted ")
    assert first_gap.example_transaction.time_window
    first_recommendation = report.recommendations[0]
    assert first_recommendation.title
    assert first_recommendation.priority in {"HIGH", "MEDIUM", "LOW"}
    assert first_recommendation.action
    assert first_recommendation.rationale
    assert any(recommendation.code_hint for recommendation in report.recommendations)
    assert report.recommended_fixes == [
        recommendation.action for recommendation in report.recommendations
    ]

    persisted = REPORT_STORE.load("report-match")
    assert persisted is not None
    assert persisted.report_id == report.report_id
    assert persisted.executive_summary == report.executive_summary
    assert persisted.security_gaps == report.security_gaps
    assert persisted.recommendations == report.recommendations


@pytest.mark.asyncio
async def test_report_generator_rejects_incomplete_matches():
    MATCH_STATE_STORE.save(
        MatchState(
            match_id="incomplete-match",
            scenario_name="Incomplete",
            status="running",
            criminal_persona="patient",
        )
    )

    with pytest.raises(ValueError, match="must be complete"):
        await REPORT_GENERATOR.generate_for_match("incomplete-match", force=True)
