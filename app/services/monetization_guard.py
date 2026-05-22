from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.services.security_guard import premium_device_allowed
from app.services.daily_access_clock import daily_access_key

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
    return daily_access_key()


def _firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        if settings.firebase_credentials_path:
            firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def _parse_expiry(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        raw = int(value)
        if raw <= 0:
            return None
        if raw > 100000000000:
            return datetime.fromtimestamp(raw / 1000, tz=UTC)
        return datetime.fromtimestamp(raw, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_expiry(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None


def _is_subscription_active(data: dict[str, Any] | None) -> bool:
    data = data or {}
    if bool(data.get("active")) or data.get("entitlement") == "premium" or bool(data.get("is_premium")):
        expires_at = _parse_expiry(data.get("expires_at") or data.get("premium_until") or data.get("premiumUntil"))
        if expires_at is None:
            return True
        return expires_at > datetime.now(UTC)
    return False


def _snapshot_update_time(snapshot: Any) -> datetime | None:
    value = getattr(snapshot, "update_time", None)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        # google.cloud.firestore_v1._helpers.TimestampWithNanoseconds exposes
        # timestamp()/ToDatetime()-like behavior depending on SDK version.
        if hasattr(value, "timestamp"):
            return datetime.fromtimestamp(value.timestamp(), tz=UTC)
        if hasattr(value, "ToDatetime"):
            parsed = value.ToDatetime()
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None
    return None


def _credit_version(data: dict[str, Any], snapshot: Any | None = None) -> datetime | None:
    # credits_updated_at is set by backend/client sync. Firestore update_time is
    # critical for Firebase Console edits where an admin only changes `credits`
    # and does not manually touch credits_updated_at.
    explicit = _parse_expiry(data.get("credits_updated_at") or data.get("updated_at"))
    return explicit or (_snapshot_update_time(snapshot) if snapshot is not None else None)


def _credit_candidate(data: dict[str, Any] | None, snapshot: Any | None = None) -> tuple[int, datetime | None] | None:
    data = data or {}
    if "credits" not in data:
        return None
    try:
        credits = int(data.get("credits") or 0)
    except Exception:
        return None
    return max(0, credits), _credit_version(data, snapshot)


def latest_credit_balance(
    monetization_data: dict[str, Any] | None,
    user_data: dict[str, Any] | None,
    *,
    monetization_snapshot: Any | None = None,
    user_snapshot: Any | None = None,
    default: int = WELCOME_CREDITS,
) -> int:
    """Pick the authoritative credit balance from mirrored Firestore docs.

    The old implementation used ``max(monetization.credits, users.credits)`` to
    protect rewarded-ad credits from stale lower mirrors. That made Firebase
    Console/admin decreases impossible: lowering 20 -> 5 was immediately ignored
    because the other mirror still had 20. We now choose the newest credit field
    by credits_updated_at/updated_at, and fall back to Firestore document
    update_time for manual console edits. If versions are equal or unknown, the
    higher value still wins as the safe fallback.
    """
    candidates = [
        item
        for item in (
            _credit_candidate(monetization_data, monetization_snapshot),
            _credit_candidate(user_data, user_snapshot),
        )
        if item is not None
    ]
    if not candidates:
        return max(0, int(default))
    if len(candidates) == 1:
        return candidates[0][0]

    dated = [item for item in candidates if item[1] is not None]
    if len(dated) == len(candidates):
        dated.sort(key=lambda item: item[1] or datetime.min.replace(tzinfo=UTC), reverse=True)
        newest_time = dated[0][1]
        newest = [item for item in dated if item[1] == newest_time]
        if len(newest) == 1:
            return newest[0][0]
        return max(item[0] for item in newest)

    # Missing versions mean we cannot prove which mirror is newer. Prefer the
    # larger balance so a stale mirror cannot accidentally erase paid/rewarded
    # credits; runtime admin decreases are handled by document update_time when
    # the backend reads Firestore snapshots.
    return max(item[0] for item in candidates)


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
                "premium_daily_exhausted": False,
                "standard_free_daily_used": 0,
                "free_used": 0,
                "daily_date": _today_key(),
                "is_premium": False,
                "user_message": None,
                "authoritative_daily_state": True,
                "daily_reset_applied": False,
                "daily_reset_timezone": "Europe/Istanbul",
                "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
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
        # Credits are mirrored in monetization/{uid} and users/{uid}. The
        # authoritative balance is the newest credit field, not the largest one:
        # otherwise Firebase Console/admin decreases are ignored forever.
        credits = latest_credit_balance(
            data,
            user_data,
            monetization_snapshot=access_snap,
            user_snapshot=user_snap,
            default=WELCOME_CREDITS,
        )
        daily_date = str(data.get("daily_date") or user_data.get("daily_date") or "")
        premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0), int(user_data.get("premium_used") or 0), int(user_data.get("premium_daily_used") or 0))
        free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0), int(user_data.get("free_used") or 0), int(user_data.get("standard_free_daily_used") or 0))
        daily_reset_applied = daily_date != today
        if daily_reset_applied:
            premium_used = 0
            free_used = 0

        now = datetime.now(UTC)
        base_patch = {
            "welcome_credits_granted": True,
            "daily_date": today,
            "updated_at": now,
            "credits_updated_at": now,
            "last_fortune_type": fortune_type,
            "daily_reset_applied": daily_reset_applied,
            "authoritative_daily_state": True,
        }

        def state(
            *,
            access_kind: str,
            charged_credits: int,
            credits_after: int,
            premium_after: int,
            free_after: int,
            user_message: str | None = None,
        ) -> dict[str, Any]:
            premium_remaining = max(0, PREMIUM_DAILY_LIMIT - premium_after)
            premium_exhausted = bool(active_premium and premium_remaining == 0)
            return {
                "credits": credits_after,
                "charged_credits": charged_credits,
                "access_kind": access_kind,
                "premium_daily_used": premium_after,
                "premium_used": premium_after,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": premium_remaining,
                "premium_daily_exhausted": premium_exhausted,
                "standard_free_daily_used": free_after,
                "free_used": free_after,
                "daily_date": today,
                "is_premium": bool(active_premium),
                "user_message": user_message,
                "authoritative_daily_state": True,
                "daily_reset_applied": daily_reset_applied,
                "daily_reset_timezone": "Europe/Istanbul",
                "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
            }

        if active_premium and premium_used < PREMIUM_DAILY_LIMIT:
            premium_after = premium_used + 1
            access_state = state(access_kind="premium_daily", charged_credits=0, credits_after=credits, premium_after=premium_after, free_after=free_used)
            patch = {
                **base_patch,
                "credits": credits,
                "premium_used": premium_after,
                "premium_daily_used": premium_after,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": access_state["premium_daily_remaining"],
                "premium_daily_exhausted": access_state["premium_daily_exhausted"],
                "free_used": free_used,
                "standard_free_daily_used": free_used,
                "last_access_kind": "premium_daily",
                "last_charged_credits": 0,
                "last_access_message": None,
            }
            transaction.set(access_ref, patch, merge=True)
            transaction.set(user_ref, {
                "credits": credits,
                "credits_updated_at": now,
                "daily_date": today,
                "premium_used": premium_after,
                "premium_daily_used": premium_after,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": access_state["premium_daily_remaining"],
                "premium_daily_exhausted": access_state["premium_daily_exhausted"],
                "last_access_kind": "premium_daily",
                "authoritative_daily_state": True,
                "daily_reset_applied": daily_reset_applied,
                "updated_at": now,
            }, merge=True)
            if active_devices_patch is not None:
                transaction.set(sub_ref, {"active_devices": active_devices_patch, "updated_at": now}, merge=True)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="premium_daily", cost=0, date_key=today, access_state=access_state)

        # Standart üyede ücretsiz günlük fal yoktur; standart kullanıcılar
        # her falı doğrudan kredi bakiyesinden kullanır.

        if credits >= cost:
            credits_after = credits - cost
            premium_credit_notice = (
                f"Bugünkü {PREMIUM_DAILY_LIMIT} premium fal hakkın bitti. Bu falda {cost} kredi kullanılıyor."
                if active_premium and premium_used >= PREMIUM_DAILY_LIMIT
                else None
            )
            access_state = state(
                access_kind="credits",
                charged_credits=cost,
                credits_after=credits_after,
                premium_after=premium_used,
                free_after=free_used,
                user_message=premium_credit_notice,
            )
            patch = {
                **base_patch,
                "credits": credits_after,
                "premium_used": premium_used,
                "premium_daily_used": premium_used,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": access_state["premium_daily_remaining"],
                "premium_daily_exhausted": access_state["premium_daily_exhausted"],
                "free_used": free_used,
                "standard_free_daily_used": free_used,
                "last_charged_credits": cost,
                "last_access_kind": "credits",
                "last_access_message": premium_credit_notice,
            }
            transaction.set(access_ref, patch, merge=True)
            transaction.set(user_ref, {
                "credits": credits_after,
                "credits_updated_at": now,
                "daily_date": today,
                "premium_used": premium_used,
                "premium_daily_used": premium_used,
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": access_state["premium_daily_remaining"],
                "premium_daily_exhausted": access_state["premium_daily_exhausted"],
                "last_access_kind": "credits",
                "authoritative_daily_state": True,
                "daily_reset_applied": daily_reset_applied,
                "updated_at": now,
            }, merge=True)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="credits", cost=cost, date_key=today, access_state=access_state)

        premium_exhausted_prefix = (
            f"Bugünkü {PREMIUM_DAILY_LIMIT} premium fal hakkın bitti ve bu fal için {cost} kredi gerekiyor. "
            if active_premium and premium_used >= PREMIUM_DAILY_LIMIT
            else ""
        )
        raise AppError(
            error_code="FORTUNE_CREDITS_REQUIRED",
            user_message=("Premium hesabın başka cihazlarda aktif olduğu için bu cihazda günlük premium hakkı kullanılamadı. " if (not active_premium and premium_device_ok is False) else premium_exhausted_prefix) + f"Bu fal için {cost} kredi gerekir. Premium hakkın yarın tekrar 5 olacak veya kredi paketiyle devam edebilirsin.",
            developer_message=f"uid={user_id} type={fortune_type} credits={credits} cost={cost}",
            status_code=402,
        )

    reservation = _reserve(transaction)
    _log_fortune_access_ledger(db, reservation=reservation, event_type="reserve")
    return reservation


