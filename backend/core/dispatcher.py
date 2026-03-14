"""
Ghost Protocol — Defender Webhook Dispatcher

Sends defender-safe transaction payloads to user webhooks and normalizes the
response into DefenderDecision objects. Timeouts and upstream errors fall back
to APPROVE so the match can continue without crashing.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Sequence

import httpx
import redis
from pydantic import BaseModel, ValidationError

from backend.config import REDIS_URL
from backend.data.models import DefenderDecision, Transaction


class DispatchErrorEvent(BaseModel):
    match_id: str | None = None
    transaction_id: str
    defender_url: str
    error_label: Literal["Defender Error", "Timeout", "Parse Error"]
    error_type: Literal[
        "timeout",
        "http_error",
        "transport_error",
        "parse_error",
        "invalid_response",
    ]
    message: str
    counts_as_missed_fraud: bool
    referee_outcome: Literal["false_negative", "true_negative"]
    war_room_visible: bool = True
    created_at: str


class DefenderErrorStore:
    def __init__(self) -> None:
        self._fallback_path = Path(tempfile.gettempdir()) / "ghost_protocol_defender_errors.json"
        self._redis_client = self._build_redis_client()

    def list(self, match_id: str) -> list[DispatchErrorEvent]:
        payload = self._load_payload(match_id)
        if payload is None:
            return []
        return [DispatchErrorEvent.model_validate(item) for item in payload]

    def append(self, event: DispatchErrorEvent) -> None:
        if event.match_id is None:
            return

        payload = [item.model_dump(mode="json") for item in self.list(event.match_id)]
        payload.append(event.model_dump(mode="json"))

        if self._redis_client is not None:
            try:
                self._redis_client.set(self._redis_key(event.match_id), json.dumps(payload), ex=86400)
                return
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        fallback_payload[event.match_id] = payload
        self._write_fallback_file(fallback_payload)

    def clear(self, match_id: str) -> None:
        if self._redis_client is not None:
            try:
                self._redis_client.delete(self._redis_key(match_id))
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        if match_id in fallback_payload:
            del fallback_payload[match_id]
            self._write_fallback_file(fallback_payload)

    def _load_payload(self, match_id: str) -> list[dict] | None:
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
        return f"defender-errors:{match_id}"

    def _read_fallback_file(self) -> dict:
        if not self._fallback_path.exists():
            return {}
        return json.loads(self._fallback_path.read_text())

    def _write_fallback_file(self, payload: dict) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._fallback_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._fallback_path)


_ERROR_STORE = DefenderErrorStore()


class WebhookDispatcher:
    """Dispatch transactions to a defender webhook without leaking ground truth."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        history_resolver: Callable[[Transaction], Sequence[Transaction]] | None = None,
        error_store: DefenderErrorStore | None = None,
    ) -> None:
        self._transport = transport
        self._history_resolver = history_resolver
        self._error_store = error_store or _ERROR_STORE
        self.error_events: list[DispatchErrorEvent] = []

    async def dispatch(
        self,
        transaction: Transaction,
        defender_url: str,
        timeout_seconds: int = 5,
        match_id: str | None = None,
    ) -> DefenderDecision:
        payload = self._build_payload(transaction)

        try:
            response = await self._post_json(defender_url, payload, timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Timeout",
                error_type="timeout",
                message=f"Defender timed out after {timeout_seconds} seconds.",
                reason_prefix="Timeout",
            )
        except httpx.HTTPStatusError as exc:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Defender Error",
                error_type="http_error",
                message=f"Defender returned HTTP {exc.response.status_code}.",
                reason_prefix="Defender Error",
            )
        except httpx.HTTPError as exc:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Defender Error",
                error_type="transport_error",
                message=f"Unable to reach defender: {exc.__class__.__name__}.",
                reason_prefix="Defender Error",
            )

        return self._parse_response(
            transaction=transaction,
            match_id=match_id,
            defender_url=defender_url,
            response=response,
        )

    async def dispatch_batch(
        self,
        transactions: list[Transaction],
        defender_url: str,
        timeout_seconds: int = 5,
        match_id: str | None = None,
    ) -> list[DefenderDecision]:
        return await asyncio.gather(
            *[
                self.dispatch(
                    transaction=transaction,
                    defender_url=defender_url,
                    timeout_seconds=timeout_seconds,
                    match_id=match_id,
                )
                for transaction in transactions
            ]
        )

    async def _post_json(
        self,
        defender_url: str,
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> httpx.Response:
        timeout = httpx.Timeout(float(timeout_seconds), connect=min(2.0, float(timeout_seconds)))
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            return await client.post(defender_url, json=payload)

    def _build_payload(self, transaction: Transaction) -> dict[str, object]:
        return {
            "transaction_id": transaction.id,
            "amount": transaction.amount,
            "merchant": transaction.merchant,
            "category": transaction.category,
            "location_city": transaction.location_city,
            "location_country": transaction.location_country,
            "transaction_type": transaction.transaction_type.value,
            "user_spending_history_summary": self._build_history_summary(transaction),
        }

    def _build_history_summary(self, transaction: Transaction) -> str:
        if self._history_resolver is None:
            return "No recent transaction history available."

        recent_transactions = list(self._history_resolver(transaction))
        if not recent_transactions:
            return "No recent transaction history available."

        summary_parts = []
        for prior in recent_transactions[-5:]:
            summary_parts.append(
                f"{prior.merchant} ${prior.amount:.2f} in {prior.location_city}"
            )
        return "Last transactions: " + ", ".join(summary_parts)

    def _parse_response(
        self,
        transaction: Transaction,
        match_id: str | None,
        defender_url: str,
        response: httpx.Response,
    ) -> DefenderDecision:
        try:
            payload = response.json()
        except ValueError:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Parse Error",
                error_type="parse_error",
                message="Defender returned malformed JSON.",
                reason_prefix="Parse Error",
            )

        if not isinstance(payload, dict):
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Defender Error",
                error_type="invalid_response",
                message="Defender response was not a JSON object.",
                reason_prefix="Defender Error",
            )

        decision_value = payload.get("decision")
        if isinstance(decision_value, str):
            payload["decision"] = decision_value.upper()

        try:
            decision = DefenderDecision.model_validate(payload)
        except ValidationError:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Parse Error",
                error_type="invalid_response",
                message="Defender response did not match DefenderDecision schema.",
                reason_prefix="Parse Error",
            )

        if decision.transaction_id != transaction.id:
            return self._fallback_approval(
                transaction=transaction,
                match_id=match_id,
                defender_url=defender_url,
                error_label="Defender Error",
                error_type="invalid_response",
                message="Defender response transaction_id did not match the request.",
                reason_prefix="Defender Error",
            )

        return decision

    def _fallback_approval(
        self,
        *,
        transaction: Transaction,
        match_id: str | None,
        defender_url: str,
        error_label: Literal["Defender Error", "Timeout", "Parse Error"],
        error_type: Literal[
            "timeout",
            "http_error",
            "transport_error",
            "parse_error",
            "invalid_response",
        ],
        message: str,
        reason_prefix: str,
    ) -> DefenderDecision:
        event = DispatchErrorEvent(
            match_id=match_id,
            transaction_id=transaction.id,
            defender_url=defender_url,
            error_label=error_label,
            error_type=error_type,
            message=message,
            counts_as_missed_fraud=transaction.is_fraud,
            referee_outcome="false_negative" if transaction.is_fraud else "true_negative",
            created_at=_timestamp(),
        )
        self.error_events.append(event)
        self._error_store.append(event)
        return DefenderDecision(
            transaction_id=transaction.id,
            decision="APPROVE",
            confidence=0.0,
            reason=f"{reason_prefix}: {message}",
        )


def get_defender_errors(match_id: str) -> list[DispatchErrorEvent]:
    return _ERROR_STORE.list(match_id)


def clear_defender_errors(match_id: str) -> None:
    _ERROR_STORE.clear(match_id)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
