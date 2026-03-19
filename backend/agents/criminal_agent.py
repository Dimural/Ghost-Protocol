"""
Ghost Protocol — Criminal Agent

Encapsulates the Red Team attacker logic. In mock mode it generates realistic,
persona-aware fraudulent transactions from local seed data. When a Groq API
key is present, the same interface switches to LLM-backed generation and
adaptation automatically.
"""
from __future__ import annotations

import json
import logging
import operator
import random
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Annotated, Any, Iterable, TypedDict

from langchain_groq import ChatGroq
from langgraph.graph import END, StateGraph

from backend.agents.criminal_prompts import (
    ADAPT_PROMPT,
    ATTACK_GENERATION_PROMPT,
    PERSONA_PROMPTS,
    TRANSACTION_SCHEMA,
)
from backend.config import GROQ_API_KEY, USE_MOCK_LLM
from backend.data.generator import load_personas
from backend.data.models import Persona, Transaction, TransactionType

PERSONAS_BY_ID = {persona.id: persona for persona in load_personas()}
SEED_TRANSACTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "transactions.json"
GROQ_ATTACK_MODEL = "llama-3.3-70b-versatile"
logger = logging.getLogger(__name__)

LUXURY_ATTACK_VECTORS = [
    ("Apple Store Online", "online shopping", TransactionType.PURCHASE),
    ("BestBuy Online", "online shopping", TransactionType.PURCHASE),
    ("Marriott Hotels", "travel", TransactionType.PURCHASE),
    ("Air Canada", "travel", TransactionType.PURCHASE),
    ("TD Bank Wire Transfer", "transfer", TransactionType.TRANSFER),
]

BOTNET_ATTACK_VECTORS = [
    ("Interac e-Transfer", "transfer", TransactionType.TRANSFER),
    ("Coinbase", "transfer", TransactionType.TRANSFER),
    ("App Store Gift Card", "online shopping", TransactionType.PURCHASE),
    ("Steam Wallet", "online shopping", TransactionType.PURCHASE),
    ("ATM Withdrawal", "withdrawal", TransactionType.WITHDRAWAL),
]

DOMESTIC_ATTACK_CITIES = [
    "Toronto",
    "Montreal",
    "Mississauga",
    "Brampton",
    "Vancouver",
    "Calgary",
    "Ottawa",
]

FOREIGN_ATTACK_LOCATIONS = [
    ("Lagos", "Nigeria"),
    ("Bucharest", "Romania"),
    ("Shenzhen", "China"),
    ("Moscow", "Russia"),
]

ATTACK_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "timestamp": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "merchant": {"type": "string"},
            "category": {"type": "string"},
            "location_city": {"type": "string"},
            "location_country": {"type": "string"},
            "transaction_type": {
                "type": "string",
                "enum": [member.value for member in TransactionType],
            },
            "fraud_type": {"type": "string"},
            "notes": {"type": "string"},
            "strategy": {"type": "string"},
        },
        "required": [
            "amount",
            "merchant",
            "category",
            "location_city",
            "location_country",
            "transaction_type",
        ],
    },
}


@dataclass
class DefenderRuleHints:
    amount_ceiling: float | None = None
    avoids_foreign: bool = False
    avoids_transfers: bool = False
    avoids_night: bool = False
    avoids_velocity: bool = False
    avoids_luxury: bool = False


class CriminalAgentState(TypedDict):
    target_persona: dict[str, Any]
    known_defender_rules: Annotated[list[str], operator.add]
    caught_ids: Annotated[list[str], operator.add]
    previous_attacks: Annotated[list[dict[str, Any]], operator.add]
    inferred_pattern: str
    strategy: str
    attacks: list[dict[str, Any]]
    retry_count: int
    round_number: int
    desired_count: int
    should_retry: bool