def _log_fortune_access_ledger(db, *, reservation: FortuneReservation, event_type: str) -> None:
    try:
        access = reservation.access_state or {}
        charged = int(access.get("charged_credits") or reservation.cost or 0)
        if charged <= 0 and reservation.kind != "credits":
            return
        payload = {
            "uid": reservation.user_id,
            "fortune_type": reservation.fortune_type,
            "event_type": event_type,
            "access_kind": reservation.kind,
            "amount": charged if event_type == "reserve" else -charged,
            "balance_after": int(access.get("credits") or 0),
            "daily_date": reservation.date_key,
            "created_at": datetime.now(UTC),
            "reason": "fortune_credit_reserve" if event_type == "reserve" else "fortune_credit_refund",
        }
        db.collection("credit_ledger").add(payload)
    except Exception:
        return


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
        credits = latest_credit_balance(data, user_data, monetization_snapshot=snap, user_snapshot=user_snap, default=0)
        premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0), int(user_data.get("premium_used") or 0), int(user_data.get("premium_daily_used") or 0))
        free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0), int(user_data.get("free_used") or 0), int(user_data.get("standard_free_daily_used") or 0))
        now = datetime.now(UTC)
        patch: dict[str, Any] = {"updated_at": now}
        patch["authoritative_daily_state"] = True
        patch["last_access_kind"] = f"refund_{reservation.kind}"
        if reservation.kind == "credits":
            patch["credits"] = credits + reservation.cost
            patch["credits_updated_at"] = now
        elif reservation.kind == "premium_daily":
            patch["premium_used"] = max(0, premium_used - 1)
            patch["premium_daily_used"] = patch["premium_used"]
            patch["premium_daily_limit"] = PREMIUM_DAILY_LIMIT
            patch["premium_daily_remaining"] = max(0, PREMIUM_DAILY_LIMIT - patch["premium_used"])
            patch["premium_daily_exhausted"] = patch["premium_used"] >= PREMIUM_DAILY_LIMIT
        elif reservation.kind == "standard_free":
            patch["free_used"] = max(0, free_used - 1)
            patch["standard_free_daily_used"] = patch["free_used"]
        ref.set(patch, merge=True)
        user_patch = {"updated_at": now, "authoritative_daily_state": True, "last_access_kind": patch["last_access_kind"]}
        if "credits" in patch:
            user_patch.update({"credits": patch["credits"], "credits_updated_at": now})
        if "premium_daily_used" in patch:
            user_patch.update({
                "premium_used": patch["premium_used"],
                "premium_daily_used": patch["premium_daily_used"],
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "premium_daily_remaining": patch["premium_daily_remaining"],
                "premium_daily_exhausted": patch["premium_daily_exhausted"],
            })
        if len(user_patch) > 3:
            user_ref.set(user_patch, merge=True)
        if "credits" in patch:
            refund_access = dict(reservation.access_state or {})
            refund_access["credits"] = patch["credits"]
            _log_fortune_access_ledger(db, reservation=FortuneReservation(user_id=reservation.user_id, fortune_type=reservation.fortune_type, kind=reservation.kind, cost=reservation.cost, date_key=reservation.date_key, access_state=refund_access), event_type="refund")
    except Exception:
        return
