"""
Ghost Protocol — Defender Registration Routes

Registers either a user-supplied webhook defender or the built-in Police AI.
Webhook registrations are probed immediately with a dummy transaction payload
and persisted by match ID using Redis when available, otherwise a local JSON
fallback file.
"""
from __future__ import annotations

import json
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import redis
from fastapi import APIRouter, HTTPException
from pydantic import AnyHttpUrl, BaseModel, Field, TypeAdapter, ValidationError, model_validator

from backend.config import REDIS_URL
from backend.core.match_state import MATCH_STATE_STORE, is_match_expired
from backend.core.dispatcher import DispatchErrorEvent, get_defender_errors
from backend.data.models import DefenderDecision, TransactionType

router = APIRouter(prefix="/api", tags=["defender"])


class RegisterDefenderRequest(BaseModel):
    match_id: str = Field(min_length=1)
    webhook_url: str | None = None
    use_police_ai: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        webhook_url = normalized.get("webhook_url")
        if isinstance(webhook_url, str):
            webhook_url = webhook_url.strip() or None

        if normalized.get("use_police_ai") is True:
            normalized["webhook_url"] = None
        else:
            normalized["webhook_url"] = webhook_url

        return normalized

    @model_validator(mode="after")
    def validate_webhook_requirement(self) -> "RegisterDefenderRequest":
        if self.use_police_ai:
            self.webhook_url = None
            return self

        if self.webhook_url is None:
            raise ValueError("webhook_url is required when use_police_ai is false.")

        self.webhook_url = str(TypeAdapter(AnyHttpUrl).validate_python(self.webhook_url))
        return self


class RegisterDefenderResponse(BaseModel):
    defender_id: str
    status: Literal["registered"] = "registered"


class TestDefenderRequest(BaseModel):
    match_id: str = Field(min_length=1)
    webhook_url: str

    @model_validator(mode="after")
    def validate_webhook_url(self) -> "TestDefenderRequest":
        self.webhook_url = str(TypeAdapter(AnyHttpUrl).validate_python(self.webhook_url.strip()))
        return self


class TestDefenderResponse(BaseModel):
    status: Literal["reachable", "unreachable"]
    raw_response: dict | None = None
    error: str | None = None


class SampleWebhookRequest(BaseModel):
    transaction_id: str = Field(min_length=1)
    amount: float = Field(ge=0.0)
    merchant: str = Field(min_length=1)
    category: str = Field(min_length=1)
    location_city: str = Field(min_length=1)
    location_country: str = Field(min_length=1)
    transaction_type: TransactionType
    user_spending_history_summary: str = Field(min_length=1)


class DefenderErrorLogResponse(BaseModel):
    match_id: str
    error_count: int
    errors: list[DispatchErrorEvent]


class StoredDefenderRegistration(BaseModel):
    defender_id: str
    match_id: str
    status: Literal["registered"] = "registered"
    mode: Literal["webhook", "police_ai"]
    webhook_url: str | None = None
    last_test_decision: DefenderDecision | None = None
    last_tested_at: str | None = None
    registered_at: str
    updated_at: str


class WebhookProbeError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class DefenderRegistrationStore:
    def __init__(self) -> None:
        self._fallback_path = (
            Path(tempfile.gettempdir()) / "ghost_protocol_defender_registrations.json"
        )
        self._redis_client = self._build_redis_client()

    def load(self, match_id: str) -> StoredDefenderRegistration | None:
        raw = self._load_payload(match_id)
        if raw is None:
            return None
        return StoredDefenderRegistration.model_validate(raw)

    def save(self, registration: StoredDefenderRegistration) -> None:
        payload = registration.model_dump(mode="json")
        if self._redis_client is not None:
            try:
                self._redis_client.set(
                    self._redis_key(registration.match_id),
                    json.dumps(payload),
                    ex=86400,
                )
                return
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        fallback_payload[registration.match_id] = payload
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
        return f"defender:{match_id}"

    def _read_fallback_file(self) -> dict:
        if not self._fallback_path.exists():
            return {}
        return json.loads(self._fallback_path.read_text())

    def _write_fallback_file(self, payload: dict) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._fallback_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._fallback_path)


_DEFENDER_STORE = DefenderRegistrationStore()


