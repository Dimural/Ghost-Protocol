"""Regression tests for Gemini-backed code paths without live network calls."""
from __future__ import annotations

from datetime import datetime

import pytest

import backend.agents.criminal_agent as criminal_module
import backend.agents.police_agent as police_module
import backend.core.report_generator as report_module
from backend.agents.criminal_agent import CriminalAgent
from backend.agents.police_agent import PoliceAgent
from backend.core.match_state import MATCH_STATE_STORE, MatchState
from backend.core.report_generator import REPORT_GENERATOR, REPORT_STORE
from backend.data.generator import load_personas
from backend.data.models import DefenderDecision, Transaction, TransactionType


@pytest.fixture(autouse=True)
def isolate_report_state(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    monkeypatch.setattr(REPORT_STORE, "_fallback_path", tmp_path / "reports.json")
    monkeypatch.setattr(REPORT_STORE, "_redis_client", None)


@pytest.mark.asyncio
async def test_criminal_agent_uses_structured_gemini_client(monkeypatch):
    target_persona = load_personas()[0]

    async def fake_generate_json(**kwargs):
        assert kwargs["model"] == criminal_module.GEMINI_FLASH_MODEL
        assert kwargs["response_schema"] == criminal_module.ATTACK_RESPONSE_SCHEMA
        return [
            {
                "amount": 87.45,
                "currency": "CAD",
                "merchant": "Cafe Pulse",
                "category": "restaurants",
                "location_city": target_persona.city,
                "location_country": target_persona.country,
                "transaction_type": TransactionType.PURCHASE.value,
                "fraud_type": "account_takeover",
                "notes": "Structured Gemini attack.",
            }
        ]

    monkeypatch.setattr(criminal_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr(criminal_module.GEMINI_CLIENT, "generate_json", fake_generate_json)

    agent = CriminalAgent(persona="patient")
    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=["Flag foreign transactions"],
        count=1,
    )

    assert len(attacks) == 1
    assert attacks[0].merchant == "Cafe Pulse"
    assert attacks[0].is_fraud is True
    assert agent.last_strategy_notes == (
        f"Patient attacker generated 1 Gemini-backed attacks for {target_persona.name}."
    )


@pytest.mark.asyncio
async def test_police_agent_uses_structured_gemini_client(monkeypatch):
    async def fake_generate_json(**kwargs):
        assert kwargs["model"] == police_module.GEMINI_FLASH_MODEL
        assert kwargs["response_schema"] == police_module.POLICE_DECISION_SCHEMA
        return {
            "decision": "deny",
            "confidence": 0.92,
            "reason": "Foreign location and atypical transfer behavior.",
        }

    monkeypatch.setattr(police_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr(police_module.GEMINI_CLIENT, "generate_json", fake_generate_json)

    decision = await PoliceAgent().evaluate_transaction(
        Transaction(
            id="txn-live-police",
            timestamp=datetime(2026, 3, 15, 3, 30, 0).isoformat(),
            user_id="ghost_student",
            amount=812.33,
            currency="CAD",
            merchant="Wise Transfer",
            category="transfer",
            location_city="Bucharest",
            location_country="Romania",
            transaction_type=TransactionType.TRANSFER,
            is_fraud=True,
            fraud_type="identity_theft",
            notes="Synthetic suspicious transaction.",
        )
    )

    assert decision.transaction_id == "txn-live-police"
    assert decision.decision == "DENY"
    assert decision.confidence == 0.92
    assert "Foreign location" in (decision.reason or "")


@pytest.mark.asyncio
async def test_report_generator_uses_structured_gemini_client(monkeypatch):
    transaction = Transaction(
        id="txn-live-report",
        timestamp=datetime(2026, 3, 15, 4, 15, 0).isoformat(),
        user_id="ghost_student",
        amount=1420.0,
        currency="CAD",
        merchant="TD Bank Wire Transfer",
        category="transfer",
        location_city="Toronto",
        location_country="Canada",
        transaction_type=TransactionType.TRANSFER,
        is_fraud=True,
        fraud_type="identity_theft",
        notes="Synthetic missed fraud for Gemini report testing.",
    )
    decision = DefenderDecision(
        transaction_id=transaction.id,
        decision="APPROVE",
        confidence=0.14,
        reason="Synthetic miss.",
    )

    MATCH_STATE_STORE.save(
        MatchState(
            match_id="live-report-match",
            scenario_name="Gemini Report",
            status="complete",
            current_round=1,
            total_rounds=1,
            criminal_persona="patient",
            transactions=[transaction],
            defender_decisions=[decision],
        )
    )

    async def fake_generate_json(**kwargs):
        assert kwargs["model"] == report_module.GEMINI_PRO_MODEL
        assert kwargs["response_schema"] == report_module.REPORT_RESPONSE_SCHEMA
        return {
            "executive_summary": "The defender missed a high-risk transfer during the simulation.",
            "critical_vulnerabilities": ["Large transfer anomalies were not denied."],
            "attack_pattern_analysis": "The attacker used a single high-value transfer to test approval boundaries.",
            "recommendations": [
                {
                    "title": "Block risky transfers",
                    "priority": "HIGH",
                    "action": "Add a hard deny rule for atypical high-value transfers.",
                    "rationale": "This closes the highest-loss gap first.",
                    "code_hint": "if tx.type == 'transfer' and tx.amount > 1000: return 'DENY'",
                }
            ],
            "risk_rating": "HIGH",
        }

    monkeypatch.setattr(report_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr(report_module.GEMINI_CLIENT, "generate_json", fake_generate_json)

    report = await REPORT_GENERATOR.generate_for_match("live-report-match", force=True)

    assert report.runtime_mode == "gemini"
    assert report.executive_summary.startswith("The defender missed")
    assert report.recommendations[0].title == "Block risky transfers"
    assert report.risk_rating == "HIGH"
