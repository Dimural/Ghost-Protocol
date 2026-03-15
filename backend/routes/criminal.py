"""
Ghost Protocol — Criminal Agent Routes

Endpoints for generating and adapting attack waves from the Criminal Agent.
State continuity prefers Redis when configured and falls back to a local JSON
file in the system temp directory when Redis is unavailable.
"""
from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.criminal_agent import CriminalAgent
from backend.config import USE_MOCK_LLM
from backend.core.match_state import (
    AttackRound,
    AdaptationNotification,
    MATCH_STATE_STORE,
    MatchState,
    is_match_expired,
    utc_now,
)
from backend.data.generator import load_personas
from backend.data.models import Transaction
from backend.routes.websocket import emit_attacker_adapting

router = APIRouter(prefix="/api/attack", tags=["criminal"])

PERSONAS = load_personas()
PERSONAS_BY_ID = {persona.id: persona for persona in PERSONAS}


class GenerateAttackRequest(BaseModel):
    match_id: str = Field(min_length=1)
    persona: Literal["amateur", "patient", "botnet"]
    count: int = Field(default=10, ge=1, le=100)
    total_rounds: int = Field(default=3, ge=1, le=10)
    target_persona_id: str | None = None
    known_defender_rules: list[str] = Field(default_factory=list)


class GenerateAttackResponse(BaseModel):
    attacks: list[Transaction]
    strategy_notes: str
    match_id: str
    round: int
    total_rounds: int
    status: Literal["running", "complete"]
    target_persona_id: str
    mode: Literal["mock", "gemini"]


class AdaptAttackRequest(BaseModel):
    match_id: str = Field(min_length=1)
    caught_ids: list[str] = Field(default_factory=list)


class AdaptAttackResponse(BaseModel):
    new_attacks: list[Transaction]
    adaptation_reasoning: str
    match_id: str
    round: int
    total_rounds: int
    status: Literal["running", "complete"]
    cycle_complete: bool
    notification: AdaptationNotification | None = None
    mode: Literal["mock", "gemini"]


@router.post("/generate", response_model=GenerateAttackResponse)
async def generate_attack(request: GenerateAttackRequest) -> GenerateAttackResponse:
    existing_state = MATCH_STATE_STORE.load(request.match_id)
    if existing_state is not None and is_match_expired(existing_state):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match '{request.match_id}' has expired and is now archived. "
                "Archived matches are read-only."
            ),
        )
    target_persona = _resolve_target_persona(request.match_id, request.target_persona_id, existing_state)
    known_defender_rules = request.known_defender_rules or (
        existing_state.known_defender_rules if existing_state else []
    )

    agent = CriminalAgent(persona=request.persona)
    attacks = await agent.generate_attacks(
        target_persona=target_persona,
        known_defender_rules=known_defender_rules,
        count=request.count,
    )

    # Regenerating attacks for a match resets the criminal cycle and canonical
    # match transcript so future Referee scoring starts from a clean slate.
    state = MatchState(
        match_id=request.match_id,
        scenario_name=existing_state.scenario_name if existing_state else "Adversarial Sandbox Match",
        status="running",
        current_round=1,
        total_rounds=request.total_rounds,
        transactions=list(attacks),
        defender_decisions=[],
        attack_rounds=[
            AttackRound(
                round=1,
                attacks=attacks,
                strategy_notes=agent.last_strategy_notes,
                created_at=utc_now(),
            )
        ],
        started_at=utc_now(),
        ended_at=None,
        share_url=existing_state.share_url if existing_state else None,
        expires_at=existing_state.expires_at if existing_state else None,
        criminal_persona=request.persona,
        target_persona_id=target_persona.id,
        known_defender_rules=known_defender_rules,
        latest_notification=None,
        defender_id=existing_state.defender_id if existing_state else None,
        defender_mode=existing_state.defender_mode if existing_state else None,
        updated_at=utc_now(),
    )
    MATCH_STATE_STORE.save(state)

    return GenerateAttackResponse(
        attacks=attacks,
        strategy_notes=agent.last_strategy_notes,
        match_id=request.match_id,
        round=1,
        total_rounds=request.total_rounds,
        status="running",
        target_persona_id=target_persona.id,
        mode=_runtime_mode(),
    )


