"""Unit tests for the Ghost Protocol CriminalAgent."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.agents.criminal_agent import CriminalAgent
from backend.data.generator import load_personas
from backend.data.models import Transaction, TransactionType


@pytest.fixture
def target_persona():
    return load_personas()[1]


@pytest.fixture(autouse=True)
def default_to_mock_llm(monkeypatch):
    monkeypatch.setattr("backend.agents.criminal_agent.USE_MOCK_LLM", True)


def _attack(
    *,
    tx_id: str,
    user_id: str,
    amount: float,
    merchant: str,
    category: str,
    city: str,
    country: str,
    transaction_type: TransactionType,
) -> Transaction:
    return Transaction(
        id=tx_id,
        timestamp=(datetime(2026, 3, 14, 12, 0, 0) + timedelta(minutes=amount)).isoformat(),
        user_id=user_id,
        amount=amount,
        currency="CAD",
        merchant=merchant,
        category=category,
        location_city=city,
        location_country=country,
        transaction_type=transaction_type,
        is_fraud=True,
        fraud_type="account_takeover",
        notes="Synthetic prior attack for adaptation testing.",
    )


@pytest.mark.asyncio
async def test_generate_attacks_returns_valid_transactions(target_persona):
    agent = CriminalAgent(persona="patient")

    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=[
            "Flag transfers above $1000",
            "Flag foreign transactions",
            "Flag rapid repeated transactions to same merchant",
        ],
        count=6,
    )

    assert len(attacks) == 6
    assert all(isinstance(tx, Transaction) for tx in attacks)
    assert all(tx.user_id == target_persona.id for tx in attacks)
    assert all(tx.amount > 0 for tx in attacks)
    assert all(tx.currency == "CAD" for tx in attacks)
    assert all(tx.notes for tx in attacks)


@pytest.mark.asyncio
async def test_attacks_have_is_fraud_true(target_persona):
    agent = CriminalAgent(persona="botnet")

    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=["Flag foreign transactions"],
        count=8,
    )

    assert attacks
    assert all(tx.is_fraud is True for tx in attacks)
    assert all(tx.fraud_type for tx in attacks)


@pytest.mark.asyncio
async def test_adapt_produces_different_attacks(target_persona):
    agent = CriminalAgent(persona="amateur")
    previous_attacks = [
        _attack(
            tx_id="caught-1",
            user_id=target_persona.id,
            amount=1500.0,
            merchant="TD Bank Wire Transfer",
            category="transfer",
            city="Lagos",
            country="Nigeria",
            transaction_type=TransactionType.TRANSFER,
        ),
        _attack(
            tx_id="caught-2",
            user_id=target_persona.id,
            amount=1300.0,
            merchant="Apple Store Online",
            category="online shopping",
            city="Bucharest",
            country="Romania",
            transaction_type=TransactionType.PURCHASE,
        ),
        _attack(
            tx_id="missed-1",
            user_id=target_persona.id,
            amount=420.0,
            merchant="BestBuy Online",
            category="online shopping",
            city=target_persona.city,
            country=target_persona.country,
            transaction_type=TransactionType.PURCHASE,
        ),
    ]

    adapted_attacks = await agent.adapt(
        previous_attacks=previous_attacks,
        caught_by_defender=["caught-1", "caught-2"],
    )

    assert len(adapted_attacks) == len(previous_attacks)
    assert all(tx.id not in {attack.id for attack in previous_attacks} for tx in adapted_attacks)
    assert max(tx.amount for tx in adapted_attacks) < min(
        attack.amount for attack in previous_attacks if attack.id in {"caught-1", "caught-2"}
    )
    assert all(tx.location_country == target_persona.country for tx in adapted_attacks)
    assert all(tx.transaction_type == TransactionType.PURCHASE for tx in adapted_attacks)
    assert "Defender appears sensitive to" in agent.last_adaptation_reasoning


@pytest.mark.asyncio
async def test_adapt_quota_exhaustion_uses_clean_local_message(target_persona, monkeypatch):
    async def quota_error(*args, **kwargs):
        raise RuntimeError("Groq 429 rate limit exceeded.")

    monkeypatch.setattr("backend.agents.criminal_agent.USE_MOCK_LLM", False)
    monkeypatch.setattr(CriminalAgent, "_generate_llm_adapted_attacks", quota_error)

    agent = CriminalAgent(persona="botnet")
    adapted_attacks = await agent.adapt(
        previous_attacks=[
            _attack(
                tx_id="caught-1",
                user_id=target_persona.id,
                amount=45.0,
                merchant="Coinbase",
                category="transfer",
                city="Toronto",
                country="Canada",
                transaction_type=TransactionType.TRANSFER,
            )
        ],
        caught_by_defender=["caught-1"],
    )

    assert adapted_attacks
    assert (
        agent.last_adaptation_reasoning
        == "Groq rate limit reached; continuing with local botnet adaptation logic."
    )


@pytest.mark.asyncio
async def test_llm_error_falls_back_to_seed_data(target_persona, monkeypatch):
    async def broken_llm(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.agents.criminal_agent.USE_MOCK_LLM", False)
    monkeypatch.setattr(CriminalAgent, "_generate_llm_attacks", broken_llm)

    agent = CriminalAgent(persona="patient")
    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=["Flag foreign transactions"],
        count=5,
    )

    assert len(attacks) == 5
    assert all(isinstance(tx, Transaction) for tx in attacks)
    assert all(tx.is_fraud for tx in attacks)
    assert "fell back to local patient mock attacks" in agent.last_strategy_notes
