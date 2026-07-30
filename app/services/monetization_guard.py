from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
PREMIUM_DAILY_CREDIT_GRANT = 0
WELCOME_CREDITS = 7

PREMIUM_PRODUCT_DURATIONS: dict[str, int] = {
    "sirra_premium_weekly": 7,
    "sirra_premium_monthly": 30,
    "sirra_premium_yearly": 365,
    "welcome_trial_2_days": 2,
    "welcome_trial_1_day": 2,
}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class FortuneReservation:
    user_id: str
    fortune_type: str
    kind: str
    cost: int = 0
    date_key: str = ""
    reservation_id: str = ""
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


def _subscription_has_lifetime_access(data: dict[str, Any] | None) -> bool:
    data = data or {}
    product_id = str(data.get("product_id") or data.get("productId") or "").strip().lower()
    entitlement = str(data.get("entitlement") or "").strip().lower()
    return (
        _truthy(data.get("lifetime"))
        or _truthy(data.get("lifetime_premium"))
        or _truthy(data.get("is_lifetime_premium"))
        or product_id in {"sirra_premium_lifetime", "premium_lifetime", "lifetime"}
        or entitlement in {"lifetime", "premium_lifetime"}
    )


def _subscription_active_flag(data: dict[str, Any] | None) -> bool:
    data = data or {}
    entitlement = str(data.get("entitlement") or "").strip().lower()
    if entitlement in {"free", "expired", "cancelled", "canceled"}:
        return False
    return _truthy(data.get("active")) or entitlement == "premium" or _truthy(data.get("is_premium"))


def _subscription_duration_days(data: dict[str, Any] | None) -> int | None:
    data = data or {}
    for key in ("duration_days", "durationDays", "premium_days", "premiumDays"):
        try:
            value = data.get(key)
            if value is not None:
                days = int(value)
                if days > 0:
                    return days
        except Exception:
            pass

    product_id = str(data.get("product_id") or data.get("productId") or "").strip()
    if product_id in PREMIUM_PRODUCT_DURATIONS:
        return PREMIUM_PRODUCT_DURATIONS[product_id]

    provider = str(data.get("provider") or "").strip().lower()
    if "welcome" in provider or _truthy(data.get("welcome_trial_granted")):
        return 2
    return None


def _subscription_started_at(data: dict[str, Any] | None) -> datetime | None:
    data = data or {}
    for key in (
        "started_at",
        "start_at",
        "start_time",
        "purchased_at",
        "purchasedAt",
        "purchase_time",
        "purchaseTime",
        "created_at",
        "createdAt",
        "activated_at",
        "activatedAt",
        "last_verified_at",
        "lastVerifiedAt",
    ):
        parsed = _parse_expiry(data.get(key))
        if parsed is not None:
            return parsed

    # Last-resort migration path for old docs that only had active:true and updated_at.
    # This prevents accidental endless premium while still giving legacy paid docs
    # a deterministic expiry instead of dropping them immediately.
    return _parse_expiry(data.get("updated_at") or data.get("updatedAt"))


def _subscription_expires_at(data: dict[str, Any] | None) -> datetime | None:
    data = data or {}
    explicit = _parse_expiry(
        data.get("expires_at")
        or data.get("expiresAt")
        or data.get("premium_until")
        or data.get("premiumUntil")
        or data.get("expiration_at_ms")
        or data.get("expirationAtMs")
    )
    if explicit is not None:
        return explicit
    if _subscription_has_lifetime_access(data):
        return None

    days = _subscription_duration_days(data)
    started_at = _subscription_started_at(data)
    if days is not None and started_at is not None:
        from datetime import timedelta

        return started_at + timedelta(days=days)
    return None


def _is_subscription_active(data: dict[str, Any] | None) -> bool:
    data = data or {}
    if not _subscription_active_flag(data):
        return False
    if _subscription_has_lifetime_access(data):
        return True
    expires_at = _subscription_expires_at(data)
    if expires_at is None:
        # IMPORTANT: active:true without expires_at used to mean endless premium.
        # That is what made premium days never decrease. Timed premium must have
        # a real expiry, or enough legacy data to infer one from product duration.
        return False
    return expires_at > datetime.now(UTC)


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
    """Return the server-owned credit balance.

    ``monetization/{uid}`` is the sole financial source. ``users/{uid}`` used to
    be writable by the client and is therefore never allowed to override a
    monetization balance. A users-document fallback is accepted only for data
    explicitly stamped by the backend migration marker.
    """
    money = _credit_candidate(monetization_data, monetization_snapshot)
    if money is not None:
        return money[0]

    user_data = user_data or {}
    trusted_legacy = str(user_data.get("financial_source") or "") in {
        "backend_v2",
        "admin_migration_v2",
    }
    if trusted_legacy:
        user = _credit_candidate(user_data, user_snapshot)
        if user is not None:
            return user[0]
    return max(0, int(default))