class _UnusedSyncGroqClient:
    """Prevents ChatGroq from constructing an unused sync Groq client in async-only flows."""

    def create(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("CriminalAgent LangGraph should only use async ChatGroq invocations.")


class CriminalAgent:
    """Generate and adapt fraudulent transactions for a chosen attacker persona."""

    def __init__(self, persona: str = "patient"):
        if persona not in PERSONA_PROMPTS:
            allowed = ", ".join(sorted(PERSONA_PROMPTS))
            raise ValueError(f"Unsupported criminal persona '{persona}'. Expected one of: {allowed}")

        self.persona = persona
        self.system_prompt = PERSONA_PROMPTS[persona]
        self.last_strategy_notes: str = ""
        self.last_adaptation_reasoning: str = ""
        self.last_runtime_mode: str = "mock" if USE_MOCK_LLM else "groq"
        self._seed_transactions_cache: list[Transaction] | None = None
        self._attack_graph = None

    async def generate_attacks(
        self,
        target_persona: dict[str, Any] | Persona,
        known_defender_rules: list[str],
        count: int = 10,
    ) -> list[Transaction]:
        """
        Generate fraudulent transactions for a target persona.

        In mock mode this returns realistic hardcoded attacks tailored to the
        target user's profile and the defender's known rules.
        """
        persona = self._coerce_persona(target_persona)
        rules = self._infer_rule_hints(known_defender_rules)

        try:
            if USE_MOCK_LLM:
                attacks = self._generate_mock_attacks(persona, rules, count)
                self.last_runtime_mode = "mock"
            else:
                attacks = await self._generate_llm_attacks(persona, known_defender_rules, count)
                self.last_runtime_mode = "groq"
        except Exception as exc:
            attacks = self._generate_mock_attacks(persona, rules, count)
            if self._is_rate_limited_error(exc):
                logger.warning(
                    "Groq criminal generation hit a rate limit; falling back to local mock attacks."
                )
                self.last_strategy_notes = (
                    f"Groq rate limit reached; continuing with local {self.persona} mock attacks."
                )
            else:
                self.last_strategy_notes = (
                    f"Groq generation failed: {self._summarize_exception(exc)}; "
                    f"fell back to local {self.persona} mock attacks."
                )
            self.last_runtime_mode = "mock"

        return attacks

    async def adapt(
        self,
        previous_attacks: list[Transaction],
        caught_by_defender: list[str],
    ) -> list[Transaction]:
        """
        Generate a new attack wave that avoids the patterns the defender caught.
        """
        if not previous_attacks:
            raise ValueError("adapt() requires at least one previous attack to analyze.")

        target_persona = self._persona_from_user_id(previous_attacks[0].user_id)
        rules, inferred_pattern = self._infer_hints_from_caught(
            target_persona,
            previous_attacks,
            set(caught_by_defender),
        )

        try:
            if USE_MOCK_LLM:
                attacks = self._generate_mock_adapted_attacks(
                    target_persona,
                    previous_attacks,
                    set(caught_by_defender),
                    rules,
                    inferred_pattern,
                )
                self.last_runtime_mode = "mock"
            else:
                attacks = await self._generate_llm_adapted_attacks(
                    target_persona,
                    previous_attacks,
                    set(caught_by_defender),
                    rules,
                    inferred_pattern,
                )
                self.last_runtime_mode = "groq"
        except Exception as exc:
            attacks = self._generate_mock_adapted_attacks(
                target_persona,
                previous_attacks,
                set(caught_by_defender),
                rules,
                inferred_pattern,
            )
            if self._is_rate_limited_error(exc):
                logger.warning(
                    "Groq criminal adaptation hit a rate limit; falling back to local mock logic."
                )
                self.last_adaptation_reasoning = (
                    f"Groq rate limit reached; continuing with local {self.persona} adaptation logic."
                )
            else:
                self.last_adaptation_reasoning = (
                    f"Groq adaptation failed: {self._summarize_exception(exc)}; "
                    f"fell back to local {self.persona} adaptation logic."
                )
            self.last_runtime_mode = "mock"

        return attacks

    def _coerce_persona(self, target_persona: dict[str, Any] | Persona) -> Persona:
        if isinstance(target_persona, Persona):
            return target_persona
        return Persona.model_validate(target_persona)

    def _persona_from_user_id(self, user_id: str) -> Persona:
        persona = PERSONAS_BY_ID.get(user_id)
        if persona is None:
            raise ValueError(f"Unknown target persona '{user_id}'.")
        return persona

    def _load_seed_transactions(self) -> list[Transaction]:
        if self._seed_transactions_cache is None:
            raw = json.loads(SEED_TRANSACTIONS_PATH.read_text())
            self._seed_transactions_cache = [Transaction(**tx) for tx in raw]
        return self._seed_transactions_cache

    def _baseline_transactions_for_persona(self, persona: Persona) -> list[Transaction]:
        return [
            tx
            for tx in self._load_seed_transactions()
            if tx.user_id == persona.id and not tx.is_fraud
        ]

    def _persona_stats(self, persona: Persona) -> dict[str, Any]:
        baseline = self._baseline_transactions_for_persona(persona)
        if baseline:
            amounts = [tx.amount for tx in baseline]
            categories = Counter(tx.category for tx in baseline)
            merchants = Counter(tx.merchant for tx in baseline)
            cities = Counter(tx.location_city for tx in baseline)
            return {
                "baseline": baseline,
                "typical_amount": median(amounts),
                "top_categories": [name for name, _ in categories.most_common(3)],
                "top_merchants": [name for name, _ in merchants.most_common(5)],
                "top_city": cities.most_common(1)[0][0],
            }

        return {
            "baseline": [],
            "typical_amount": max(25.0, persona.typical_max_transaction / 6),
            "top_categories": list(persona.spending_patterns[:3]),
            "top_merchants": [],
            "top_city": persona.city,
        }

    def _infer_rule_hints(self, known_defender_rules: Iterable[str]) -> DefenderRuleHints:
        joined = " ".join(known_defender_rules).lower()
        hints = DefenderRuleHints()

        amounts = []
        for match in re.finditer(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)", joined):
            value = float(match.group(1).replace(",", ""))
            start = max(0, match.start() - 20)
            end = min(len(joined), match.end() + 20)
            context = joined[start:end]
            if any(token in context for token in ("$", "amount", "under", "below", "over", "above", "threshold")):
                amounts.append(value)

        if amounts:
            hints.amount_ceiling = min(amounts)

        hints.avoids_foreign = any(
            token in joined
            for token in ("foreign", "international", "overseas", "location", "different country", "different city")
        )
        hints.avoids_transfers = any(
            token in joined
            for token in ("transfer", "wire", "withdrawal", "atm", "cash", "e-transfer", "etransfer")
        )
        hints.avoids_night = any(
            token in joined
            for token in ("3am", "late", "night", "overnight", "unusual time")
        )
        hints.avoids_velocity = any(
            token in joined
            for token in ("rapid", "repeated", "velocity", "burst", "many small", "micro", "multiple")
        )
        hints.avoids_luxury = any(
            token in joined
            for token in ("luxury", "electronics", "travel", "high-end", "gift card")
        )

        return hints

    def _infer_hints_from_caught(
        self,
        persona: Persona,
        previous_attacks: list[Transaction],
        caught_ids: set[str],
    ) -> tuple[DefenderRuleHints, str]:
        caught = [tx for tx in previous_attacks if tx.id in caught_ids]
        missed = [tx for tx in previous_attacks if tx.id not in caught_ids]
        hints = DefenderRuleHints()
        patterns: list[str] = []

        if caught:
            smallest_caught = min(tx.amount for tx in caught)
            if any(tx.amount >= smallest_caught for tx in caught):
                hints.amount_ceiling = round(max(5.0, smallest_caught * 0.72), 2)
                patterns.append("larger transaction amounts")

            if any(tx.location_country != persona.country for tx in caught):
                hints.avoids_foreign = True
                patterns.append("foreign or out-of-pattern locations")

            if any(tx.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL) for tx in caught):
                hints.avoids_transfers = True
                patterns.append("transfer-style money movement")

            if any(self._is_night(tx.timestamp) for tx in caught):
                hints.avoids_night = True
                patterns.append("late-night timing")

            if len(caught) >= 3:
                merchant_repeats = Counter(tx.merchant for tx in caught)
                if merchant_repeats.most_common(1)[0][1] >= 2:
                    hints.avoids_velocity = True
                    patterns.append("repeat bursts to the same merchant")

        if not patterns:
            if missed:
                patterns.append("the obvious outliers, so the next wave should mimic missed baseline patterns")
            else:
                patterns.append("large, obvious anomalies")

        if missed and not hints.amount_ceiling:
            hints.amount_ceiling = round(max(5.0, max(tx.amount for tx in missed) * 1.05), 2)

        return hints, ", ".join(patterns)

    def _generate_mock_attacks(
        self,
        persona: Persona,
        rules: DefenderRuleHints,
        count: int,
        preferred_categories: list[str] | None = None,
    ) -> list[Transaction]:
        stats = self._persona_stats(persona)
        baseline = stats["baseline"]

        if self.persona == "amateur":
            attacks = self._generate_amateur_attacks(persona, stats, rules, count)
            strategy = "Large, impulsive hits that still try to stay just inside the defender's known rules."
        elif self.persona == "botnet":
            attacks = self._generate_botnet_attacks(persona, stats, rules, count, preferred_categories)
            strategy = "Distributed micro-attacks across many small transactions to dilute the signature."
        else:
            attacks = self._generate_patient_attacks(
                persona,
                stats,
                rules,
                count,
                baseline,
                preferred_categories,
            )
            strategy = "Slow, persona-matched fraud that shadows the victim's baseline and avoids explicit rules."

        self.last_strategy_notes = (
            f"{self.persona.title()} attacker generated {len(attacks)} mock attacks for {persona.name}. "
            f"Primary approach: {strategy}"
        )
        return attacks

    def _generate_mock_adapted_attacks(
        self,
        persona: Persona,
        previous_attacks: list[Transaction],
        caught_ids: set[str],
        rules: DefenderRuleHints,
        inferred_pattern: str,
    ) -> list[Transaction]:
        missed = [tx for tx in previous_attacks if tx.id not in caught_ids]
        count = len(previous_attacks)
        preferred_categories = None

        if missed:
            preferred_categories = [
                name
                for name, _ in Counter(tx.category for tx in missed).most_common(3)
            ]

        attacks = self._generate_mock_attacks(
            persona,
            rules,
            count,
            preferred_categories=preferred_categories,
        )

        if self.persona == "amateur":
            tactic = "shrinking amounts and keeping the activity domestic"
        elif self.persona == "botnet":
            tactic = "splitting traffic across more merchants and tighter amount bands"
        else:
            tactic = "leaning harder into the victim's normal merchants and timing"

        self.last_adaptation_reasoning = (
            f"Defender appears sensitive to {inferred_pattern}; switching to {tactic}."
        )

        adapted_attacks: list[Transaction] = []
        for attack in attacks:
            notes = attack.notes or ""
            adapted_attacks.append(
                attack.model_copy(
                    update={
                        "notes": f"{notes} Adapted after defender keyed on {inferred_pattern}.".strip(),
                    }
                )
            )

        return adapted_attacks

    def _generate_amateur_attacks(
        self,
        persona: Persona,
        stats: dict[str, Any],
        rules: DefenderRuleHints,
        count: int,
    ) -> list[Transaction]:
        attacks: list[Transaction] = []
        typical_amount = max(stats["typical_amount"], persona.typical_max_transaction / 3)

        for index in range(count):
            merchant, category, transaction_type = random.choice(LUXURY_ATTACK_VECTORS)
            if rules.avoids_transfers and transaction_type != TransactionType.PURCHASE:
                merchant, category, transaction_type = ("BestBuy Online", "online shopping", TransactionType.PURCHASE)

            amount = round(max(typical_amount * 2.0, persona.typical_max_transaction * random.uniform(0.9, 1.4)), 2)
            if rules.amount_ceiling is not None:
                amount = round(min(amount, max(5.0, rules.amount_ceiling * random.uniform(0.9, 0.98))), 2)

            if rules.avoids_foreign:
                location_city = random.choice([persona.city, stats["top_city"], *DOMESTIC_ATTACK_CITIES])
                location_country = persona.country
            else:
                location_city, location_country = random.choice(FOREIGN_ATTACK_LOCATIONS)

            strategy = (
                "Quick cash-out using a high-value purchase that looks close enough to normal "
                "thresholds to slip past simple rules."
            )
            attacks.append(
                self._build_transaction(
                    persona=persona,
                    amount=amount,
                    merchant=merchant,
                    category=category,
                    transaction_type=transaction_type,
                    location_city=location_city,
                    location_country=location_country,
                    fraud_type="account_takeover" if transaction_type == TransactionType.PURCHASE else "identity_theft",
                    notes=strategy,
                    timestamp=self._build_timestamp(index, rapid=False, avoid_night=rules.avoids_night),
                )
            )

        return attacks

    def _generate_patient_attacks(
        self,
        persona: Persona,
        stats: dict[str, Any],
        rules: DefenderRuleHints,
        count: int,
        baseline: list[Transaction],
        preferred_categories: list[str] | None,
    ) -> list[Transaction]:
        attacks: list[Transaction] = []
        typical_amount = max(10.0, stats["typical_amount"])
        top_categories = preferred_categories or stats["top_categories"] or list(persona.spending_patterns)
        top_merchants = stats["top_merchants"]

        for index in range(count):
            template = random.choice(baseline) if baseline else None
            category = template.category if template else random.choice(top_categories)
            merchant = template.merchant if template else random.choice(top_merchants or ["Amazon.ca", "Uber Eats"])

            if rules.avoids_luxury and category in {"travel", "online shopping"}:
                category = random.choice([name for name in top_categories if name not in {"travel", "online shopping"}] or top_categories)

            amount = round(typical_amount * random.uniform(1.1, 1.55), 2)
            amount = min(amount, persona.typical_max_transaction * 0.88)
            if rules.amount_ceiling is not None:
                amount = min(amount, max(5.0, rules.amount_ceiling * random.uniform(0.82, 0.95)))

            location_city = template.location_city if template else persona.city
            location_country = template.location_country if template else persona.country
            if not rules.avoids_foreign and index == count - 1 and category in {"travel", "online shopping"}:
                location_city, location_country = random.choice(FOREIGN_ATTACK_LOCATIONS)

            if rules.avoids_transfers and template and template.transaction_type == TransactionType.TRANSFER:
                transaction_type = TransactionType.PURCHASE
            else:
                transaction_type = self._default_transaction_type_for_category(
                    category,
                    template.transaction_type if template else None,
                )

            strategy = (
                "Blend into the victim's existing merchants and spend slightly above normal "
                "so the pattern looks like a routine lifestyle change."
            )
            attacks.append(
                self._build_transaction(
                    persona=persona,
                    amount=round(amount, 2),
                    merchant=merchant,
                    category=category,
                    transaction_type=transaction_type,
                    location_city=location_city,
                    location_country=location_country,
                    fraud_type="account_takeover",
                    notes=strategy,
                    timestamp=self._build_timestamp(index, rapid=False, avoid_night=rules.avoids_night, slow=True),
                )
            )

        return attacks

    def _generate_botnet_attacks(
        self,
        persona: Persona,
        stats: dict[str, Any],
        rules: DefenderRuleHints,
        count: int,
        preferred_categories: list[str] | None,
    ) -> list[Transaction]:
        attacks: list[Transaction] = []
        baseline_cap = max(9.0, min(persona.typical_max_transaction * 0.12, 49.0))
        if rules.amount_ceiling is not None:
            baseline_cap = min(baseline_cap, max(5.0, rules.amount_ceiling * 0.7))

        for index in range(count):
            merchant, category, transaction_type = random.choice(BOTNET_ATTACK_VECTORS)
            if rules.avoids_transfers and transaction_type != TransactionType.PURCHASE:
                merchant, category, transaction_type = (
                    random.choice(stats["top_merchants"]) if stats["top_merchants"] else "Amazon.ca",
                    random.choice(preferred_categories or stats["top_categories"]) if (preferred_categories or stats["top_categories"]) else "online shopping",
                    TransactionType.PURCHASE,
                )

            location_city = random.choice([persona.city, stats["top_city"], *DOMESTIC_ATTACK_CITIES])
            location_country = persona.country if rules.avoids_foreign or random.random() < 0.8 else random.choice(FOREIGN_ATTACK_LOCATIONS)[1]
            if location_country != persona.country:
                location_city = random.choice([city for city, country in FOREIGN_ATTACK_LOCATIONS if country == location_country])

            amount = round(random.uniform(max(4.0, baseline_cap * 0.45), baseline_cap), 2)
            strategy = (
                "Smurf the account with low-value, high-volume transactions spread across merchants "
                "so any single event looks harmless."
            )
            attacks.append(
                self._build_transaction(
                    persona=persona,
                    amount=amount,
                    merchant=merchant,
                    category=category,
                    transaction_type=transaction_type,
                    location_city=location_city,
                    location_country=location_country,
                    fraud_type="smurfing",
                    notes=strategy,
                    timestamp=self._build_timestamp(index, rapid=not rules.avoids_velocity, avoid_night=rules.avoids_night),
                )
            )

        return attacks

    def _get_attack_graph(self):
        if self._attack_graph is None:
            self._attack_graph = self._build_attack_graph()
        return self._attack_graph

    def _build_attack_graph(self):
        graph = StateGraph(CriminalAgentState)
        graph.add_node("Perceive", self._perceive_node)
        graph.add_node("Strategize", self._strategize_node)
        graph.add_node("Attack", self._attack_node)
        graph.add_node("Evaluate", self._evaluate_node)
        graph.set_entry_point("Perceive")
        graph.add_edge("Perceive", "Strategize")
        graph.add_edge("Strategize", "Attack")
        graph.add_edge("Attack", "Evaluate")
        graph.add_conditional_edges(
            "Evaluate",
            self._route_after_evaluate,
            {
                "retry": "Attack",
                "end": END,
            },
        )
        return graph.compile(name=f"{self.persona}-criminal-agent")

    def _route_after_evaluate(self, state: CriminalAgentState) -> str:
        return "retry" if state.get("should_retry") else "end"

    def _build_generation_state(
        self,
        persona: Persona,
        known_defender_rules: list[str],
        count: int,
    ) -> CriminalAgentState:
        return {
            "target_persona": persona.model_dump(mode="json"),
            "known_defender_rules": list(known_defender_rules),
            "caught_ids": [],
            "previous_attacks": [],
            "inferred_pattern": "",
            "strategy": "",
            "attacks": [],
            "retry_count": 0,
            "round_number": 1,
            "desired_count": count,
            "should_retry": False,
        }

    def _build_adaptation_state(
        self,
        persona: Persona,
        previous_attacks: list[Transaction],
        caught_ids: set[str],
        count: int,
    ) -> CriminalAgentState:
        return {
            "target_persona": persona.model_dump(mode="json"),
            "known_defender_rules": [],
            "caught_ids": sorted(caught_ids),
            "previous_attacks": [tx.model_dump(mode="json") for tx in previous_attacks],
            "inferred_pattern": "",
            "strategy": "",
            "attacks": [],
            "retry_count": 0,
            "round_number": 2,
            "desired_count": count,
            "should_retry": False,
        }

    async def _perceive_node(self, state: CriminalAgentState) -> dict[str, Any]:
        persona = Persona.model_validate(state["target_persona"])
        previous_attacks = self._coerce_transactions(state["previous_attacks"])
        fallback_pattern = self._heuristic_inferred_pattern(
            persona,
            previous_attacks,
            set(state["caught_ids"]),
            state["known_defender_rules"],
        )
        payload = await self._invoke_graph_json(
            "Perceive",
            (
                "You are in the Perceive phase of a criminal attack planning graph.\n"
                f"Round number: {state['round_number']}\n\n"
                f"Target persona:\n{self._format_persona_description(persona)}\n\n"
                f"Known defender rules:\n{self._format_rules_for_prompt(state['known_defender_rules'])}\n\n"
                f"Caught transaction IDs:\n{self._format_ids_for_prompt(state['caught_ids'])}\n\n"
                f"Previous attack history:\n{self._format_transactions_for_prompt(previous_attacks)}\n\n"
                "Infer what pattern the defender is most sensitive to. If evidence is sparse, describe the "
                "baseline behavior the attacker should mimic.\n"
                'Return JSON only: {"inferred_pattern": "one concise sentence"}'
            ),
            temperature=0.2,
        )
        inferred_pattern = str(payload.get("inferred_pattern") or fallback_pattern).strip()
        return {"inferred_pattern": inferred_pattern or fallback_pattern}

    async def _strategize_node(self, state: CriminalAgentState) -> dict[str, Any]:
        persona = Persona.model_validate(state["target_persona"])
        previous_attacks = self._coerce_transactions(state["previous_attacks"])
        fallback_strategy = self._heuristic_strategy(
            persona,
            state["inferred_pattern"],
            state["known_defender_rules"],
        )
        payload = await self._invoke_graph_json(
            "Strategize",
            (
                "You are in the Strategize phase of a criminal attack planning graph.\n"
                f"Target persona:\n{self._format_persona_description(persona)}\n\n"
                f"Known defender rules:\n{self._format_rules_for_prompt(state['known_defender_rules'])}\n\n"
                f"Caught transaction IDs:\n{self._format_ids_for_prompt(state['caught_ids'])}\n\n"
                f"Previous attack history:\n{self._format_transactions_for_prompt(previous_attacks)}\n\n"
                f"Defender sensitivity pattern:\n{state['inferred_pattern'] or fallback_strategy}\n\n"
                "Choose an attack approach that maximizes extraction while blending into the target's normal "
                "behavior and avoiding the defender's apparent sensitivities.\n"
                'Return JSON only: {"strategy": "one concise tactical plan"}'
            ),
            temperature=0.35,
        )
        strategy = str(payload.get("strategy") or fallback_strategy).strip()
        return {"strategy": strategy or fallback_strategy}

    async def _attack_node(self, state: CriminalAgentState) -> dict[str, Any]:
        persona = Persona.model_validate(state["target_persona"])
        previous_attacks = self._coerce_transactions(state["previous_attacks"])
        known_rules_text = self._format_rules_for_prompt(state["known_defender_rules"])

        if previous_attacks:
            prompt = ADAPT_PROMPT.format(
                previous_attacks_summary=self._format_transactions_for_prompt(previous_attacks),
                caught_ids=state["caught_ids"],
                missed_ids=[tx.id for tx in previous_attacks if tx.id not in set(state["caught_ids"])],
                inferred_pattern=state["inferred_pattern"],
                count=state["desired_count"],
            )
            prompt = (
                f"{prompt}\n\n"
                f"Target account belongs to: {self._format_persona_description(persona)}\n"
                f"Known defender rules:\n{known_rules_text}\n"
                f"Chosen strategy: {state['strategy']}\n"
                f"Use this transaction schema:\n{TRANSACTION_SCHEMA}\n"
                "Return ONLY a JSON array of transactions."
            )
        else:
            prompt = ATTACK_GENERATION_PROMPT.format(
                known_rules=known_rules_text,
                persona_description=self._format_persona_description(persona),
                count=state["desired_count"],
                transaction_schema=TRANSACTION_SCHEMA,
            )
            prompt = (
                f"{prompt}\n\n"
                f"Defender sensitivity pattern: {state['inferred_pattern']}\n"
                f"Chosen strategy: {state['strategy']}\n"
                f"Retry count so far: {state['retry_count']}\n"
                "Return ONLY the JSON array."
            )

        payload = await self._invoke_graph_json("Attack", prompt, temperature=0.65)
        if isinstance(payload, dict):
            payload = payload.get("attacks") or payload.get("transactions") or []
        if not isinstance(payload, list):
            raise ValueError("Attack node did not return a JSON array of transactions.")
        return {"attacks": payload}

    async def _evaluate_node(self, state: CriminalAgentState) -> dict[str, Any]:
        persona = Persona.model_validate(state["target_persona"])
        payload = await self._invoke_graph_json(
            "Evaluate",
            (
                "You are in the Evaluate phase of a criminal attack planning graph.\n"
                f"Target persona:\n{self._format_persona_description(persona)}\n\n"
                f"Known defender rules:\n{self._format_rules_for_prompt(state['known_defender_rules'])}\n\n"
                f"Defender sensitivity pattern:\n{state['inferred_pattern']}\n\n"
                f"Current strategy:\n{state['strategy']}\n\n"
                f"Generated attacks:\n{self._format_transactions_for_prompt(state['attacks'])}\n\n"
                "Score whether these attacks are realistic, schema-compliant, and likely to evade the defender. "
                "If they are weak, explain the single most important correction.\n"
                'Return JSON only: {"quality_score": 0.0, "acceptable": true, "feedback": "one concise sentence"}'
            ),
            temperature=0.1,
        )
        quality_score = self._coerce_float(payload.get("quality_score"), default=0.0)
        acceptable = self._coerce_bool(payload.get("acceptable"))
        if payload.get("acceptable") is None:
            acceptable = quality_score >= 0.75

        feedback = str(payload.get("feedback") or "").strip()
        should_retry = not acceptable and state["retry_count"] < 2
        next_strategy = state["strategy"]

        if should_retry:
            correction = feedback or "Reduce obvious anomalies and follow the target baseline more closely."
            next_strategy = f"{state['strategy']} Refinement after self-evaluation: {correction}".strip()

        return {
            "retry_count": state["retry_count"] + 1 if should_retry else state["retry_count"],
            "should_retry": should_retry,
            "strategy": next_strategy,
        }

    async def _generate_llm_attacks(
        self,
        persona: Persona,
        known_defender_rules: list[str],
        count: int,
    ) -> list[Transaction]:
        final_state = await self._get_attack_graph().ainvoke(
            self._build_generation_state(persona, known_defender_rules, count)
        )
        attacks = self._transactions_from_payload(
            final_state.get("attacks", []),
            persona,
            count,
            default_fraud_type=self._default_fraud_type(),
        )
        self.last_strategy_notes = (
            f"{self.persona.title()} attacker generated {len(attacks)} Groq-backed attacks for {persona.name}."
        )
        return attacks

    async def _generate_llm_adapted_attacks(
        self,
        persona: Persona,
        previous_attacks: list[Transaction],
        caught_ids: set[str],
        rules: DefenderRuleHints,
        inferred_pattern: str,
    ) -> list[Transaction]:
        final_state = await self._get_attack_graph().ainvoke(
            self._build_adaptation_state(
                persona,
                previous_attacks,
                caught_ids,
                len(previous_attacks),
            )
        )
        attacks = self._transactions_from_payload(
            final_state.get("attacks", []),
            persona,
            len(previous_attacks),
            default_fraud_type=self._default_fraud_type(),
        )
        strategy_summary = str(final_state.get("strategy") or "").strip()
        graph_pattern = str(final_state.get("inferred_pattern") or inferred_pattern).strip() or inferred_pattern
        self.last_strategy_notes = (
            f"{self.persona.title()} attacker generated {len(attacks)} Groq-backed attacks for {persona.name}."
        )
        self.last_adaptation_reasoning = (
            f"Defender appeared sensitive to {graph_pattern}; "
            f"switching to {strategy_summary or 'a tighter evasive pattern'}."
        )
        return attacks

    async def _invoke_graph_json(
        self,
        node_name: str,
        prompt: str,
        *,
        temperature: float,
    ) -> Any:
        llm = ChatGroq(
            model=GROQ_ATTACK_MODEL,
            api_key=GROQ_API_KEY,
            temperature=temperature,
            max_retries=1,
            client=_UnusedSyncGroqClient(),
        )
        try:
            response = await llm.ainvoke(
                [
                    ("system", self.system_prompt),
                    ("human", prompt),
                ]
            )
        except Exception as exc:
            if self._is_rate_limited_error(exc):
                logger.warning("Groq criminal %s node rate-limited; using local mock fallback.", node_name)
                raise RuntimeError(f"Groq criminal {node_name} node hit a 429 rate limit.") from exc
            raise

        return self._parse_json_response(self._coerce_message_text(response.content))

    def _transactions_from_payload(
        self,
        payload: Any,
        persona: Persona,
        count: int,
        default_fraud_type: str,
    ) -> list[Transaction]:
        if isinstance(payload, dict):
            payload = payload.get("attacks") or payload.get("transactions") or []
        if not isinstance(payload, list):
            raise ValueError("Groq response did not contain a JSON array of transactions.")

        transactions: list[Transaction] = []
        for item in payload[:count]:
            if not isinstance(item, dict):
                continue

            strategy = item.pop("strategy", None)
            notes = item.get("notes") or strategy
            transaction_type = item.get("transaction_type", TransactionType.PURCHASE.value)

            transactions.append(
                Transaction(
                    id=item.get("id") or self._random_transaction_id(),
                    timestamp=item.get("timestamp") or self._build_timestamp(len(transactions)),
                    user_id=persona.id,
                    amount=float(item.get("amount", 0.0)),
                    currency=item.get("currency", "CAD"),
                    merchant=item.get("merchant") or "Unknown Merchant",
                    category=item.get("category") or "misc",
                    location_city=item.get("location_city") or persona.city,
                    location_country=item.get("location_country") or persona.country,
                    transaction_type=TransactionType(transaction_type),
                    is_fraud=True,
                    fraud_type=item.get("fraud_type") or default_fraud_type,
                    notes=notes,
                )
            )

        if len(transactions) < count:
            fallback_count = count - len(transactions)
            rules = DefenderRuleHints()
            transactions.extend(self._generate_mock_attacks(persona, rules, fallback_count))

        return transactions

    def _coerce_transactions(self, payload: list[dict[str, Any]]) -> list[Transaction]:
        transactions: list[Transaction] = []
        for item in payload:
            try:
                transactions.append(Transaction.model_validate(item))
            except Exception:
                continue
        return transactions

    def _format_persona_description(self, persona: Persona) -> str:
        return (
            f"{persona.name}, {persona.age}, {persona.occupation} in {persona.city}, {persona.country}. "
            f"Income: ${persona.income:.0f}/month. Typical categories: {', '.join(persona.spending_patterns)}. "
            f"Usual max transaction: ${persona.typical_max_transaction:.2f}."
        )

    def _format_rules_for_prompt(self, known_defender_rules: list[str]) -> str:
        return "\n".join(f"- {rule}" for rule in known_defender_rules) or "- No explicit rules supplied"

    def _format_ids_for_prompt(self, values: list[str]) -> str:
        return ", ".join(values) if values else "None"

    def _format_transactions_for_prompt(
        self,
        transactions: list[Transaction] | list[dict[str, Any]],
    ) -> str:
        if not transactions:
            return "None."

        lines: list[str] = []
        for item in transactions:
            if isinstance(item, Transaction):
                transaction = item
            else:
                try:
                    transaction = Transaction.model_validate(item)
                except Exception:
                    continue

            lines.append(
                f"- {transaction.id}: {transaction.amount:.2f} {transaction.currency} at {transaction.merchant} "
                f"({transaction.category}) in {transaction.location_city}, {transaction.location_country} "
                f"[{transaction.transaction_type.value}]"
            )

        return "\n".join(lines) if lines else "None."

    def _heuristic_inferred_pattern(
        self,
        persona: Persona,
        previous_attacks: list[Transaction],
        caught_ids: set[str],
        known_defender_rules: list[str],
    ) -> str:
        if previous_attacks:
            _, inferred_pattern = self._infer_hints_from_caught(persona, previous_attacks, caught_ids)
            return inferred_pattern

        hints = self._infer_rule_hints(known_defender_rules)
        sensitivities: list[str] = []
        if hints.amount_ceiling is not None:
            sensitivities.append(f"amounts above roughly ${hints.amount_ceiling:.2f}")
        if hints.avoids_foreign:
            sensitivities.append("foreign or off-pattern locations")
        if hints.avoids_transfers:
            sensitivities.append("transfer and withdrawal behavior")
        if hints.avoids_night:
            sensitivities.append("late-night activity")
        if hints.avoids_velocity:
            sensitivities.append("bursty transaction velocity")
        if hints.avoids_luxury:
            sensitivities.append("luxury or travel spending")

        return ", ".join(sensitivities) or "baseline deviations in merchant, location, timing, and amount"

    def _heuristic_strategy(
        self,
        persona: Persona,
        inferred_pattern: str,
        known_defender_rules: list[str],
    ) -> str:
        hints = self._infer_rule_hints(known_defender_rules)
        amount_note = ""
        if hints.amount_ceiling is not None:
            amount_note = f" Keep amounts below about ${hints.amount_ceiling:.2f}."

        if self.persona == "amateur":
            return (
                f"Use a few higher-value domestic purchases that stay just under the apparent thresholds and avoid "
                f"{inferred_pattern}.{amount_note}"
            ).strip()
        if self.persona == "botnet":
            return (
                f"Distribute low-value transactions across domestic merchants and varied categories while avoiding "
                f"{inferred_pattern}.{amount_note}"
            ).strip()
        return (
            f"Shadow {persona.name}'s normal merchants, domestic locations, and slightly-above-baseline amounts "
            f"while avoiding {inferred_pattern}.{amount_note}"
        ).strip()

    def _coerce_message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
                else:
                    parts.append(str(item))
            return "\n".join(parts).strip()
        return str(content).strip()

    def _parse_json_response(self, raw_text: str) -> Any:
        cleaned = self._strip_markdown_fences(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = min((index for index in (cleaned.find("{"), cleaned.find("[")) if index != -1), default=-1)
            end = max(cleaned.rfind("}"), cleaned.rfind("]"))
            if start != -1 and end != -1 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise

    def _coerce_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "yes", "1", "acceptable", "accept"}
        return bool(value)

    def _default_fraud_type(self) -> str:
        if self.persona == "botnet":
            return "smurfing"
        if self.persona == "amateur":
            return "account_takeover"
        return "synthetic_identity"

    def _build_transaction(
        self,
        *,
        persona: Persona,
        amount: float,
        merchant: str,
        category: str,
        transaction_type: TransactionType,
        location_city: str,
        location_country: str,
        fraud_type: str,
        notes: str,
        timestamp: str,
    ) -> Transaction:
        return Transaction(
            id=self._random_transaction_id(),
            timestamp=timestamp,
            user_id=persona.id,
            amount=round(amount, 2),
            currency="CAD",
            merchant=merchant,
            category=category,
            location_city=location_city,
            location_country=location_country,
            transaction_type=transaction_type,
            is_fraud=True,
            fraud_type=fraud_type,
            notes=notes,
        )

    def _build_timestamp(
        self,
        index: int,
        *,
        rapid: bool = False,
        avoid_night: bool = False,
        slow: bool = False,
    ) -> str:
        start = datetime.now().replace(second=0, microsecond=0)
        if slow:
            timestamp = start + timedelta(days=index, hours=18 + (index % 3), minutes=random.randint(0, 35))
        elif rapid:
            timestamp = start + timedelta(minutes=index * random.randint(1, 4))
        else:
            timestamp = start + timedelta(hours=index * 2, minutes=random.randint(0, 40))

        if avoid_night:
            timestamp = timestamp.replace(hour=random.randint(9, 20))
        elif not rapid and self.persona == "patient":
            timestamp = timestamp.replace(hour=random.randint(17, 22))

        return timestamp.isoformat()

    def _random_transaction_id(self) -> str:
        return str(uuid.uuid4())

    def _default_transaction_type_for_category(
        self,
        category: str,
        fallback: TransactionType | None = None,
    ) -> TransactionType:
        lowered = category.lower()
        if lowered in {"transfer", "remittances", "payroll"}:
            return TransactionType.TRANSFER
        if lowered in {"withdrawal"}:
            return TransactionType.WITHDRAWAL
        if lowered in {"deposit"}:
            return TransactionType.DEPOSIT
        return TransactionType.PURCHASE

    def _strip_markdown_fences(self, raw_text: str) -> str:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _is_rate_limited_error(self, exc: Exception) -> bool:
        error_str = str(exc).lower()
        return any(token in error_str for token in ("429", "rate", "quota", "limit"))

    def _summarize_exception(self, exc: Exception) -> str:
        text = str(exc).strip()
        return text or exc.__class__.__name__

    def _is_night(self, timestamp: str) -> bool:
        hour = datetime.fromisoformat(timestamp).hour
        return 0 <= hour <= 5