@router.post("/register-defender", response_model=RegisterDefenderResponse)
@router.post("/defender/register", response_model=RegisterDefenderResponse)
async def register_defender(
    request: RegisterDefenderRequest,
) -> RegisterDefenderResponse:
    now = _timestamp()
    existing_match = MATCH_STATE_STORE.load(request.match_id)
    if existing_match is not None and is_match_expired(existing_match):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match '{request.match_id}' has expired and is now archived. "
                "Archived matches are read-only."
            ),
        )
    defender_id = f"defender_{uuid.uuid4().hex[:12]}"

    if request.use_police_ai:
        registration = StoredDefenderRegistration(
            defender_id=defender_id,
            match_id=request.match_id,
            mode="police_ai",
            registered_at=now,
            updated_at=now,
        )
        _DEFENDER_STORE.save(registration)
        _sync_match_defender_registration(
            match_id=request.match_id,
            defender_id=registration.defender_id,
            defender_mode=registration.mode,
            updated_at=now,
        )
        return RegisterDefenderResponse(defender_id=registration.defender_id)

    webhook_url = str(request.webhook_url)
    test_payload = _build_dummy_transaction_payload(request.match_id)

    try:
        decision = await _probe_defender_webhook(webhook_url, test_payload)
    except WebhookProbeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    registration = StoredDefenderRegistration(
        defender_id=defender_id,
        match_id=request.match_id,
        mode="webhook",
        webhook_url=webhook_url,
        last_test_decision=decision,
        last_tested_at=now,
        registered_at=now,
        updated_at=now,
    )
    _DEFENDER_STORE.save(registration)
    _sync_match_defender_registration(
        match_id=request.match_id,
        defender_id=registration.defender_id,
        defender_mode=registration.mode,
        updated_at=now,
    )

    return RegisterDefenderResponse(defender_id=registration.defender_id)


