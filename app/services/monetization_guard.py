from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.services.security_guard import premium_device_allowed

FORTUNE_COSTS: dict[str, int] = {
    "coffee": 5,
    "tarot": 2,
    "dream": 2,
    "love": 3,
    "katina": 3,
    "palm": 6,
    "birthchart": 6,
    "numerology": 1,
    "oracle": 1,
    "soulmate": 6,
}

PREMIUM_DAILY_LIMIT = 5
WELCOME_CREDITS = 7


@dataclass(frozen=True)
class FortuneReservation:
    user_id: str
    fortune_type: str
    kind: str
    cost: int = 0
    date_key: str = ""
    access_state: dict[str, Any] | None = None


def fortune_cost(fortune_type: str) -> int:
    return FORTUNE_COSTS.get(fortune_type, 2)


def _today_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        if settings.firebase_credentials_path:
            firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def _is_subscription_active(data: dict[str, Any] | None) -> bool:
    data = data or {}
    if bool(data.get("active")) or data.get("entitlement") == "premium":
        expires_at = str(data.get("expires_at") or "").strip()
        if not expires_at:
            return True
        if expires_at.isdigit():
            try:
                return datetime.fromtimestamp(int(expires_at) / 1000, tz=UTC) > datetime.now(UTC)
            except Exception:
                return True
        try:
            parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return parsed > datetime.now(UTC)
        except Exception:
            return True
    return False


async def reserve_fortune_access(*, user_id: str, fortune_type: str, device_id: str | None = None) -> FortuneReservation:
    """Atomically reserve a fortune right before an AI call.

    This is the only secure place where credits are spent. The mobile app may
    preview a cost, but the backend makes the final decision and returns the
    new server balance in ``reservation.access_state``.
    """
    if settings.mock_ai and settings.allow_mock_auth:
        return FortuneReservation(
            user_id=user_id,
            fortune_type=fortune_type,
            kind="mock",
            cost=0,
            date_key=_today_key(),
            access_state={
                "credits": 0,
                "charged_credits": 0,
                "access_kind": "mock",
                "premium_daily_used": 0,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": PREMIUM_DAILY_LIMIT,
                "standard_free_daily_used": 0,
                "daily_date": _today_key(),
                "is_premium": False,
            },
        )

    try:
        db = _firestore_client()
        from firebase_admin import firestore
    except Exception as exc:
        raise AppError(
            error_code="MONETIZATION_NOT_READY",
            user_message="Fal hakkın kontrol edilemedi. Lütfen birazdan tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    today = _today_key()
    cost = fortune_cost(fortune_type)
    sub_ref = db.collection("subscriptions").document(user_id)
    user_ref = db.collection("users").document(user_id)
    access_ref = db.collection("monetization").document(user_id)

    transaction = db.transaction()

    @firestore.transactional
    def _reserve(transaction):
        sub_snap = sub_ref.get(transaction=transaction)
        user_snap = user_ref.get(transaction=transaction)
        access_snap = access_ref.get(transaction=transaction)

        sub = sub_snap.to_dict() if sub_snap.exists else None
        user = user_snap.to_dict() if user_snap.exists else None
        # Güvenlik: premium yetkisi sadece subscriptions koleksiyonundan gelir.
        # users.is_premium sadece UI yansımasıdır; kullanıcı tarafından yazılabilir kabul edilmemelidir.
        active_premium = _is_subscription_active(sub)
        premium_device_ok = True
        active_devices_patch = None
        if active_premium:
            premium_device_ok, active_devices_patch = premium_device_allowed(sub, device_id)
            active_premium = active_premium and premium_device_ok

        data = access_snap.to_dict() if access_snap.exists else {}
        user_data = user or {}
        if not data:
            data = {"credits": WELCOME_CREDITS, "welcome_credits_granted": True}
        monetization_credits = int(data.get("credits") or 0)
        user_credits = int(user_data.get("credits") or 0)
        # Credits were historically mirrored in both monetization/{uid} and users/{uid}.
        # The backend must never charge from a stale lower document, otherwise login/logout
        # can appear to erase rewarded-ad credits. Use the highest known balance before spending
        # and mirror the result back to both documents.
        credits = max(monetization_credits, user_credits)
        daily_date = str(data.get("daily_date") or user_data.get("daily_date") or "")
        premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0), int(user_data.get("premium_used") or 0), int(user_data.get("premium_daily_used") or 0))
        free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0), int(user_data.get("free_used") or 0), int(user_data.get("standard_free_daily_used") or 0))
        if daily_date != today:
            premium_used = 0
            free_used = 0

        now = datetime.now(UTC)
        base_patch = {
            "welcome_credits_granted": True,
            "daily_date": today,
            "updated_at": now,
            "credits_updated_at": now,
            "last_fortune_type": fortune_type,
        }

        def state(*, access_kind: str, charged_credits: int, credits_after: int, premium_after: int, free_after: int) -> dict[str, Any]:
            return {
                "credits": credits_after,
                "charged_credits": charged_credits,
                "access_kind": access_kind,
                "premium_daily_used": premium_after,
                "premium_used": premium_after,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": max(0, PREMIUM_DAILY_LIMIT - premium_after),
                "standard_free_daily_used": free_after,
                "free_used": free_after,
                "daily_date": today,
                "is_premium": bool(active_premium),
            }

        if active_premium and premium_used < PREMIUM_DAILY_LIMIT:
            premium_after = premium_used + 1
            patch = {**base_patch, "credits": credits, "premium_used": premium_after, "premium_daily_used": premium_after, "free_used": free_used, "standard_free_daily_used": free_used}
            transaction.set(access_ref, patch, merge=True)
            transaction.set(user_ref, {"credits": credits, "credits_updated_at": now, "updated_at": now}, merge=True)
            if active_devices_patch is not None:
                transaction.set(sub_ref, {"active_devices": active_devices_patch, "updated_at": now}, merge=True)
            access_state = state(access_kind="premium_daily", charged_credits=0, credits_after=credits, premium_after=premium_after, free_after=free_used)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="premium_daily", cost=0, date_key=today, access_state=access_state)

        if not active_premium and fortune_type == "oracle" and free_used < 1:
            free_after = free_used + 1
            patch = {**base_patch, "credits": credits, "premium_used": premium_used, "premium_daily_used": premium_used, "free_used": free_after, "standard_free_daily_used": free_after}
            transaction.set(access_ref, patch, merge=True)
            transaction.set(user_ref, {"credits": credits, "credits_updated_at": now, "updated_at": now}, merge=True)
            access_state = state(access_kind="standard_free", charged_credits=0, credits_after=credits, premium_after=premium_used, free_after=free_after)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="standard_free", cost=0, date_key=today, access_state=access_state)

        if credits >= cost:
            credits_after = credits - cost
            patch = {**base_patch, "credits": credits_after, "premium_used": premium_used, "premium_daily_used": premium_used, "free_used": free_used, "standard_free_daily_used": free_used, "last_charged_credits": cost}
            transaction.set(access_ref, patch, merge=True)
            transaction.set(user_ref, {"credits": credits_after, "credits_updated_at": now, "updated_at": now}, merge=True)
            access_state = state(access_kind="credits", charged_credits=cost, credits_after=credits_after, premium_after=premium_used, free_after=free_used)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="credits", cost=cost, date_key=today, access_state=access_state)

        raise AppError(
            error_code="FORTUNE_CREDITS_REQUIRED",
            user_message=("Premium hesabın başka cihazlarda aktif olduğu için bu cihazda günlük premium hakkı kullanılamadı. " if (not active_premium and premium_device_ok is False) else "") + f"Bu fal için {cost} kredi gerekir. Premiuma geçebilir veya kredi paketiyle devam edebilirsin.",
            developer_message=f"uid={user_id} type={fortune_type} credits={credits} cost={cost}",
            status_code=402,
        )

    return _reserve(transaction)


