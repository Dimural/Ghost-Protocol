"""
Ghost Protocol — Match Management Routes

Creates and manages the canonical match records the frontend will use to launch
and inspect simulations.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.match_state import (
    MATCH_STATE_STORE,
    MatchState,
    calculate_match_expiry,
    is_match_expired,
    utc_now,
)
from backend.core.referee import MatchScore

router = APIRouter(prefix="/api/match", tags=["match"])


class CreateMatchRequest(BaseModel):
    scenario_name: str = Field(min_length=1)
    criminal_persona: str = Field(pattern="^(amateur|patient|botnet)$")
    total_rounds: int = Field(ge=1, le=10)


class CreateMatchResponse(BaseModel):
    match_id: str
    status: str
    share_url: str


def _require_match(match_id: str) -> MatchState:
    match_state = MATCH_STATE_STORE.load(match_id)
    if match_state is None:
        raise HTTPException(status_code=404, detail=f"Match '{match_id}' was not found.")
    return match_state


def _require_modifiable_match(match_id: str) -> MatchState:
    match_state = _require_match(match_id)
    if is_match_expired(match_state):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match '{match_id}' has expired and is now archived. "
                "Archived matches are read-only."
            ),
        )
    return match_state


@router.post("/create", response_model=CreateMatchResponse)
async def create_match(request: CreateMatchRequest) -> CreateMatchResponse:
    match_id = uuid.uuid4().hex
    share_url = f"/match/{match_id}"
    timestamp = utc_now()

    state = MatchState(
        match_id=match_id,
        scenario_name=request.scenario_name,
        status="setup",
        current_round=0,
        total_rounds=request.total_rounds,
        transactions=[],
        defender_decisions=[],
        attack_rounds=[],
        started_at=timestamp,
        ended_at=None,
        share_url=share_url,
        expires_at=calculate_match_expiry(timestamp),
        criminal_persona=request.criminal_persona,
        updated_at=timestamp,
    )
    MATCH_STATE_STORE.save(state)

    return CreateMatchResponse(
        match_id=match_id,
        status=state.status,
        share_url=share_url,
    )


@router.get("/{match_id}", response_model=MatchState)
async def get_match(match_id: str) -> MatchState:
    return _require_match(match_id)


@router.post("/{match_id}/start", response_model=MatchState)
async def start_match(match_id: str) -> MatchState:
    state = _require_modifiable_match(match_id)
    timestamp = utc_now()
    updated_state = state.model_copy(
        update={
            "status": "running",
            "started_at": timestamp,
            "ended_at": None,
            "updated_at": timestamp,
        }
    )
    MATCH_STATE_STORE.save(updated_state)
    return updated_state


@router.post("/{match_id}/pause", response_model=MatchState)
async def pause_match(match_id: str) -> MatchState:
    state = _require_modifiable_match(match_id)
    updated_state = state.model_copy(
        update={
            "status": "paused",
            "updated_at": utc_now(),
        }
    )
    MATCH_STATE_STORE.save(updated_state)
    return updated_state


@router.post("/{match_id}/reset", response_model=MatchState)
async def reset_match(match_id: str) -> MatchState:
    state = _require_modifiable_match(match_id)
    timestamp = utc_now()
    updated_state = state.model_copy(
        update={
            "status": "setup",
            "current_round": 0,
            "transactions": [],
            "defender_decisions": [],
            "score": MatchScore(),
            "attack_rounds": [],
            "latest_notification": None,
            "started_at": timestamp,
            "ended_at": None,
            "updated_at": timestamp,
        }
    )
    MATCH_STATE_STORE.save(updated_state)
    return updated_state