@router.post("/adapt", response_model=AdaptAttackResponse)
async def adapt_attack(request: AdaptAttackRequest) -> AdaptAttackResponse:
    state = MATCH_STATE_STORE.load(request.match_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail="No stored criminal state found for this match. Generate attacks first.",
        )
    if is_match_expired(state):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match '{request.match_id}' has expired and is now archived. "
                "Archived matches are read-only."
            ),
        )

    if state.criminal_persona is None:
        raise HTTPException(
            status_code=409,
            detail="This match is missing its criminal persona and cannot adapt yet.",
        )

    if not state.last_attacks:
        raise HTTPException(
            status_code=409,
            detail="This match has no previous attacks to adapt from.",
        )

    updated_rounds = list(state.attack_rounds)
    if updated_rounds:
        updated_rounds[-1] = updated_rounds[-1].model_copy(
            update={"caught_ids": list(request.caught_ids)}
        )

    if state.current_round >= state.total_rounds:
        updated_state = state.model_copy(
            update={
                "status": "complete",
                "attack_rounds": updated_rounds,
                "latest_notification": None,
                "ended_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        MATCH_STATE_STORE.save(updated_state)

        return AdaptAttackResponse(
            new_attacks=[],
            adaptation_reasoning="Attack cycle complete. All configured rounds have been processed.",
            match_id=request.match_id,
            round=state.current_round,
            total_rounds=state.total_rounds,
            status="complete",
            cycle_complete=True,
            notification=None,
            mode=_runtime_mode(),
        )

    agent = CriminalAgent(persona=state.criminal_persona)
    new_attacks = await agent.adapt(state.last_attacks, request.caught_ids)

    next_round = state.current_round + 1
    notification = AdaptationNotification(
        round=next_round,
        total_rounds=state.total_rounds,
        reasoning=agent.last_adaptation_reasoning,
        banner_message=_build_banner_message(next_round, state.total_rounds, agent.last_adaptation_reasoning),
        created_at=utc_now(),
    )
    updated_rounds.append(
        AttackRound(
            round=next_round,
            attacks=new_attacks,
            strategy_notes=agent.last_strategy_notes,
            adaptation_reasoning=agent.last_adaptation_reasoning,
            notification=notification,
            created_at=utc_now(),
        )
    )

    updated_state = state.model_copy(
        update={
            "current_round": next_round,
            "status": "running",
            "transactions": [*state.transactions, *new_attacks],
            "attack_rounds": updated_rounds,
            "latest_notification": notification,
            "updated_at": utc_now(),
        }
    )
    MATCH_STATE_STORE.save(updated_state)
    await emit_attacker_adapting(request.match_id, notification)

    return AdaptAttackResponse(
        new_attacks=new_attacks,
        adaptation_reasoning=agent.last_adaptation_reasoning,
        match_id=request.match_id,
        round=next_round,
        total_rounds=state.total_rounds,
        status="running",
        cycle_complete=False,
        notification=notification,
        mode=_runtime_mode(),
    )


def _resolve_target_persona(
    match_id: str,
    requested_persona_id: str | None,
    existing_state: MatchState | None,
):
    target_persona_id = requested_persona_id
    if target_persona_id is None and existing_state is not None:
        target_persona_id = existing_state.target_persona_id

    if target_persona_id is None:
        target_persona_id = _stable_default_persona_id(match_id)

    persona = PERSONAS_BY_ID.get(target_persona_id)
    if persona is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown target_persona_id '{target_persona_id}'.",
        )
    return persona


def _stable_default_persona_id(match_id: str) -> str:
    digest = hashlib.sha256(match_id.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(PERSONAS)
    return PERSONAS[index].id


def _runtime_mode() -> Literal["mock", "gemini"]:
    return "mock" if USE_MOCK_LLM else "gemini"


def _build_banner_message(round_number: int, total_rounds: int, reasoning: str) -> str:
    return (
        f"🔴 ATTACKER IS ADAPTING... Round {round_number} of {total_rounds}\n"
        f"{reasoning}"
    )