async def refund_fortune_access(reservation: FortuneReservation) -> None:
    if reservation.kind in {"mock", "none"} or (settings.mock_ai and settings.allow_mock_auth):
        return
    try:
        db = _firestore_client()
        ref = db.collection("monetization").document(reservation.user_id)
        user_ref = db.collection("users").document(reservation.user_id)
        snap = ref.get()
        user_snap = user_ref.get()
        data = snap.to_dict() if snap.exists else {}
        user_data = user_snap.to_dict() if user_snap.exists else {}
        credits = max(int(data.get("credits") or 0), int(user_data.get("credits") or 0))
        premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0), int(user_data.get("premium_used") or 0), int(user_data.get("premium_daily_used") or 0))
        free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0), int(user_data.get("free_used") or 0), int(user_data.get("standard_free_daily_used") or 0))
        now = datetime.now(UTC)
        patch: dict[str, Any] = {"updated_at": now}
        if reservation.kind == "credits":
            patch["credits"] = credits + reservation.cost
            patch["credits_updated_at"] = now
        elif reservation.kind == "premium_daily":
            patch["premium_used"] = max(0, premium_used - 1)
            patch["premium_daily_used"] = patch["premium_used"]
        elif reservation.kind == "standard_free":
            patch["free_used"] = max(0, free_used - 1)
            patch["standard_free_daily_used"] = patch["free_used"]
        ref.set(patch, merge=True)
        if "credits" in patch:
            user_ref.set({"credits": patch["credits"], "credits_updated_at": now, "updated_at": now}, merge=True)
    except Exception:
        return
