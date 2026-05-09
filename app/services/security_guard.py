from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.core.errors import AppError

MAX_PREMIUM_ACTIVE_DEVICES = 2


def normalize_device_id(device_id: str | None) -> str | None:
    value = (device_id or "").strip()
    if not value or len(value) < 18:
        return None
    return value[:160]


def device_hash(device_id: str | None) -> str | None:
    normalized = normalize_device_id(device_id)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def require_device_hash(device_id: str | None) -> str:
    hashed = device_hash(device_id)
    if not hashed:
        raise AppError(
            error_code="DEVICE_ID_REQUIRED",
            user_message="Cihaz güvenlik bilgisi okunamadı. Lütfen uygulamayı güncelle ve tekrar dene.",
            developer_message="Missing or invalid X-Device-Install-Id",
            status_code=403,
        )
    return hashed


def premium_device_allowed(subscription_data: dict[str, Any] | None, device_id: str | None) -> tuple[bool, dict[str, Any]]:
    hashed = device_hash(device_id)
    if not hashed:
        return False, {}
    data = subscription_data or {}
    devices = data.get("active_devices") if isinstance(data.get("active_devices"), dict) else {}
    now = datetime.now(UTC).isoformat()
    if hashed in devices:
        devices[hashed] = {**(devices.get(hashed) or {}), "last_seen_at": now}
        return True, devices
    if len(devices) >= MAX_PREMIUM_ACTIVE_DEVICES:
        return False, devices
    devices[hashed] = {"first_seen_at": now, "last_seen_at": now}
    return True, devices