@router.post("/defender/test", response_model=TestDefenderResponse)
async def test_defender_webhook(request: TestDefenderRequest) -> TestDefenderResponse:
    payload = _build_dummy_transaction_payload(request.match_id)
    timeout = httpx.Timeout(5.0, connect=2.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(request.webhook_url, json=payload)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        return TestDefenderResponse(
            status="unreachable",
            raw_response=None,
            error=f"Webhook test timed out after 5 seconds: {exc.__class__.__name__}",
        )
    except httpx.HTTPError as exc:
        return TestDefenderResponse(
            status="unreachable",
            raw_response=None,
            error=f"Webhook request failed: {exc.__class__.__name__}",
        )

    try:
        raw_response = response.json()
    except ValueError:
        return TestDefenderResponse(
            status="reachable",
            raw_response={"text": response.text},
            error=None,
        )

    if isinstance(raw_response, dict):
        return TestDefenderResponse(status="reachable", raw_response=raw_response, error=None)

    return TestDefenderResponse(
        status="reachable",
        raw_response={"response": raw_response},
        error=None,
    )


@router.post("/defender/sample-webhook", response_model=DefenderDecision)
async def sample_defender_webhook(request: SampleWebhookRequest) -> DefenderDecision:
    score, reasons = _score_sample_webhook(request)
    decision = "DENY" if score >= 0.45 else "APPROVE"
    confidence = min(0.99, 0.52 + (score * 0.45)) if decision == "DENY" else max(0.51, 0.92 - (score * 0.4))
    reason = (
        "Denied because " + "; ".join(reasons[:3]) + "."
        if decision == "DENY"
        else "Approved because no strong fraud signals were detected by the sample webhook."
    )
    return DefenderDecision(
        transaction_id=request.transaction_id,
        decision=decision,
        confidence=round(confidence, 2),
        reason=reason,
    )


@router.get("/defender/{match_id}/errors", response_model=DefenderErrorLogResponse)
async def get_defender_error_log(match_id: str) -> DefenderErrorLogResponse:
    errors = get_defender_errors(match_id)
    return DefenderErrorLogResponse(match_id=match_id, error_count=len(errors), errors=errors)


async def _probe_defender_webhook(
    webhook_url: str,
    payload: dict[str, object],
) -> DefenderDecision:
    timeout = httpx.Timeout(5.0, connect=2.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise WebhookProbeError(
            f"Webhook test timed out after 5 seconds for {webhook_url}.",
            status_code=504,
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise WebhookProbeError(
            f"Webhook test returned HTTP {exc.response.status_code} for {webhook_url}.",
            status_code=502,
        ) from exc
    except httpx.HTTPError as exc:
        raise WebhookProbeError(
            f"Webhook is unreachable at {webhook_url}: {exc.__class__.__name__}.",
            status_code=502,
        ) from exc

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise WebhookProbeError(
            "Webhook returned malformed JSON. Expected transaction_id, decision, confidence.",
            status_code=502,
        ) from exc

    if not isinstance(response_payload, dict):
        raise WebhookProbeError(
            "Webhook returned malformed JSON. Expected a JSON object response.",
            status_code=502,
        )

    decision_value = response_payload.get("decision")
    if isinstance(decision_value, str):
        response_payload["decision"] = decision_value.upper()

    try:
        decision = DefenderDecision.model_validate(response_payload)
    except ValidationError as exc:
        raise WebhookProbeError(
            "Webhook returned malformed JSON. Expected transaction_id, decision, confidence.",
            status_code=502,
        ) from exc

    if decision.transaction_id != payload["transaction_id"]:
        raise WebhookProbeError(
            "Webhook response transaction_id did not match the registration test payload.",
            status_code=502,
        )

    return decision


def _build_dummy_transaction_payload(match_id: str) -> dict[str, object]:
    suffix = match_id[-6:] if len(match_id) >= 6 else match_id
    transaction_id = f"defender-test-{suffix}-{uuid.uuid4().hex[:6]}"

    return {
        "transaction_id": transaction_id,
        "amount": 48.75,
        "merchant": "Metro",
        "category": "groceries",
        "location_city": "Toronto",
        "location_country": "Canada",
        "transaction_type": TransactionType.PURCHASE.value,
        "user_spending_history_summary": (
            "Last 5 transactions: Tim Hortons $6.40, TTC $3.35, "
            "Shoppers Drug Mart $14.20, Metro $52.10, Spotify $11.99"
        ),
    }


def _score_sample_webhook(request: SampleWebhookRequest) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    merchant_lower = request.merchant.lower()
    history_lower = request.user_spending_history_summary.lower()
    historical_amounts = [
        float(match)
        for match in re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", request.user_spending_history_summary)
    ]
    avg_history_amount = (
        sum(historical_amounts) / len(historical_amounts) if historical_amounts else None
    )

    if request.location_country != "Canada":
        score += 0.45
        reasons.append("transaction is outside Canada")

    if request.transaction_type in (TransactionType.TRANSFER, TransactionType.WITHDRAWAL):
        score += 0.25
        reasons.append("money-movement channel is higher risk")

    if request.amount >= 1000:
        score += 0.40
        reasons.append("amount is very large")
    elif request.amount >= 250:
        score += 0.20
        reasons.append("amount is elevated")

    if avg_history_amount is not None and request.amount > avg_history_amount * 2.5:
        score += 0.20
        reasons.append("amount is much larger than recent history")

    if any(keyword in merchant_lower for keyword in ("wire", "transfer", "coinbase", "crypto", "gift")):
        score += 0.25
        reasons.append("merchant looks like a fraud-prone cash-out channel")

    if request.merchant.lower() in history_lower and request.amount > 75:
        score += 0.10
        reasons.append("same merchant is being hit repeatedly")

    if request.location_city.lower() not in history_lower and request.location_country != "Canada":
        score += 0.20
        reasons.append("location is not reflected in recent history")

    if request.category.lower() not in history_lower and request.amount > 100:
        score += 0.10
        reasons.append("category is absent from recent history")

    return min(score, 1.0), reasons


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_match_defender_registration(
    match_id: str,
    defender_id: str,
    defender_mode: Literal["webhook", "police_ai"],
    updated_at: str,
) -> None:
    match_state = MATCH_STATE_STORE.load(match_id)
    if match_state is None:
        return

    MATCH_STATE_STORE.save(
        match_state.model_copy(
            update={
                "defender_id": defender_id,
                "defender_mode": defender_mode,
                "updated_at": updated_at,
            }
        )
    )


def get_defender_registration(match_id: str) -> StoredDefenderRegistration | None:
    return _DEFENDER_STORE.load(match_id)
