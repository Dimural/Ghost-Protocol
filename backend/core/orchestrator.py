"""
Ghost Protocol — Match Orchestrator

Runs the full simulation loop for a match: attack generation, defender
evaluation, referee scoring, websocket emission, and round-to-round attacker
adaptation.
"""
from __future__ import annotations

import asyncio
import hashlib

from backend.agents.criminal_agent import CriminalAgent
from backend.agents.police_agent import PoliceAgent
from backend.core.dispatcher import WebhookDispatcher
from backend.core.match_state import (
    AttackRound,
    AdaptationNotification,
    MATCH_STATE_STORE,
    MatchState,
    utc_now,
)
from backend.core.referee import RefereeEngine
from backend.data.generator import load_personas
from backend.data.models import DefenderDecision, Persona, Transaction
from backend.routes.defender import get_defender_registration
from backend.routes.websocket import (
    build_match_event_emitter,
    emit_attacker_adapting,
    emit_match_complete,
)

DEFAULT_ATTACKS_PER_ROUND = 10
TRANSACTION_DELAY_SECONDS = 0.3
ROUND_DELAY_SECONDS = 1.5

PERSONAS = load_personas()
PERSONAS_BY_ID = {persona.id: persona for persona in PERSONAS}


class MatchOrchestrator:
    """Drive a match from start through completion using the canonical state."""

    def __init__(self) -> None:
        self._match_store = MATCH_STATE_STORE
        self._referee = RefereeEngine()

    async def run_match(self, match_id: str) -> None:
        current_state = self._load_required_match(match_id)
        current_state = self._validate_ready_state(current_state)

        criminal_agent = CriminalAgent(persona=current_state.criminal_persona)
        target_persona = self._resolve_target_persona(current_state)
        police_agent = PoliceAgent() if current_state.defender_mode == "police_ai" else None
        webhook_url = self._resolve_webhook_url(current_state)
        current_state_ref = {"state": current_state}
        dispatcher = (
            WebhookDispatcher(
                history_resolver=lambda transaction: self._recent_history_for_transaction(
                    current_state_ref["state"], transaction
                )
            )
            if current_state.defender_mode == "webhook"
            else None
        )
        emitter = build_match_event_emitter(match_id)

        try:
            current_state = await self._ensure_round_ready(
                current_state,
                criminal_agent,
                target_persona,
            )
            current_state_ref["state"] = current_state

            while True:
                current_state = self._load_required_match(match_id)
                current_state_ref["state"] = current_state
                if current_state.status != "running":
                    return

                current_round = self._current_round_record(current_state)
                current_state, caught_ids = await self._process_round(
                    current_state,
                    current_round,
                    police_agent=police_agent,
                    dispatcher=dispatcher,
                    webhook_url=webhook_url,
                    emitter=emitter,
                )
                current_state_ref["state"] = current_state

                if current_state.current_round >= current_state.total_rounds:
                    completed_state = current_state.model_copy(
                        update={
                            "status": "complete",
                            "ended_at": utc_now(),
                            "latest_notification": None,
                            "updated_at": utc_now(),
                        }
                    )
                    await emit_match_complete(match_id, completed_state.score)
                    self._match_store.save(completed_state)
                    return

                next_round_number = current_state.current_round + 1
                next_attacks = await criminal_agent.adapt(current_round.attacks, caught_ids)
                notification = AdaptationNotification(
                    round=next_round_number,
                    total_rounds=current_state.total_rounds,
                    reasoning=criminal_agent.last_adaptation_reasoning,
                    banner_message=self._build_banner_message(
                        next_round_number,
                        current_state.total_rounds,
                        criminal_agent.last_adaptation_reasoning,
                    ),
                    created_at=utc_now(),
                )
                current_state = self._append_attack_round(
                    current_state,
                    round_number=next_round_number,
                    attacks=next_attacks,
                    strategy_notes=criminal_agent.last_strategy_notes,
                    adaptation_reasoning=criminal_agent.last_adaptation_reasoning,
                    notification=notification,
                )
                self._match_store.save(current_state)
                current_state_ref["state"] = current_state

                await emit_attacker_adapting(match_id, notification)
                await asyncio.sleep(ROUND_DELAY_SECONDS)
        except Exception:
            latest_state = self._match_store.load(match_id)
            if latest_state is not None and latest_state.status == "running":
                self._match_store.save(
                    latest_state.model_copy(
                        update={
                            "status": "paused",
                            "updated_at": utc_now(),
                        }
                    )
                )
            raise

    def _load_required_match(self, match_id: str) -> MatchState:
        match_state = self._match_store.load(match_id)
        if match_state is None:
            raise ValueError(f"Match '{match_id}' was not found.")
        return match_state

    def _validate_ready_state(self, match_state: MatchState) -> MatchState:
        if match_state.criminal_persona is None:
            raise ValueError(f"Match '{match_state.match_id}' is missing its criminal persona.")
        if match_state.defender_mode is None:
            raise ValueError(
                f"Match '{match_state.match_id}' does not have a registered defender yet."
            )
        return match_state

    def _resolve_target_persona(self, match_state: MatchState) -> Persona:
        target_persona_id = match_state.target_persona_id or self._stable_default_persona_id(
            match_state.match_id
        )
        persona = PERSONAS_BY_ID.get(target_persona_id)
        if persona is None:
            raise ValueError(f"Unknown target persona '{target_persona_id}'.")
        return persona

    def _resolve_webhook_url(self, match_state: MatchState) -> str | None:
        if match_state.defender_mode != "webhook":
            return None

        registration = get_defender_registration(match_state.match_id)
        if registration is None or not registration.webhook_url:
            raise ValueError(
                f"Match '{match_state.match_id}' is configured for webhook mode but has no "
                "stored webhook URL."
            )
        return registration.webhook_url

    async def _ensure_round_ready(
        self,
        match_state: MatchState,
        criminal_agent: CriminalAgent,
        target_persona: Persona,
    ) -> MatchState:
        if match_state.current_round > 0 and len(match_state.attack_rounds) >= match_state.current_round:
            return match_state

        attacks = await criminal_agent.generate_attacks(
            target_persona=target_persona,
            known_defender_rules=match_state.known_defender_rules,
            count=self._attack_count_for_state(match_state),
        )
        updated_state = self._append_attack_round(
            match_state,
            round_number=1,
            attacks=attacks,
            strategy_notes=criminal_agent.last_strategy_notes,
            adaptation_reasoning=None,
            notification=None,
        )
        self._match_store.save(updated_state)
        return updated_state

    async def _process_round(
        self,
        match_state: MatchState,
        attack_round: AttackRound,
        *,
        police_agent: PoliceAgent | None,
        dispatcher: WebhookDispatcher | None,
        webhook_url: str | None,
        emitter,
    ) -> tuple[MatchState, list[str]]:
        current_state = match_state
        processed_ids = {decision.transaction_id for decision in current_state.defender_decisions}
        caught_ids = set(self._caught_ids_for_round(current_state, attack_round.attacks))
        pending_attacks = [tx for tx in attack_round.attacks if tx.id not in processed_ids]

        for index, transaction in enumerate(pending_attacks):
            latest_state = self._load_required_match(current_state.match_id)
            if latest_state.status != "running":
                return latest_state, sorted(caught_ids)

            current_state = latest_state
            decision = await self._evaluate_transaction(
                current_state,
                transaction,
                police_agent=police_agent,
                dispatcher=dispatcher,
                webhook_url=webhook_url,
            )
            result = await self._referee.score_transaction(
                current_state,
                transaction,
                decision,
                emitter=emitter,
            )
            current_state = result.match_state.model_copy(
                update={
                    "status": "running",
                    "updated_at": utc_now(),
                }
            )
            self._match_store.save(current_state)

            if result.event.outcome == "true_positive":
                caught_ids.add(transaction.id)

            if index < len(pending_attacks) - 1:
                await asyncio.sleep(TRANSACTION_DELAY_SECONDS)

        current_state = self._update_round_caught_ids(current_state, attack_round.round, caught_ids)
        self._match_store.save(current_state)
        return current_state, sorted(caught_ids)

    async def _evaluate_transaction(
        self,
        match_state: MatchState,
        transaction: Transaction,
        *,
        police_agent: PoliceAgent | None,
        dispatcher: WebhookDispatcher | None,
        webhook_url: str | None,
    ) -> DefenderDecision:
        recent_transactions = self._recent_history_for_transaction(match_state, transaction)

        if match_state.defender_mode == "police_ai":
            if police_agent is None:
                raise ValueError("Police AI defender mode requested without a PoliceAgent instance.")
            return await police_agent.evaluate_transaction(transaction, recent_transactions)

        if dispatcher is None or webhook_url is None:
            raise ValueError("Webhook defender mode requested without a dispatcher or webhook URL.")
        return await dispatcher.dispatch(
            transaction,
            webhook_url,
            match_id=match_state.match_id,
        )

    def _recent_history_for_transaction(
        self,
        match_state: MatchState,
        transaction: Transaction,
    ) -> list[Transaction]:
        transactions_by_id = {item.id: item for item in match_state.transactions}
        recent_transactions: list[Transaction] = []

        for decision in match_state.defender_decisions:
            prior = transactions_by_id.get(decision.transaction_id)
            if prior is None or prior.user_id != transaction.user_id:
                continue
            if prior.id == transaction.id:
                continue
            recent_transactions.append(prior)

        return recent_transactions[-5:]

    def _caught_ids_for_round(
        self,
        match_state: MatchState,
        attacks: list[Transaction],
    ) -> list[str]:
        attacks_by_id = {attack.id: attack for attack in attacks}
        caught_ids: list[str] = []

        for decision in match_state.defender_decisions:
            transaction = attacks_by_id.get(decision.transaction_id)
            if transaction is None:
                continue
            if transaction.is_fraud and decision.decision == "DENY":
                caught_ids.append(transaction.id)

        return caught_ids

    def _current_round_record(self, match_state: MatchState) -> AttackRound:
        if match_state.current_round <= 0:
            raise ValueError(f"Match '{match_state.match_id}' has not initialized round 1 yet.")

        for attack_round in match_state.attack_rounds:
            if attack_round.round == match_state.current_round:
                return attack_round

        raise ValueError(
            f"Match '{match_state.match_id}' is missing attack data for round {match_state.current_round}."
        )

    def _append_attack_round(
        self,
        match_state: MatchState,
        *,
        round_number: int,
        attacks: list[Transaction],
        strategy_notes: str | None,
        adaptation_reasoning: str | None,
        notification: AdaptationNotification | None,
    ) -> MatchState:
        transactions = list(match_state.transactions)
        existing_ids = {transaction.id for transaction in transactions}
        for attack in attacks:
            if attack.id not in existing_ids:
                transactions.append(attack)
                existing_ids.add(attack.id)

        updated_rounds = [
            attack_round
            for attack_round in match_state.attack_rounds
            if attack_round.round != round_number
        ]
        updated_rounds.append(
            AttackRound(
                round=round_number,
                attacks=attacks,
                caught_ids=[],
                strategy_notes=strategy_notes,
                adaptation_reasoning=adaptation_reasoning,
                notification=notification,
                created_at=utc_now(),
            )
        )
        updated_rounds.sort(key=lambda attack_round: attack_round.round)

        return match_state.model_copy(
            update={
                "status": "running",
                "current_round": round_number,
                "transactions": transactions,
                "attack_rounds": updated_rounds,
                "target_persona_id": match_state.target_persona_id
                or self._stable_default_persona_id(match_state.match_id),
                "latest_notification": notification,
                "updated_at": utc_now(),
            }
        )

    def _update_round_caught_ids(
        self,
        match_state: MatchState,
        round_number: int,
        caught_ids: set[str],
    ) -> MatchState:
        updated_rounds: list[AttackRound] = []
        for attack_round in match_state.attack_rounds:
            if attack_round.round == round_number:
                updated_rounds.append(
                    attack_round.model_copy(update={"caught_ids": sorted(caught_ids)})
                )
                continue
            updated_rounds.append(attack_round)

        return match_state.model_copy(
            update={
                "attack_rounds": updated_rounds,
                "updated_at": utc_now(),
            }
        )

    def _attack_count_for_state(self, match_state: MatchState) -> int:
        return DEFAULT_ATTACKS_PER_ROUND

    def _stable_default_persona_id(self, match_id: str) -> str:
        digest = hashlib.sha256(match_id.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(PERSONAS)
        return PERSONAS[index].id

    def _build_banner_message(self, round_number: int, total_rounds: int, reasoning: str) -> str:
        return (
            f"🔴 ATTACKER IS ADAPTING... Round {round_number} of {total_rounds}\n"
            f"{reasoning}"
        )


MATCH_ORCHESTRATOR = MatchOrchestrator()
