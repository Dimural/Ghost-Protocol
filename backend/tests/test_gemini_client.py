"""Tests for Gemini quota handling and runtime mode fallback."""
from __future__ import annotations

import httpx
import pytest

from backend.gemini_client import GeminiClient, GeminiQuotaExceededError


@pytest.mark.asyncio
async def test_quota_exhaustion_enters_cooldown_without_repeating_network_calls():
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "You exceeded your current quota.",
                }
            },
        )

    client = GeminiClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        quota_cooldown_minutes=15,
    )

    with pytest.raises(GeminiQuotaExceededError, match="switching to local fallback mode"):
        await client.generate_json(model="gemini-2.5-flash", prompt="hello")

    with pytest.raises(GeminiQuotaExceededError, match="continuing in local fallback mode"):
        await client.generate_json(model="gemini-2.5-flash", prompt="hello again")

    assert call_count == 1
    assert client.current_runtime_mode() == "mock"
