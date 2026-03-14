"""
Ghost Protocol — Defender Webhook Dispatcher

Sends defender-safe transaction payloads to user webhooks and normalizes the
response into DefenderDecision objects. Timeouts and upstream errors fall back
to APPROVE so the match can continue without crashing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable, Literal, Sequence

import httpx
from pydantic import BaseModel, ValidationError

from backend.data.models import DefenderDecision, Transaction


class DispatchErrorEvent(BaseModel):
    transaction_id: str
    defender_url: str
    error_type: Literal[
        "timeout",
        "http_error",
        "transport_error",
        "parse_error",
        "invalid_response",
    ]
    message: str
    created_at: str


class WebhookDispatcher:
    """Dispatch transactions to a defender webhook without leaking ground truth."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        history_resolver: Callable[[Transaction], Sequence[Transaction]] | None = None,
    ) -> None:
        self._transport = transport
        self._history_resolver = history_resolver
        self.error_events: list[DispatchErrorEvent] = []

    async def dispatch(
        self,
        transaction: Transaction,
        defender_url: str,
        timeout_seconds: int = 5,
    ) -> DefenderDecision:
        payload = self._build_payload(transaction)

        try:
            response = await self._post_json(defender_url, payload, timeout_seconds)
            response.raise_for_status()
        except httpx.TimeoutException:
            return self._fallback_approval(
                transaction_id=transaction.id,
                defender_url=defender_url,
                error_type="timeout",
                message=f"Defender timed out after {timeout_seconds} seconds.",
                reason_prefix="Timeout",
            )
        except httpx.HTTPStatusError as exc:
            return self._fallback_approval(
                transaction_id=transaction.id,
                defender_url=defender_url,
                error_type="http_error",
                message=f"Defender returned HTTP {exc.response.status_code}.",
                reason_prefix="Defender Error",
            )
        except httpx.HTTPError as exc:
            return self._fallback_approval(
                transaction_id=transaction.id,
                defender_url=defender_url,
                error_type="transport_error",
                message=f"Unable to reach defender: {exc.__class__.__name__}.",
                reason_prefix="Defender Error",
            )

        return self._parse_response(transaction.id, defender_url, response)

    async def dispatch_batch(
        self,
        transactions: list[Transaction],
        defender_url: str,
        timeout_seconds: int = 5,
    ) -> list[DefenderDecision]:
        return await asyncio.gather(
            *[
                self.dispatch(
                    transaction=transaction,
                    defender_url=defender_url,
                    timeout_seconds=timeout_seconds,
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
        transaction_id: str,
        defender_url: str,
        response: httpx.Response,
    ) -> DefenderDecision:
        try:
            payload = response.json()
        except ValueError:
            return self._fallback_approval(
                transaction_id=transaction_id,
                defender_url=defender_url,
                error_type="parse_error",
                message="Defender returned malformed JSON.",
                reason_prefix="Parse Error",
            )

        if not isinstance(payload, dict):
            return self._fallback_approval(
                transaction_id=transaction_id,
                defender_url=defender_url,
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
                transaction_id=transaction_id,
                defender_url=defender_url,
                error_type="invalid_response",
                message="Defender response did not match DefenderDecision schema.",
                reason_prefix="Defender Error",
            )

        if decision.transaction_id != transaction_id:
            return self._fallback_approval(
                transaction_id=transaction_id,
                defender_url=defender_url,
                error_type="invalid_response",
                message="Defender response transaction_id did not match the request.",
                reason_prefix="Defender Error",
            )

        return decision

    def _fallback_approval(
        self,
        *,
        transaction_id: str,
        defender_url: str,
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
        self.error_events.append(
            DispatchErrorEvent(
                transaction_id=transaction_id,
                defender_url=defender_url,
                error_type=error_type,
                message=message,
                created_at=_timestamp(),
            )
        )
        return DefenderDecision(
            transaction_id=transaction_id,
            decision="APPROVE",
            confidence=0.0,
            reason=f"{reason_prefix}: {message}",
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
