"""
Ghost Protocol — Canonical Match State Manager

Provides the shared match record used by the Criminal Agent, Defender
integration, and upcoming Referee engine. Persistence prefers Redis and falls
back to a local JSON file when Redis is unavailable.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import redis
from pydantic import BaseModel, Field

from backend.config import REDIS_URL
from backend.core.adaptation_analysis import AdaptationEvidence
from backend.core.referee import MatchScore
from backend.data.models import DefenderDecision, Transaction

MatchStatus = Literal["setup", "running", "paused", "complete"]
CriminalPersona = Literal["amateur", "patient", "botnet"]
DefenderMode = Literal["webhook", "police_ai"]
MATCH_EXPIRY_HOURS = 24


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def calculate_match_expiry(created_at: str | None = None) -> str:
    base_time = parse_utc_timestamp(created_at) if created_at else datetime.now(timezone.utc)
    return (base_time + timedelta(hours=MATCH_EXPIRY_HOURS)).isoformat()


def is_expired_timestamp(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    return parse_utc_timestamp(expires_at) <= datetime.now(timezone.utc)


def is_match_expired(match_state: "MatchState") -> bool:
    return is_expired_timestamp(match_state.expires_at)


class AdaptationNotification(BaseModel):
    type: Literal["ATTACKER_ADAPTING"] = "ATTACKER_ADAPTING"
    title: str = "🔴 ATTACKER IS ADAPTING..."
    round: int
    total_rounds: int
    reasoning: str
    banner_message: str
    verified: bool | None = None
    evidence_summary: str | None = None
    created_at: str = Field(default_factory=utc_now)


class AttackRound(BaseModel):
    round: int
    attacks: list[Transaction] = Field(default_factory=list)
    caught_ids: list[str] = Field(default_factory=list)
    strategy_notes: str | None = None
    adaptation_reasoning: str | None = None
    adaptation_evidence: AdaptationEvidence | None = None
    runtime_mode: Literal["mock", "groq"] | None = None
    notification: AdaptationNotification | None = None
    created_at: str = Field(default_factory=utc_now)


class MatchState(BaseModel):
    match_id: str
    scenario_name: str = "Adversarial Sandbox Match"
    status: MatchStatus = "setup"
    current_round: int = 0
    total_rounds: int = 3
    transactions: list[Transaction] = Field(default_factory=list)
    defender_decisions: list[DefenderDecision] = Field(default_factory=list)
    score: MatchScore = Field(default_factory=MatchScore)
    attack_rounds: list[AttackRound] = Field(default_factory=list)
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None
    share_url: str | None = None
    expires_at: str | None = None
    criminal_persona: CriminalPersona | None = None
    target_persona_id: str | None = None
    known_defender_rules: list[str] = Field(default_factory=list)
    latest_notification: AdaptationNotification | None = None
    defender_id: str | None = None
    defender_mode: DefenderMode | None = None
    report_id: str | None = None
    report_generated_at: str | None = None
    updated_at: str = Field(default_factory=utc_now)

    @property
    def last_attacks(self) -> list[Transaction]:
        if not self.attack_rounds:
            return []
        return list(self.attack_rounds[-1].attacks)


class MatchStateStore:
    def __init__(self) -> None:
        self._fallback_path = Path(tempfile.gettempdir()) / "ghost_protocol_matches.json"
        self._redis_client = self._build_redis_client()

    def load(self, match_id: str) -> MatchState | None:
        raw = self._load_payload(match_id)
        if raw is None:
            return None

        payload = self._migrate_legacy_payload(raw) if self._looks_legacy(raw) else raw
        return MatchState.model_validate(payload)

    def save(self, state: MatchState) -> None:
        payload = state.model_dump(mode="json")
        if self._redis_client is not None:
            try:
                self._redis_client.set(self._redis_key(state.match_id), json.dumps(payload))
                return
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        fallback_payload[state.match_id] = payload
        self._write_fallback_file(fallback_payload)

    def delete(self, match_id: str) -> None:
        if self._redis_client is not None:
            try:
                self._redis_client.delete(self._redis_key(match_id))
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        if match_id in fallback_payload:
            del fallback_payload[match_id]
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

    def _looks_legacy(self, payload: dict) -> bool:
        return "last_attacks" in payload or (
            "attack_rounds" in payload and "transactions" not in payload and "defender_decisions" not in payload
        )

    def _migrate_legacy_payload(self, payload: dict) -> dict:
        raw_rounds = list(payload.get("attack_rounds") or [])
        if not raw_rounds and payload.get("last_attacks"):
            raw_rounds = [
                {
                    "round": payload.get("current_round", 1),
                    "attacks": payload["last_attacks"],
                    "created_at": payload.get("updated_at", utc_now()),
                }
            ]

        transactions: list[dict] = []
        for attack_round in raw_rounds:
            transactions.extend(attack_round.get("attacks") or [])

        started_at = payload.get("started_at") or payload.get("updated_at") or utc_now()
        updated_at = payload.get("updated_at") or started_at

        return {
            "match_id": payload["match_id"],
            "scenario_name": payload.get("scenario_name") or "Adversarial Sandbox Match",
            "status": payload.get("status", "setup"),
            "current_round": payload.get("current_round", len(raw_rounds)),
            "total_rounds": payload.get("total_rounds", 3),
            "transactions": transactions,
            "defender_decisions": payload.get("defender_decisions") or [],
            "score": payload.get("score") or {},
            "attack_rounds": raw_rounds,
            "started_at": started_at,
            "ended_at": payload.get("ended_at"),
            "share_url": payload.get("share_url"),
            "expires_at": payload.get("expires_at"),
            "criminal_persona": payload.get("criminal_persona"),
            "target_persona_id": payload.get("target_persona_id"),
            "known_defender_rules": payload.get("known_defender_rules") or [],
            "latest_notification": payload.get("latest_notification"),
            "defender_id": payload.get("defender_id"),
            "defender_mode": payload.get("defender_mode"),
            "report_id": payload.get("report_id"),
            "report_generated_at": payload.get("report_generated_at"),
            "updated_at": updated_at,
        }


MATCH_STATE_STORE = MatchStateStore()


def get_match_state(match_id: str) -> MatchState | None:
    return MATCH_STATE_STORE.load(match_id)


def save_match_state(state: MatchState) -> None:
    MATCH_STATE_STORE.save(state)
