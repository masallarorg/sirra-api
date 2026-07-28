from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

_OPENAI_CLIENT: httpx.AsyncClient | None = None
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _get_client() -> httpx.AsyncClient:
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is None or _OPENAI_CLIENT.is_closed:
        _OPENAI_CLIENT = httpx.AsyncClient(
            base_url=settings.openai_api_base.rstrip("/"),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            timeout=httpx.Timeout(settings.openai_request_timeout_seconds, connect=10.0),
        )
    return _OPENAI_CLIENT


async def close_openai_client() -> None:
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is not None and not _OPENAI_CLIENT.is_closed:
        await _OPENAI_CLIENT.aclose()
    _OPENAI_CLIENT = None


def ensure_openai_configured(*, user_message: str, developer_message: str = "OPENAI_API_KEY is not configured") -> None:
    if not settings.openai_api_key:
        raise AppError(
            error_code="OPENAI_API_KEY_MISSING",
            user_message=user_message,
            developer_message=developer_message,
            status_code=503,
            retryable=True,
        )


def _error_body(response: httpx.Response) -> str:
    body = response.text[:1800]
    key = settings.openai_api_key or ""
    if key:
        body = body.replace(key, "[REDACTED_OPENAI_KEY]")
    return f"OpenAI status={response.status_code} body={body}"


def add_default_openai_options(payload: dict[str, Any]) -> dict[str, Any]:
    final_payload = dict(payload)
    if settings.openai_reasoning_effort and str(final_payload.get("model", "")).startswith("gpt-5"):
        final_payload.setdefault("reasoning", {"effort": settings.openai_reasoning_effort})
    if settings.openai_max_output_tokens > 0:
        final_payload.setdefault("max_output_tokens", settings.openai_max_output_tokens)
    return final_payload


async def call_openai_responses(
    payload: dict[str, Any],
    *,
    error_code: str,
    user_message: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    ensure_openai_configured(user_message=user_message)
    request_payload = add_default_openai_options(payload)
    client = _get_client()
    retries = max(settings.openai_retries, 0)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.post(
                "/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
                timeout=timeout_seconds or settings.openai_request_timeout_seconds,
            )
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= retries:
                raise AppError(
                    error_code=f"{error_code}_NETWORK",
                    user_message=user_message,
                    developer_message=str(exc),
                    status_code=503,
                    retryable=True,
                ) from exc
            await asyncio.sleep(min(2.0, 0.35 * (2**attempt)) + random.random() * 0.15)
            continue

        if response.status_code < 400:
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise AppError(
                    error_code=f"{error_code}_BAD_JSON",
                    user_message=user_message,
                    developer_message=f"OpenAI returned non-JSON response: {response.text[:1200]}",
                    status_code=502,
                    retryable=True,
                ) from exc

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < retries:
            retry_after = response.headers.get("retry-after")
            try:
                wait = min(float(retry_after), 3.0) if retry_after else min(2.0, 0.4 * (2**attempt))
            except ValueError:
                wait = min(2.0, 0.4 * (2**attempt))
            await asyncio.sleep(wait + random.random() * 0.2)
            continue

        raise AppError(
            error_code=f"{error_code}_RESPONSE",
            user_message=user_message,
            developer_message=_error_body(response),
            status_code=502 if response.status_code >= 500 else 400,
            retryable=response.status_code in _RETRYABLE_STATUS_CODES,
        )

    raise AppError(
        error_code=f"{error_code}_NETWORK",
        user_message=user_message,
        developer_message=str(last_exc or "OpenAI request failed"),
        status_code=503,
        retryable=True,
    )


def extract_output_text(response_json: dict[str, Any], *, empty_error_code: str = "OPENAI_OUTPUT_EMPTY", user_message: str = "AI çıktısı boş geldi. Lütfen tekrar dene.") -> str:
    if isinstance(response_json.get("output_text"), str) and response_json["output_text"].strip():
        return response_json["output_text"].strip()

    texts: list[str] = []
    for item in response_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    if texts:
        return "\n".join(texts)
    raise AppError(
        error_code=empty_error_code,
        user_message=user_message,
        developer_message=json.dumps(response_json, ensure_ascii=False)[:1200],
        status_code=502,
        retryable=True,
    )


def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}}


def image_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    import base64

    return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
