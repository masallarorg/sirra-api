from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.schemas.astrology import DailyHoroscope

# Process-level fallback cache. This prevents repeat OpenAI calls during local
# development when Firestore Admin is not available, but production should use
# Firestore through FIREBASE_CREDENTIALS_PATH.
_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


def horoscope_cache_key(sign: str, locale: str, target_date: str | None = None) -> str:
    safe_locale = locale.lower().replace("-", "_").replace(" ", "_")
    safe_sign = sign.lower().replace(" ", "_")
    return f"{target_date or date.today().isoformat()}_{safe_sign}_{safe_locale}"


def _firestore_client():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except Exception as exc:
        if settings.allow_mock_auth or settings.mock_ai:
            return None
        raise AppError(
            error_code="FIREBASE_ADMIN_PACKAGE_MISSING",
            user_message="Burç cache servisi hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    try:
        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                cred = credentials.Certificate(settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception as exc:
        if settings.allow_mock_auth or settings.mock_ai:
            return None
        raise AppError(
            error_code="FIREBASE_ADMIN_NOT_CONFIGURED",
            user_message="Burç cache servisi hazır değil. Lütfen daha sonra tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc


async def get_cached_daily_horoscope(*, sign: str, locale: str, target_date: str | None = None) -> DailyHoroscope | None:
    key = horoscope_cache_key(sign=sign, locale=locale, target_date=target_date)

    if key in _MEMORY_CACHE:
        data = dict(_MEMORY_CACHE[key])
        data["cached"] = True
        data["generated_by"] = data.get("generated_by") or "memory_cache"
        return DailyHoroscope.model_validate(data)

    if settings.mock_ai or settings.allow_mock_auth:
        return None

    db = _firestore_client()
    if db is None:
        return None

    snapshot = db.collection("daily_horoscopes").document(key).get()
    if not snapshot.exists:
        return None

    data = snapshot.to_dict() or {}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    payload = dict(payload)
    payload["cached"] = True
    payload["generated_by"] = payload.get("generated_by") or "firestore_cache"
    return DailyHoroscope.model_validate(payload)


async def save_daily_horoscope_cache(*, horoscope: DailyHoroscope, locale: str) -> None:
    key = horoscope_cache_key(sign=horoscope.sign, locale=locale, target_date=horoscope.date)
    payload = horoscope.model_dump()
    payload["cached"] = False

    _MEMORY_CACHE[key] = payload

    if settings.mock_ai or settings.allow_mock_auth:
        return

    db = _firestore_client()
    if db is None:
        return

    now = datetime.now(UTC)
    expires_at = now + timedelta(days=2)
    db.collection("daily_horoscopes").document(key).set(
        {
            "cache_key": key,
            "date": horoscope.date,
            "sign": horoscope.sign,
            "locale": locale,
            "payload": payload,
            "created_at": now,
            "expires_at": expires_at,
            "source": horoscope.generated_by,
        },
        merge=True,
    )