def user_has_active_premium(user_id: str) -> bool:
    """Return server-authoritative premium state from subscriptions/{uid}."""
    db = _firestore_client()
    snapshot = db.collection("subscriptions").document(user_id).get()
    return _is_subscription_active(snapshot.to_dict() if snapshot.exists else None)


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
            reservation_id=f"mock_{uuid4().hex}",
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
    reservation_id = f"fr_{uuid4().hex}"
    sub_ref = db.collection("subscriptions").document(user_id)
    access_ref = db.collection("monetization").document(user_id)
    reservation_ref = db.collection("fortune_access_reservations").document(reservation_id)

    transaction = db.transaction()

    @firestore.transactional
    def _reserve(transaction):
        sub_snap = sub_ref.get(transaction=transaction)
        access_snap = access_ref.get(transaction=transaction)

        sub = sub_snap.to_dict() if sub_snap.exists else None
        # Güvenlik: premium yetkisi sadece subscriptions koleksiyonundan gelir.
        # users.is_premium sadece UI yansımasıdır; kullanıcı tarafından yazılabilir kabul edilmemelidir.
        active_premium = _is_subscription_active(sub)
        premium_device_ok = True
        active_devices_patch = None
        premium_expires_at = _subscription_expires_at(sub) if active_premium else None
        if active_premium:
            premium_device_ok, active_devices_patch = premium_device_allowed(sub, device_id)
            active_premium = active_premium and premium_device_ok
            if not active_premium:
                premium_expires_at = None

        data = access_snap.to_dict() if access_snap.exists else {}
        if not data:
            data = {"credits": WELCOME_CREDITS, "welcome_credits_granted": True}
        # monetization/{uid} is the only financial source used at runtime.
        credits = latest_credit_balance(
            data,
            None,
            monetization_snapshot=access_snap,
            default=WELCOME_CREDITS,
        )
        daily_date = str(data.get("daily_date") or "")
        premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0))
        free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0))
        daily_reset_applied = daily_date != today
        if daily_reset_applied:
            premium_used = 0
            free_used = 0

        premium_credit_grant_date = str(data.get("premium_credit_grant_date") or "")
        premium_credit_granted = False
        if active_premium and premium_credit_grant_date != today:
            credits += PREMIUM_DAILY_CREDIT_GRANT
            premium_credit_grant_date = today
            premium_credit_granted = True

        now = datetime.now(UTC)
        base_patch = {
            "welcome_credits_granted": True,
            "daily_date": today,
            "updated_at": now,
            "credits_updated_at": now,
            "last_fortune_type": fortune_type,
            "daily_reset_applied": daily_reset_applied,
            "authoritative_daily_state": True,
            "premium_credit_grant_date": premium_credit_grant_date,
            "premium_daily_credit_grant": PREMIUM_DAILY_CREDIT_GRANT,
            "premium_daily_credit_granted": premium_credit_granted,
        }

        def record_reservation(kind: str, charged_cost: int, access_state: dict[str, Any]) -> None:
            transaction.set(
                reservation_ref,
                {
                    "reservation_id": reservation_id,
                    "uid": user_id,
                    "fortune_type": fortune_type,
                    "kind": kind,
                    "cost": charged_cost,
                    "date_key": today,
                    "status": "reserved",
                    "access_state": access_state,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        def state(
            *,
            access_kind: str,
            charged_credits: int,
            credits_after: int,
            premium_after: int,
            free_after: int,
            user_message: str | None = None,
        ) -> dict[str, Any]:
            premium_remaining = max(0, PREMIUM_DAILY_LIMIT - premium_after) if active_premium else 0
            premium_exhausted = bool(active_premium and premium_after >= PREMIUM_DAILY_LIMIT)
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
                "expires_at": premium_expires_at.isoformat() if premium_expires_at else None,
                "premium_until": premium_expires_at.isoformat() if premium_expires_at else None,
                "user_message": user_message,
                "authoritative_daily_state": True,
                "daily_reset_applied": daily_reset_applied,
                "daily_reset_timezone": "Europe/Istanbul",
                "daily_reset_rule": "Premium üyeye her gün 5 ücretsiz yorum hakkı verilir; bu haklarda kredi düşmez.",
                "premium_daily_credit_grant": PREMIUM_DAILY_CREDIT_GRANT,
                "premium_daily_credit_granted": premium_credit_granted,
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
            if active_devices_patch is not None:
                transaction.set(sub_ref, {"active_devices": active_devices_patch, "updated_at": now}, merge=True)
            record_reservation("premium_daily", 0, access_state)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="premium_daily", cost=0, date_key=today, reservation_id=reservation_id, access_state=access_state)

        # Standart üyede ücretsiz günlük fal yoktur; standart kullanıcılar
        # her falı doğrudan kredi bakiyesinden kullanır.

        if credits >= cost:
            credits_after = credits - cost
            premium_credit_notice = None
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
            record_reservation("credits", cost, access_state)
            return FortuneReservation(user_id=user_id, fortune_type=fortune_type, kind="credits", cost=cost, date_key=today, reservation_id=reservation_id, access_state=access_state)

        premium_exhausted_prefix = ""
        raise AppError(
            error_code="FORTUNE_CREDITS_REQUIRED",
            user_message=("Premium hesabın başka cihazlarda aktif olduğu için bu cihazda günlük premium hakkı kullanılamadı. " if (not active_premium and premium_device_ok is False) else premium_exhausted_prefix) + f"Bu fal için {cost} kredi gerekir. Premium günlük 5 ücretsiz yorum hakkın doldu. Kredi bakiyenle devam edebilir veya yarın yenilenen hakkını kullanabilirsin.",
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
            "reservation_id": reservation.reservation_id,
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


async def commit_fortune_access(reservation: FortuneReservation) -> None:
    """Mark a reservation completed without changing the reserved balance."""
    if reservation.kind in {"mock", "none"} or not reservation.reservation_id:
        return
    try:
        db = _firestore_client()
        from firebase_admin import firestore

        reservation_ref = db.collection("fortune_access_reservations").document(reservation.reservation_id)
        transaction = db.transaction()

        @firestore.transactional
        def _commit(tx):
            snapshot = reservation_ref.get(transaction=tx)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict() or {}
            if data.get("status") != "reserved":
                return False
            tx.set(
                reservation_ref,
                {
                    "status": "completed",
                    "completed_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
                merge=True,
            )
            return True

        _commit(transaction)
    except Exception:
        # The actual access change was already committed atomically. This marker
        # is operational metadata and must not break a completed reading.
        return


async def refund_fortune_access(reservation: FortuneReservation) -> None:
    """Idempotently refund a failed reading using one Firestore transaction."""
    if reservation.kind in {"mock", "none"} or (settings.mock_ai and settings.allow_mock_auth):
        return
    try:
        db = _firestore_client()
        from firebase_admin import firestore

        access_ref = db.collection("monetization").document(reservation.user_id)
        reservation_ref = db.collection("fortune_access_reservations").document(reservation.reservation_id)
        transaction = db.transaction()

        @firestore.transactional
        def _refund(tx):
            reservation_snap = reservation_ref.get(transaction=tx) if reservation.reservation_id else None
            if reservation_snap is not None and reservation_snap.exists:
                reservation_data = reservation_snap.to_dict() or {}
                if reservation_data.get("status") != "reserved":
                    return None

            access_snap = access_ref.get(transaction=tx)
            data = access_snap.to_dict() if access_snap.exists else {}
            credits = latest_credit_balance(data, None, monetization_snapshot=access_snap, default=0)
            premium_used = max(int(data.get("premium_used") or 0), int(data.get("premium_daily_used") or 0))
            free_used = max(int(data.get("free_used") or 0), int(data.get("standard_free_daily_used") or 0))
            now = datetime.now(UTC)
            patch: dict[str, Any] = {
                "updated_at": now,
                "authoritative_daily_state": True,
                "last_access_kind": f"refund_{reservation.kind}",
            }
            if reservation.kind == "credits":
                patch["credits"] = credits + reservation.cost
                patch["credits_updated_at"] = now
            elif reservation.kind == "premium_daily":
                # Do not decrement today's counter when the failed reservation
                # belongs to a previous daily window that has already reset.
                if str(data.get("daily_date") or "") == reservation.date_key:
                    patch["premium_used"] = max(0, premium_used - 1)
                    patch["premium_daily_used"] = patch["premium_used"]
                    patch["premium_daily_limit"] = PREMIUM_DAILY_LIMIT
                    patch["premium_daily_remaining"] = max(0, PREMIUM_DAILY_LIMIT - patch["premium_used"])
                    patch["premium_daily_exhausted"] = patch["premium_used"] >= PREMIUM_DAILY_LIMIT
            elif reservation.kind == "standard_free":
                if str(data.get("daily_date") or "") == reservation.date_key:
                    patch["free_used"] = max(0, free_used - 1)
                    patch["standard_free_daily_used"] = patch["free_used"]

            tx.set(access_ref, patch, merge=True)
            if reservation.reservation_id:
                tx.set(
                    reservation_ref,
                    {
                        "status": "refunded",
                        "refunded_at": now,
                        "updated_at": now,
                    },
                    merge=True,
                )
            return patch

        patch = _refund(transaction)
        if patch and "credits" in patch:
            refund_access = dict(reservation.access_state or {})
            refund_access["credits"] = patch["credits"]
            _log_fortune_access_ledger(
                db,
                reservation=FortuneReservation(
                    user_id=reservation.user_id,
                    fortune_type=reservation.fortune_type,
                    kind=reservation.kind,
                    cost=reservation.cost,
                    date_key=reservation.date_key,
                    reservation_id=reservation.reservation_id,
                    access_state=refund_access,
                ),
                event_type="refund",
            )
    except Exception:
        return
