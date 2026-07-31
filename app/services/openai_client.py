from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError

_OPENAI_CLIENT: httpx.AsyncClient | None = None
logger = logging.getLogger("uvicorn.error")
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

        error_detail = _error_body(response)
        logger.error("OpenAI request failed code=%s %s", error_code, error_detail)
        raise AppError(
            error_code=f"{error_code}_RESPONSE",
            user_message=user_message,
            developer_message=error_detail,
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



async def call_openai_image_edit(
    *,
    image_bytes: bytes,
    prompt: str,
    error_code: str,
    user_message: str,
    output_format: str = "jpeg",
    quality: str = "medium",
    size: str = "1024x1024",
    timeout_seconds: float = 120.0,
) -> tuple[str, str]:
    """Generate a new image from an uploaded reference image.

    GPT Image models return base64 image data by default. The raw user image is
    sent only for this request and is not written to the backend filesystem.
    """
    ensure_openai_configured(user_message=user_message)
    client = _get_client()
    retries = max(settings.openai_retries, 0)
    mime_type = "image/jpeg" if output_format == "jpeg" else f"image/{output_format}"
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            response = await client.post(
                "/images/edits",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data={
                    "model": settings.openai_image_model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "output_format": output_format,
                },
                files=[("image[]", ("selfie.jpg", image_bytes, "image/jpeg"))],
                timeout=timeout_seconds,
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
            await asyncio.sleep(min(2.0, 0.45 * (2**attempt)) + random.random() * 0.15)
            continue

        if response.status_code < 400:
            try:
                payload = response.json()
                image_data = ((payload.get("data") or [{}])[0] or {}).get("b64_json")
                if not isinstance(image_data, str) or not image_data.strip():
                    raise ValueError("Image response has no b64_json")
                return image_data.strip(), mime_type
            except (json.JSONDecodeError, ValueError, IndexError, TypeError) as exc:
                raise AppError(
                    error_code=f"{error_code}_BAD_RESPONSE",
                    user_message=user_message,
                    developer_message=f"{exc}: {response.text[:1200]}",
                    status_code=502,
                    retryable=True,
                ) from exc

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < retries:
            await asyncio.sleep(min(2.5, 0.5 * (2**attempt)) + random.random() * 0.2)
            continue

        error_detail = _error_body(response)
        logger.error("OpenAI request failed code=%s %s", error_code, error_detail)
        raise AppError(
            error_code=f"{error_code}_RESPONSE",
            user_message=user_message,
            developer_message=error_detail,
            status_code=502 if response.status_code >= 500 else 400,
            retryable=response.status_code in _RETRYABLE_STATUS_CODES,
        )

    raise AppError(
        error_code=f"{error_code}_NETWORK",
        user_message=user_message,
        developer_message=str(last_exc or "OpenAI image request failed"),
        status_code=503,
        retryable=True,
    )

async def call_openai_image_generate(
    *,
    prompt: str,
    error_code: str,
    user_message: str,
    output_format: str = "jpeg",
    quality: str = "medium",
    size: str = "1024x1024",
    timeout_seconds: float = 120.0,
) -> tuple[str, str]:
    """Generate a new image without copying an uploaded customer's face."""
    ensure_openai_configured(user_message=user_message)
    client = _get_client()
    retries = max(settings.openai_retries, 0)
    mime_type = "image/jpeg" if output_format == "jpeg" else f"image/{output_format}"
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            response = await client.post(
                "/images/generations",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_image_model,
                    "prompt": prompt,
                    "size": size,
                    "quality": quality,
                    "output_format": output_format,
                    "n": 1,
                },
                timeout=timeout_seconds,
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
            await asyncio.sleep(min(2.0, 0.45 * (2**attempt)) + random.random() * 0.15)
            continue

        if response.status_code < 400:
            try:
                payload = response.json()
                image_data = ((payload.get("data") or [{}])[0] or {}).get("b64_json")
                if not isinstance(image_data, str) or not image_data.strip():
                    raise ValueError("Image response has no b64_json")
                return image_data.strip(), mime_type
            except (json.JSONDecodeError, ValueError, IndexError, TypeError) as exc:
                raise AppError(
                    error_code=f"{error_code}_BAD_RESPONSE",
                    user_message=user_message,
                    developer_message=f"{exc}: {response.text[:1200]}",
                    status_code=502,
                    retryable=True,
                ) from exc

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < retries:
            await asyncio.sleep(min(2.5, 0.5 * (2**attempt)) + random.random() * 0.2)
            continue

        error_detail = _error_body(response)
        logger.error("OpenAI request failed code=%s %s", error_code, error_detail)
        raise AppError(
            error_code=f"{error_code}_RESPONSE",
            user_message=user_message,
            developer_message=error_detail,
            status_code=502 if response.status_code >= 500 else 400,
            retryable=response.status_code in _RETRYABLE_STATUS_CODES,
        )

    raise AppError(
        error_code=f"{error_code}_NETWORK",
        user_message=user_message,
        developer_message=str(last_exc or "OpenAI image request failed"),
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


def _strip_markdown_json_fence(text: str) -> str:
    clean = text.strip().lstrip("\ufeff")
    if not clean.startswith("```"):
        return clean
    lines = clean.splitlines()
    if lines and lines[0].strip().lower() in {"```", "```json", "```javascript", "```js"}:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _decode_json_object(text: str) -> dict[str, Any]:
    clean = _strip_markdown_json_fence(text)
    candidates = [clean]
    first_brace = clean.find("{")
    if first_brace > 0:
        candidates.append(clean[first_brace:])

    decoder = json.JSONDecoder()
    errors: list[str] = []
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, str):
                value = json.loads(_strip_markdown_json_fence(value))
            if isinstance(value, dict):
                return value
            errors.append(f"decoded_type={type(value).__name__}")
        except json.JSONDecodeError as exc:
            errors.append(str(exc))

        start = candidate.find("{")
        if start >= 0:
            try:
                value, _ = decoder.raw_decode(candidate[start:])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError as exc:
                errors.append(str(exc))

    raise ValueError("; ".join(errors[-3:]) or "No JSON object found")


def extract_output_json(
    response_json: dict[str, Any],
    *,
    empty_error_code: str = "OPENAI_OUTPUT_EMPTY",
    invalid_error_code: str = "OPENAI_OUTPUT_JSON_INVALID",
    user_message: str = "AI çıktısı beklenen biçimde gelmedi. Lütfen tekrar dene.",
) -> dict[str, Any]:
    parsed = response_json.get("output_parsed")
    if isinstance(parsed, dict):
        return parsed
    for item in response_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            for key in ("parsed", "json"):
                value = content.get(key)
                if isinstance(value, dict):
                    return value

    text = extract_output_text(response_json, empty_error_code=empty_error_code, user_message=user_message)
    try:
        return _decode_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise AppError(
            error_code=invalid_error_code,
            user_message=user_message,
            developer_message=f"{exc}: {text[:1200]}",
            status_code=502,
            retryable=True,
        ) from exc


def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}}


def image_data_url(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    import base64

    return f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
