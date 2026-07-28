from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings
from app.core.errors import AppError


@dataclass(frozen=True)
class VerifiedRewardCallback:
    ad_network: str
    ad_unit: str
    custom_data: str
    key_id: int
    reward_amount: int
    reward_item: str
    timestamp_ms: int
    transaction_id: str
    user_id: str


_key_cache: tuple[float, dict[int, str]] | None = None
_key_lock = asyncio.Lock()


def split_signed_query(raw_query: str) -> tuple[bytes, str, int]:
    """Return the exact signed query bytes, signature and key id.

    AdMob signs every query parameter before ``signature``. The original byte
    order and escaping must be preserved; parsing and rebuilding the query
    before verification would invalidate the signature.
    """
    signature_marker = "&signature="
    key_marker = "&key_id="
    signature_index = raw_query.rfind(signature_marker)
    if signature_index <= 0:
        raise AppError(
            error_code="ADMOB_SSV_SIGNATURE_MISSING",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="signature query parameter missing",
            status_code=400,
        )
    key_index = raw_query.find(key_marker, signature_index + len(signature_marker))
    if key_index <= signature_index:
        raise AppError(
            error_code="ADMOB_SSV_KEY_ID_MISSING",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="key_id query parameter missing",
            status_code=400,
        )

    signed_content = raw_query[:signature_index].encode("utf-8")
    signature = unquote(raw_query[signature_index + len(signature_marker) : key_index]).strip()
    key_text = unquote(raw_query[key_index + len(key_marker) :]).split("&", 1)[0].strip()
    try:
        key_id = int(key_text)
    except ValueError as exc:
        raise AppError(
            error_code="ADMOB_SSV_KEY_ID_INVALID",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=f"key_id={key_text!r}",
            status_code=400,
        ) from exc
    if not signature:
        raise AppError(
            error_code="ADMOB_SSV_SIGNATURE_EMPTY",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="signature is empty",
            status_code=400,
        )
    return signed_content, signature, key_id


def _decode_urlsafe_signature(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise AppError(
            error_code="ADMOB_SSV_SIGNATURE_INVALID",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="signature is not valid URL-safe base64",
            status_code=400,
        ) from exc


async def _fetch_verifier_keys() -> dict[int, str]:
    global _key_cache
    now = time.time()
    if _key_cache and now - _key_cache[0] < settings.admob_ssv_max_age_seconds:
        return _key_cache[1]

    async with _key_lock:
        now = time.time()
        if _key_cache and now - _key_cache[0] < settings.admob_ssv_max_age_seconds:
            return _key_cache[1]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(settings.admob_ssv_keys_url)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            if _key_cache:
                return _key_cache[1]
            raise AppError(
                error_code="ADMOB_SSV_KEYS_UNAVAILABLE",
                user_message="Reklam ödülü doğrulama servisine ulaşılamadı. Biraz sonra tekrar dene.",
                developer_message=str(exc),
                status_code=503,
                retryable=True,
            ) from exc

        parsed: dict[int, str] = {}
        for item in body.get("keys", []) if isinstance(body, dict) else []:
            if not isinstance(item, dict):
                continue
            try:
                parsed[int(item["keyId"])] = str(item["pem"])
            except (KeyError, TypeError, ValueError):
                continue
        if not parsed:
            raise AppError(
                error_code="ADMOB_SSV_KEYS_EMPTY",
                user_message="Reklam ödülü doğrulama servisi hazır değil.",
                developer_message="AdMob verifier key response did not contain usable keys",
                status_code=503,
                retryable=True,
            )
        _key_cache = (now, parsed)
        return parsed


def _single(params: dict[str, list[str]], key: str, *, required: bool = True) -> str:
    values = params.get(key) or []
    value = values[0].strip() if values else ""
    if required and not value:
        raise AppError(
            error_code="ADMOB_SSV_PARAMETER_MISSING",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=f"missing parameter: {key}",
            status_code=400,
        )
    return value


async def verify_reward_callback(raw_query: str) -> VerifiedRewardCallback:
    signed_content, signature_text, key_id = split_signed_query(raw_query)
    keys = await _fetch_verifier_keys()
    pem = keys.get(key_id)
    if pem is None:
        # Refresh once in case Google rotated keys after our cache was populated.
        global _key_cache
        _key_cache = None
        keys = await _fetch_verifier_keys()
        pem = keys.get(key_id)
    if pem is None:
        raise AppError(
            error_code="ADMOB_SSV_KEY_UNKNOWN",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=f"unknown key_id={key_id}",
            status_code=400,
        )

    try:
        public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
        public_key.verify(
            _decode_urlsafe_signature(signature_text),
            signed_content,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise AppError(
            error_code="ADMOB_SSV_SIGNATURE_MISMATCH",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="ECDSA signature verification failed",
            status_code=400,
        ) from exc
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            error_code="ADMOB_SSV_VERIFICATION_FAILED",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=str(exc),
            status_code=400,
        ) from exc

    params = parse_qs(raw_query, keep_blank_values=True)
    try:
        reward_amount = int(_single(params, "reward_amount"))
        timestamp_ms = int(_single(params, "timestamp"))
    except ValueError as exc:
        raise AppError(
            error_code="ADMOB_SSV_PARAMETER_INVALID",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message="reward_amount or timestamp is not an integer",
            status_code=400,
        ) from exc

    now_ms = int(time.time() * 1000)
    age_ms = now_ms - timestamp_ms
    if age_ms < -5 * 60 * 1000 or age_ms > settings.admob_ssv_max_age_seconds * 1000:
        raise AppError(
            error_code="ADMOB_SSV_CALLBACK_EXPIRED",
            user_message="Reklam ödülü doğrulama süresi doldu.",
            developer_message=f"callback_age_ms={age_ms}",
            status_code=400,
        )

    callback = VerifiedRewardCallback(
        ad_network=_single(params, "ad_network", required=False),
        ad_unit=_single(params, "ad_unit"),
        custom_data=_single(params, "custom_data"),
        key_id=key_id,
        reward_amount=reward_amount,
        reward_item=_single(params, "reward_item", required=False),
        timestamp_ms=timestamp_ms,
        transaction_id=_single(params, "transaction_id"),
        user_id=_single(params, "user_id"),
    )
    expected_unit = settings.admob_rewarded_ad_unit_id.strip()
    if expected_unit and callback.ad_unit != expected_unit:
        raise AppError(
            error_code="ADMOB_SSV_AD_UNIT_MISMATCH",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=f"ad_unit={callback.ad_unit} expected={expected_unit}",
            status_code=400,
        )
    if callback.reward_amount != settings.admob_reward_amount:
        raise AppError(
            error_code="ADMOB_SSV_REWARD_MISMATCH",
            user_message="Reklam ödülü doğrulanamadı.",
            developer_message=f"reward_amount={callback.reward_amount}",
            status_code=400,
        )
    return callback
