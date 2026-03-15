"""Regression tests for Groq-backed code paths without live network calls."""
from __future__ import annotations

import json
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


class _FakeGroqResponse:
    def __init__(self, payload):
        content = payload if isinstance(payload, str) else json.dumps(payload)
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type("Message", (), {"content": content})(),
                },
            )()
        ]


def _fake_async_groq_factory(create_handler):
    class FakeCompletions:
        async def create(self, **kwargs):
            return await create_handler(**kwargs)

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeAsyncGroq:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key
            self.chat = FakeChat()

    return FakeAsyncGroq


@pytest.fixture(autouse=True)
def isolate_report_state(tmp_path, monkeypatch):
    monkeypatch.setattr(MATCH_STATE_STORE, "_fallback_path", tmp_path / "matches.json")
    monkeypatch.setattr(MATCH_STATE_STORE, "_redis_client", None)
    monkeypatch.setattr(REPORT_STORE, "_fallback_path", tmp_path / "reports.json")
    monkeypatch.setattr(REPORT_STORE, "_redis_client", None)


@pytest.mark.asyncio
async def test_criminal_agent_uses_structured_groq_client(monkeypatch):
    target_persona = load_personas()[0]

    async def fake_create(**kwargs):
        assert kwargs["model"] == criminal_module.GROQ_ATTACK_MODEL
        assert kwargs["messages"][0]["role"] == "system"
        return _FakeGroqResponse(
            [
                {
                    "amount": 87.45,
                    "currency": "CAD",
                    "merchant": "Cafe Pulse",
                    "category": "restaurants",
                    "location_city": target_persona.city,
                    "location_country": target_persona.country,
                    "transaction_type": TransactionType.PURCHASE.value,
                    "fraud_type": "account_takeover",
                    "notes": "Structured Groq attack.",
                }
            ]
        )

    monkeypatch.setattr(criminal_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr("groq.AsyncGroq", _fake_async_groq_factory(fake_create))

    agent = CriminalAgent(persona="patient")
    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=["Flag foreign transactions"],
        count=1,
    )

    assert len(attacks) == 1
    assert attacks[0].merchant == "Cafe Pulse"
    assert attacks[0].is_fraud is True
    assert agent.last_runtime_mode == "groq"
    assert agent.last_strategy_notes == (
        f"Patient attacker generated 1 Groq-backed attacks for {target_persona.name}."
    )


@pytest.mark.asyncio
async def test_police_agent_uses_structured_groq_batch(monkeypatch):
    async def fake_create(**kwargs):
        assert kwargs["model"] == police_module.GROQ_POLICE_MODEL
        assert kwargs["messages"][0]["role"] == "system"
        return _FakeGroqResponse(
            [
                {
                    "decision": "deny",
                    "confidence": 0.92,
                    "reason": "Foreign location and atypical transfer behavior.",
                },
                {
                    "decision": "approve",
                    "confidence": 0.71,
                    "reason": "Matches the user's normal baseline.",
                },
            ]
        )

    monkeypatch.setattr(police_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr("groq.AsyncGroq", _fake_async_groq_factory(fake_create))

    agent = PoliceAgent()
    suspicious = Transaction(
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
    normal = suspicious.model_copy(
        update={
            "id": "txn-live-police-2",
            "amount": 24.50,
            "merchant": "Metro",
            "category": "groceries",
            "location_city": "Toronto",
            "location_country": "Canada",
            "transaction_type": TransactionType.PURCHASE,
            "is_fraud": False,
            "fraud_type": None,
        }
    )
    decisions = await agent.evaluate_batch(
        [suspicious, normal],
        recent_history_by_id={
            suspicious.id: [],
            normal.id: [],
        },
    )

    assert [decision.transaction_id for decision in decisions] == [
        "txn-live-police",
        "txn-live-police-2",
    ]
    assert decisions[0].decision == "DENY"
    assert decisions[0].confidence == 0.92
    assert decisions[1].decision == "APPROVE"
    assert agent.last_runtime_mode == "groq"


@pytest.mark.asyncio
async def test_report_generator_uses_structured_groq_client(monkeypatch):
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
        notes="Synthetic missed fraud for Groq report testing.",
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
            scenario_name="Groq Report",
            status="complete",
            current_round=1,
            total_rounds=1,
            criminal_persona="patient",
            transactions=[transaction],
            defender_decisions=[decision],
        )
    )

    async def fake_create(**kwargs):
        assert kwargs["model"] == report_module.GROQ_REPORT_MODEL
        return _FakeGroqResponse(
            {
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
        )

    monkeypatch.setattr(report_module, "USE_MOCK_LLM", False)
    monkeypatch.setattr("groq.AsyncGroq", _fake_async_groq_factory(fake_create))

    report = await REPORT_GENERATOR.generate_for_match("live-report-match", force=True)

    assert report.runtime_mode == "groq"
    assert report.executive_summary.startswith("The defender missed")
    assert report.recommendations[0].title == "Block risky transfers"
    assert report.risk_rating == "HIGH"
