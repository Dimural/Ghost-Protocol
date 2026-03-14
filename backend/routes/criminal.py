"""
Ghost Protocol — Criminal Agent Routes

Endpoints for generating and adapting attack waves from the Criminal Agent.
State continuity prefers Redis when configured and falls back to a local JSON
file in the system temp directory when Redis is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.criminal_agent import CriminalAgent
from backend.config import REDIS_URL, USE_MOCK_LLM
from backend.data.generator import load_personas
from backend.data.models import Transaction

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


class AdaptationNotification(BaseModel):
    type: Literal["ATTACKER_ADAPTING"] = "ATTACKER_ADAPTING"
    title: str = "🔴 ATTACKER IS ADAPTING..."
    round: int
    total_rounds: int
    reasoning: str
    banner_message: str
    created_at: str


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


class StoredAttackRound(BaseModel):
    round: int
    attacks: list[Transaction]
    caught_ids: list[str] = Field(default_factory=list)
    strategy_notes: str | None = None
    adaptation_reasoning: str | None = None
    notification: AdaptationNotification | None = None
    created_at: str


class MatchAttackState(BaseModel):
    match_id: str
    criminal_persona: Literal["amateur", "patient", "botnet"]
    target_persona_id: str
    known_defender_rules: list[str] = Field(default_factory=list)
    total_rounds: int = 3
    current_round: int = 1
    status: Literal["running", "complete"] = "running"
    last_attacks: list[Transaction] = Field(default_factory=list)
    attack_rounds: list[StoredAttackRound] = Field(default_factory=list)
    latest_notification: AdaptationNotification | None = None
    updated_at: str


class MatchStateStore:
    def __init__(self) -> None:
        self._fallback_path = Path(tempfile.gettempdir()) / "ghost_protocol_attack_matches.json"
        self._redis_client = self._build_redis_client()

    def load(self, match_id: str) -> MatchAttackState | None:
        raw = self._load_payload(match_id)
        if raw is None:
            return None
        return MatchAttackState.model_validate(raw)

    def save(self, state: MatchAttackState) -> None:
        payload = state.model_dump(mode="json")
        if self._redis_client is not None:
            try:
                self._redis_client.set(self._redis_key(state.match_id), json.dumps(payload), ex=86400)
                return
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        fallback_payload[state.match_id] = payload
        self._write_fallback_file(fallback_payload)

    def _load_payload(self, match_id: str) -> dict | None:
        if self._redis_client is not None:
            try:
                raw = self._redis_client.get(self._redis_key(match_id))
                if raw:
                    return json.loads(raw)
            except redis.RedisError:
                self._redis_client = None

        return self._read_fallback_file().get(match_id)

    def _build_redis_client(self) -> redis.Redis | None:
        if not REDIS_URL:
            return None

        try:
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            return client
        except redis.RedisError:
            return None

    def _redis_key(self, match_id: str) -> str:
        return f"match:{match_id}"

    def _read_fallback_file(self) -> dict:
        if not self._fallback_path.exists():
            return {}
        return json.loads(self._fallback_path.read_text())

    def _write_fallback_file(self, payload: dict) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._fallback_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._fallback_path)


_STATE_STORE = MatchStateStore()


@router.post("/generate", response_model=GenerateAttackResponse)
async def generate_attack(request: GenerateAttackRequest) -> GenerateAttackResponse:
    existing_state = _STATE_STORE.load(request.match_id)
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

    state = MatchAttackState(
        match_id=request.match_id,
        criminal_persona=request.persona,
        target_persona_id=target_persona.id,
        known_defender_rules=known_defender_rules,
        total_rounds=request.total_rounds,
        current_round=1,
        status="running",
        last_attacks=attacks,
        attack_rounds=[
            StoredAttackRound(
                round=1,
                attacks=attacks,
                strategy_notes=agent.last_strategy_notes,
                created_at=_timestamp(),
            )
        ],
        latest_notification=None,
        updated_at=_timestamp(),
    )
    _STATE_STORE.save(state)

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
    state = _STATE_STORE.load(request.match_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail="No stored criminal state found for this match. Generate attacks first.",
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
                "updated_at": _timestamp(),
            }
        )
        _STATE_STORE.save(updated_state)

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
        created_at=_timestamp(),
    )
    updated_rounds.append(
        StoredAttackRound(
            round=next_round,
            attacks=new_attacks,
            strategy_notes=agent.last_strategy_notes,
            adaptation_reasoning=agent.last_adaptation_reasoning,
            notification=notification,
            created_at=_timestamp(),
        )
    )

    updated_state = state.model_copy(
        update={
            "current_round": next_round,
            "status": "running",
            "last_attacks": new_attacks,
            "attack_rounds": updated_rounds,
            "latest_notification": notification,
            "updated_at": _timestamp(),
        }
    )
    _STATE_STORE.save(updated_state)

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
    existing_state: MatchAttackState | None,
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


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_mode() -> Literal["mock", "gemini"]:
    return "mock" if USE_MOCK_LLM else "gemini"


def _build_banner_message(round_number: int, total_rounds: int, reasoning: str) -> str:
    return (
        f"🔴 ATTACKER IS ADAPTING... Round {round_number} of {total_rounds}\n"
        f"{reasoning}"
    )
