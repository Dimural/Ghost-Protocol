"""
Ghost Protocol — Shared Gemini REST client

Uses the current Gemini REST API directly so the backend is not coupled to the
deprecated google-generativeai SDK. Responses are requested in JSON mode to
avoid brittle prompt-only parsing.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.config import GEMINI_API_BASE_URL, GEMINI_API_KEY


class GeminiAPIError(RuntimeError):
    """Raised when the Gemini API rejects a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeminiQuotaExceededError(GeminiAPIError):
    """Raised when Gemini rejects requests because the project quota is exhausted."""


def summarize_exception(exc: Exception, *, limit: int = 220) -> str:
    """Return a compact single-line error summary safe for UI/status messages."""
    summary = " ".join(str(exc).split()).strip() or exc.__class__.__name__
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3].rstrip() + "..."


def is_quota_exhausted_error(exc: Exception) -> bool:
    if isinstance(exc, GeminiQuotaExceededError):
        return True
    if isinstance(exc, GeminiAPIError) and exc.status_code == 429:
        return "RESOURCE_EXHAUSTED" in str(exc).upper()
    return False


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str | None = GEMINI_API_KEY,
        base_url: str = GEMINI_API_BASE_URL,
        timeout_seconds: float = 25.0,
        quota_cooldown_minutes: int = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._quota_cooldown_minutes = max(1, quota_cooldown_minutes)
        self._transport = transport
        self._quota_exhausted_until: datetime | None = None

    async def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        if not self._api_key:
            raise RuntimeError("Gemini API key is missing; cannot run Gemini request.")
        if self.quota_cooldown_active():
            raise GeminiQuotaExceededError(
                "Gemini quota is currently exhausted; continuing in local fallback mode.",
                status_code=429,
            )

        request_payload = self._build_request_payload(
            prompt=prompt,
            system_prompt=system_prompt,
            response_schema=response_schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        timeout = httpx.Timeout(self._timeout_seconds, connect=min(5.0, self._timeout_seconds))
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = await client.post(
                f"{self._base_url}/models/{model}:generateContent",
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )

        if response.is_error:
            raise self._build_api_error(model, response)

        payload = response.json()
        raw_text = self._extract_text(payload)
        if not raw_text:
            finish_reason = self._first_candidate_finish_reason(payload)
            block_reason = self._prompt_block_reason(payload)
            details = []
            if finish_reason:
                details.append(f"finish_reason={finish_reason}")
            if block_reason:
                details.append(f"block_reason={block_reason}")
            suffix = f" ({', '.join(details)})" if details else ""
            raise ValueError(f"Gemini returned no text output for model '{model}'{suffix}.")

        cleaned = self._strip_markdown_fences(raw_text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            preview = cleaned[:200].replace("\n", " ")
            raise ValueError(
                f"Gemini returned invalid JSON for model '{model}': {preview}"
            ) from exc

    def _build_request_payload(
        self,
        *,
        prompt: str,
        system_prompt: str | None,
        response_schema: dict[str, Any] | None,
        temperature: float | None,
        max_output_tokens: int | None,
    ) -> dict[str, Any]:
        parts = []
        if system_prompt and system_prompt.strip():
            parts.append({"text": system_prompt.strip()})
        parts.append({"text": prompt.strip()})

        generation_config: dict[str, Any] = {
            "responseMimeType": "application/json",
        }
        if response_schema is not None:
            generation_config["responseJsonSchema"] = response_schema
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens

        return {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": generation_config,
        }

    def current_runtime_mode(self) -> str:
        if not self._api_key or self.quota_cooldown_active():
            return "mock"
        return "gemini"

    def quota_cooldown_active(self) -> bool:
        if self._quota_exhausted_until is None:
            return False
        return datetime.now(timezone.utc) < self._quota_exhausted_until

    def _build_api_error(self, model: str, response: httpx.Response) -> GeminiAPIError:
        message = f"Gemini API rejected model '{model}' with HTTP {response.status_code}."
        try:
            payload = response.json()
        except ValueError:
            detail = response.text.strip()
            if detail:
                message = f"{message} {detail}"
            return GeminiAPIError(message, status_code=response.status_code)

        error_payload = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error_payload, dict):
            status = error_payload.get("status")
            detail = error_payload.get("message")
            if response.status_code == 429 and status == "RESOURCE_EXHAUSTED":
                self._quota_exhausted_until = datetime.now(timezone.utc) + timedelta(
                    minutes=self._quota_cooldown_minutes
                )
                quota_message = (
                    "Gemini quota is exhausted; switching to local fallback mode "
                    f"for about {self._quota_cooldown_minutes} minutes."
                )
                if detail:
                    quota_message = f"{quota_message} Google response: {detail}"
                return GeminiQuotaExceededError(quota_message, status_code=response.status_code)
            if status and detail:
                message = (
                    f"Gemini API rejected model '{model}' with HTTP {response.status_code} "
                    f"({status}): {detail}"
                )
            elif detail:
                message = (
                    f"Gemini API rejected model '{model}' with HTTP {response.status_code}: "
                    f"{detail}"
                )

        return GeminiAPIError(message, status_code=response.status_code)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            return ""

        chunks: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)

        return "\n".join(chunks).strip()

    def _first_candidate_finish_reason(self, payload: dict[str, Any]) -> str | None:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            return None
        finish_reason = candidate.get("finishReason")
        return finish_reason if isinstance(finish_reason, str) else None

    def _prompt_block_reason(self, payload: dict[str, Any]) -> str | None:
        feedback = payload.get("promptFeedback")
        if not isinstance(feedback, dict):
            return None
        block_reason = feedback.get("blockReason")
        return block_reason if isinstance(block_reason, str) else None

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


GEMINI_CLIENT = GeminiClient()
