from datetime import UTC, datetime, timedelta
from typing import Any
import hashlib
import logging

from fastapi import APIRouter, Depends

from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.profile import AstrologyDeriveRequest, AstrologyDeriveResponse, UserProfile
from app.services.daily_access_clock import daily_access_key
from app.services.security_guard import device_hash
from app.services.monetization_guard import _is_subscription_active, _subscription_expires_at, _subscription_has_lifetime_access
from app.services.natal_chart import calculate_natal_summary

router = APIRouter()
logger = logging.getLogger(__name__)

WELCOME_CREDITS = 7
WELCOME_TRIAL_DAYS = 2
PREMIUM_DAILY_LIMIT = 5


def _firestore_client():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        from app.core.config import settings

        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                cred = credentials.Certificate(settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception as exc:
        raise AppError(
            error_code="PROFILE_FIREBASE_ADMIN_NOT_READY",
            user_message="Profil kayit servisi hazir degil. Firebase service account ayarini kontrol et.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
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
        return _parse_datetime(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None


def _apply_auto_astrology(payload: dict[str, Any]) -> None:
    """Fill sun, moon and rising signs when complete birth data is available.

    Profile saving must never fail just because astrology data is incomplete or
    temporarily invalid. Manual astrology values are preserved when automatic
    filling is disabled.
    """
    if payload.get("astrology_auto_fill", True) is False:
        return

    birth_date = _clean(payload.get("birth_date"))
    birth_time = _clean(payload.get("birth_time"))
    latitude = payload.get("birth_latitude")
    longitude = payload.get("birth_longitude")
    timezone_name = _clean(payload.get("birth_timezone")) or "Europe/Istanbul"

    if not birth_date or not birth_time or latitude is None or longitude is None:
        return

    try:
        result = calculate_natal_summary(
            birth_date=birth_date,
            birth_time=birth_time,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone_name=timezone_name,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Profile astrology autofill skipped: invalid input error=%s", type(exc).__name__)
        return
    except Exception as exc:
        logger.warning("Profile astrology autofill skipped: calculation error=%s", type(exc).__name__)
        return

    payload["zodiac_label"] = result.sun_sign
    payload["moon_sign"] = result.moon_sign
    payload["rising_sign"] = result.rising_sign
    payload["astrology_calculation_quality"] = result.quality
    payload["birth_timezone"] = result.timezone
    payload["birth_latitude"] = result.latitude
    payload["birth_longitude"] = result.longitude


def _payload_from_profile(profile: UserProfile, current_user: CurrentUser) -> dict[str, Any]:
    now = datetime.now(UTC)
    email = _clean(profile.email) or _clean(current_user.email)
    payload = {
        "uid": current_user.uid,
        "user_id": current_user.uid,
        "display_name": _clean(profile.display_name) or _clean(current_user.name) or "Misafir",
        "email": email,
        "birth_date": _clean(profile.birth_date),
        "birth_date_display": _clean(profile.birth_date_display),
        "birth_time": _clean(profile.birth_time),
        "birth_place": _clean(profile.birth_place),
        "birth_latitude": profile.birth_latitude,
        "birth_longitude": profile.birth_longitude,
        "birth_timezone": _clean(profile.birth_timezone) or "Europe/Istanbul",
        "zodiac_sign": _clean(profile.zodiac_sign),
        "zodiac_label": _clean(profile.zodiac_label),
        "rising_sign": _clean(profile.rising_sign),
        "moon_sign": _clean(profile.moon_sign),
        "astrology_auto_fill": bool(profile.astrology_auto_fill),
        "astrology_calculation_quality": _clean(profile.astrology_calculation_quality),
        "relationship_status": _clean(profile.relationship_status),
        "main_interest": _clean(profile.main_interest),
        "reading_tone": _clean(profile.reading_tone),
        "smart_suggestions": bool(profile.smart_suggestions),
        "automatic_personalization": bool(profile.automatic_personalization),
        "fast_mode": bool(profile.fast_mode),
        "data_saver": bool(profile.data_saver),
        "notification_opt_in": bool(profile.notification_opt_in),
        # A device-local path is never meaningful or safe to persist on the server.
        "selfie_consent_accepted": bool(profile.selfie_consent_accepted),
        "selfie_persona_tags": [str(tag).strip() for tag in (profile.selfie_persona_tags or []) if str(tag).strip()][:12],
        "addressing_preference": _clean(profile.addressing_preference),
        "gender_identity": _clean(profile.gender_identity),
        "soulmate_portrait_preference": _clean(profile.soulmate_portrait_preference),
        "profile_completed": bool(profile.birth_date and profile.zodiac_sign),
        "updated_at": now,
        "last_login_at": now,
    }
    # Premium status, expiry and credit fields are server-owned. Never trust
    # values supplied by a mobile profile payload.
    return payload


def _subscription_active(data: dict[str, Any] | None) -> bool:
    return _is_subscription_active(data)


def _ensure_welcome_entitlement(db, user_id: str, device_id: str | None) -> dict[str, Any]:
    """Atomically grant 7 welcome credits and a one-device-only 2-day trial."""
    from firebase_admin import firestore

    now = datetime.now(UTC)
    today = daily_access_key(now)
    trial_ends_at = now + timedelta(days=2)
    hashed_device = device_hash(device_id)

    money_ref = db.collection("monetization").document(user_id)
    sub_ref = db.collection("subscriptions").document(user_id)
    device_ref = db.collection("promo_devices").document(hashed_device) if hashed_device else None
    transaction = db.transaction()

    @firestore.transactional
    def _apply(transaction):
        money_snap = money_ref.get(transaction=transaction)
        sub_snap = sub_ref.get(transaction=transaction)
        device_snap = device_ref.get(transaction=transaction) if device_ref is not None else None

        money = money_snap.to_dict() if money_snap.exists else {}
        sub = sub_snap.to_dict() if sub_snap.exists else {}
        device = device_snap.to_dict() if device_snap is not None and device_snap.exists else {}

        credits = max(int(money.get("credits") or 0), WELCOME_CREDITS)
        daily_date = str(money.get("daily_date") or today)
        premium_used = max(int(money.get("premium_used") or 0), int(money.get("premium_daily_used") or 0))
        free_used = max(int(money.get("free_used") or 0), int(money.get("standard_free_daily_used") or 0))
        if daily_date != today:
            daily_date = today
            premium_used = 0
            free_used = 0

        already_trialed = sub.get("welcome_trial_granted") is True
        device_claimed_elsewhere = bool(device.get("claimed")) and device.get("user_id") != user_id
        grant_trial = bool(hashed_device) and not already_trialed and not device_claimed_elsewhere and not _subscription_active(sub)

        transaction.set(money_ref, {
            "credits": credits,
            "welcome_credits_granted": True,
            "daily_date": daily_date,
            "premium_used": premium_used,
            "premium_daily_used": premium_used,
            "premium_daily_limit": PREMIUM_DAILY_LIMIT,
            "premium_daily_remaining": max(0, PREMIUM_DAILY_LIMIT - premium_used),
            "free_used": free_used,
            "standard_free_daily_used": free_used,
            "authoritative_daily_state": True,
            "credits_updated_at": now,
            "updated_at": now,
        }, merge=True)

        expires_at = _subscription_expires_at(sub)
        if grant_trial:
            expires_at = trial_ends_at
            transaction.set(sub_ref, {
                "user_id": user_id,
                "active": True,
                "entitlement": "premium",
                "provider": "backend_welcome_trial",
                "product_id": "welcome_trial_2_days",
                "duration_days": 2,
                "started_at": now,
                "expires_at": trial_ends_at.isoformat(),
                "premium_daily_limit": PREMIUM_DAILY_LIMIT,
                "welcome_trial_granted": True,
                "promo_device_hash": hashed_device,
                "updated_at": now,
            }, merge=True)
            transaction.set(device_ref, {
                "claimed": True,
                "user_id": user_id,
                "claim_type": "welcome_trial",
                "claimed_at": now,
                "expires_at": trial_ends_at.isoformat(),
            }, merge=True)

        active = grant_trial or _subscription_active(sub)
        remaining = max(0, PREMIUM_DAILY_LIMIT - premium_used) if active else 0
        return {
            "credits": credits,
            "charged_credits": 0,
            "access_kind": "welcome_trial" if grant_trial else "welcome_registration",
            "premium_daily_used": premium_used,
            "premium_used": premium_used,
            "premium_daily_limit": PREMIUM_DAILY_LIMIT,
            "premium_daily_remaining": remaining,
            "premium_daily_exhausted": bool(active and remaining == 0),
            "standard_free_daily_used": free_used,
            "free_used": free_used,
            "daily_date": daily_date,
            "is_premium": bool(active),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "trial_granted": grant_trial,
            "trial_denied_device_already_used": device_claimed_elsewhere,
            "authoritative_daily_state": True,
            "daily_reset_applied": False,
            "daily_reset_timezone": "Europe/Istanbul",
            "daily_reset_rule": "Premium üyeye her gün 5 ücretsiz yorum hakkı verilir.",
        }

    return _apply(transaction)


@router.post("/astrology/derive", response_model=AstrologyDeriveResponse)
async def derive_astrology(
    request: AstrologyDeriveRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> AstrologyDeriveResponse:
    del current_user
    try:
        result = calculate_natal_summary(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            latitude=request.birth_latitude,
            longitude=request.birth_longitude,
            timezone_name=request.birth_timezone,
        )
    except ValueError as exc:
        raise AppError(
            error_code="ASTROLOGY_INPUT_INVALID",
            user_message=str(exc),
            developer_message=str(exc),
            status_code=422,
        ) from exc
    return AstrologyDeriveResponse(
        sun_sign=result.sun_sign,
        moon_sign=result.moon_sign,
        rising_sign=result.rising_sign,
        calculation_quality=result.quality,
        birth_timezone=result.timezone,
        birth_latitude=result.latitude,
        birth_longitude=result.longitude,
    )


@router.post("", response_model=UserProfile)
async def upsert_profile(
    profile: UserProfile,
    current_user: CurrentUser = Depends(require_current_user),
) -> UserProfile:
    """Persist the signed-in user's profile with Firebase Admin.

    New accounts are also granted the registration entitlement immediately:
    7 credits and a 2-day premium trial. The grant is idempotent.
    """
    db = _firestore_client()
    payload = _payload_from_profile(profile, current_user)
    _apply_auto_astrology(payload)
    ref = db.collection("users").document(current_user.uid)

    try:
        snapshot = ref.get()
        if not snapshot.exists:
            payload["created_at"] = datetime.now(UTC)
        ref.set(payload, merge=True)
        # This helper is idempotent and is the only registration entitlement
        # writer. Calling it for every upsert also repairs partially-created accounts.
        access = _ensure_welcome_entitlement(db, current_user.uid, current_user.device_id)
    except Exception as exc:
        raise AppError(
            error_code="PROFILE_SAVE_FAILED",
            user_message="Profil bilgilerin kaydedilemedi. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    return UserProfile(
        user_id=current_user.uid,
        display_name=payload["display_name"] or "Misafir",
        email=payload.get("email"),
        birth_date=payload.get("birth_date"),
        birth_date_display=payload.get("birth_date_display"),
        birth_time=payload.get("birth_time"),
        birth_place=payload.get("birth_place"),
        birth_latitude=payload.get("birth_latitude"),
        birth_longitude=payload.get("birth_longitude"),
        birth_timezone=payload.get("birth_timezone"),
        zodiac_sign=payload.get("zodiac_sign"),
        zodiac_label=payload.get("zodiac_label"),
        rising_sign=payload.get("rising_sign"),
        moon_sign=payload.get("moon_sign"),
        astrology_auto_fill=payload.get("astrology_auto_fill", True),
        astrology_calculation_quality=payload.get("astrology_calculation_quality"),
        relationship_status=payload.get("relationship_status"),
        main_interest=payload.get("main_interest"),
        reading_tone=payload.get("reading_tone"),
        smart_suggestions=payload.get("smart_suggestions", True),
        automatic_personalization=payload.get("automatic_personalization", True),
        fast_mode=payload.get("fast_mode", True),
        data_saver=payload.get("data_saver", False),
        notification_opt_in=payload.get("notification_opt_in", False),
        selfie_path=None,
        selfie_consent_accepted=payload.get("selfie_consent_accepted", False),
        selfie_persona_tags=payload.get("selfie_persona_tags", []),
        addressing_preference=payload.get("addressing_preference"),
        gender_identity=payload.get("gender_identity"),
        soulmate_portrait_preference=payload.get("soulmate_portrait_preference"),
        is_premium=bool(access.get("is_premium")),
        premium_until=access.get("expires_at"),
    )


@router.get("/me", response_model=UserProfile)
async def get_my_profile(current_user: CurrentUser = Depends(require_current_user)) -> UserProfile:
    db = _firestore_client()
    try:
        snapshot = db.collection("users").document(current_user.uid).get()
    except Exception as exc:
        raise AppError(
            error_code="PROFILE_READ_FAILED",
            user_message="Profil bilgilerin okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    data = snapshot.to_dict() if snapshot.exists else {}
    data = data or {}
    sub_snapshot = db.collection("subscriptions").document(current_user.uid).get()
    sub_data = sub_snapshot.to_dict() if sub_snapshot.exists else {}
    premium_until = _subscription_expires_at(sub_data or {})
    premium_flag = _subscription_active(sub_data or {})
    return UserProfile(
        user_id=current_user.uid,
        display_name=_clean(data.get("display_name")) or _clean(current_user.name) or "Misafir",
        email=_clean(data.get("email")) or _clean(current_user.email),
        birth_date=_clean(data.get("birth_date")),
        birth_date_display=_clean(data.get("birth_date_display")),
        birth_time=_clean(data.get("birth_time")),
        birth_place=_clean(data.get("birth_place")),
        birth_latitude=data.get("birth_latitude"),
        birth_longitude=data.get("birth_longitude"),
        birth_timezone=_clean(data.get("birth_timezone")) or "Europe/Istanbul",
        zodiac_sign=_clean(data.get("zodiac_sign")),
        zodiac_label=_clean(data.get("zodiac_label")),
        rising_sign=_clean(data.get("rising_sign")),
        moon_sign=_clean(data.get("moon_sign")),
        astrology_auto_fill=data.get("astrology_auto_fill", True) is not False,
        astrology_calculation_quality=_clean(data.get("astrology_calculation_quality")),
        relationship_status=_clean(data.get("relationship_status")),
        main_interest=_clean(data.get("main_interest")),
        reading_tone=_clean(data.get("reading_tone")),
        smart_suggestions=data.get("smart_suggestions", True) is not False,
        automatic_personalization=data.get("automatic_personalization", True) is not False,
        fast_mode=data.get("fast_mode", True) is not False,
        data_saver=bool(data.get("data_saver", False)),
        notification_opt_in=bool(data.get("notification_opt_in", False)),
        selfie_path=None,
        selfie_consent_accepted=bool(data.get("selfie_consent_accepted", False)),
        selfie_persona_tags=data.get("selfie_persona_tags") if isinstance(data.get("selfie_persona_tags"), list) else [],
        addressing_preference=_clean(data.get("addressing_preference")),
        gender_identity=_clean(data.get("gender_identity")),
        soulmate_portrait_preference=_clean(data.get("soulmate_portrait_preference")),
        is_premium=premium_flag,
        premium_until=premium_until.isoformat() if premium_until else None,
    )



def _delete_query_documents(db, collection_name: str, field_name: str, value: str) -> int:
    deleted = 0
    while True:
        docs = list(db.collection(collection_name).where(field_name, "==", value).limit(200).stream())
        if not docs:
            return deleted
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
            deleted += 1
        batch.commit()
        if len(docs) < 200:
            return deleted


def _delete_collection_documents(db, collection_ref) -> int:
    deleted = 0
    while True:
        docs = list(collection_ref.limit(200).stream())
        if not docs:
            return deleted
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
            deleted += 1
        batch.commit()
        if len(docs) < 200:
            return deleted


def _anonymize_promo_device_documents(db, user_id: str) -> int:
    """Detach a promo-device abuse-prevention marker from the deleted account."""
    updated = 0
    former_user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    docs = list(db.collection("promo_devices").where("user_id", "==", user_id).stream())
    for doc in docs:
        data = doc.to_dict() or {}
        doc.reference.set({
            "claimed": bool(data.get("claimed", True)),
            "user_id": None,
            "former_user_hash": former_user_hash,
            "claim_type": data.get("claim_type"),
            "claimed_at": data.get("claimed_at"),
            "account_deleted": True,
            "retention_reason": "promotion_abuse_prevention",
            "account_deleted_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }, merge=False)
        updated += 1
    return updated


def _anonymize_revenuecat_event_documents(db, user_id: str) -> int:
    """Remove account identifiers while retaining an event replay marker."""
    updated = 0
    former_user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    docs = list(db.collection("revenuecat_events").where("user_id", "==", user_id).stream())
    for doc in docs:
        data = doc.to_dict() or {}
        doc.reference.set({
            "user_id": None,
            "former_user_hash": former_user_hash,
            "event_hash": data.get("event_hash") or doc.id,
            "event_id": None,
            "event_type": data.get("event_type"),
            "product_id": data.get("product_id"),
            "credits_added": data.get("credits_added"),
            "account_deleted": True,
            "retention_reason": "purchase_replay_prevention",
            "account_deleted_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }, merge=False)
        updated += 1
    return updated


def _anonymize_purchase_documents(db, user_id: str) -> int:
    """Retain only a pseudonymous token ledger needed to stop purchase replay.

    Google Play purchase tokens must not become reusable after an account is
    deleted. Personal payloads and raw Google responses are removed, while the
    hashed token document remains as a minimal fraud-prevention record.
    """
    updated = 0
    former_user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    docs = list(db.collection("google_play_purchases").where("user_id", "==", user_id).stream())
    for doc in docs:
        data = doc.to_dict() or {}
        doc.reference.set({
            "user_id": None,
            "former_user_hash": former_user_hash,
            "product_id": data.get("product_id"),
            "kind": data.get("kind"),
            "package_name": data.get("package_name"),
            "credits_added": data.get("credits_added"),
            "expires_at": data.get("expires_at"),
            "purchase_id": None,
            "google_data": None,
            "account_deleted": True,
            "retention_reason": "purchase_replay_prevention",
            "account_deleted_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }, merge=False)
        updated += 1
    return updated


@router.delete("/me")
async def delete_my_account(current_user: CurrentUser = Depends(require_current_user)) -> dict[str, Any]:
    """Permanently delete the authenticated account and app-owned personal data."""
    db = _firestore_client()
    uid = current_user.uid
    deleted_documents = 0
    try:
        # Keep a minimal pseudonymous purchase-token ledger so a consumed or
        # active Google Play token cannot be replayed on a newly created account.
        deleted_documents += _anonymize_purchase_documents(db, uid)
        deleted_documents += _anonymize_revenuecat_event_documents(db, uid)
        deleted_documents += _anonymize_promo_device_documents(db, uid)

        # User-created/owned top-level collections. Queries are deliberately
        # separate to avoid requiring a large composite index.
        for collection_name, fields in {
            "fortunes": ("user_id", "uid"),
            "rewarded_ad_sessions": ("user_id",),
            "rewarded_ad_transactions": ("user_id",),
            "rewarded_ad_claims": ("uid", "user_id"),
            "credit_ledger": ("uid", "user_id"),
            "ai_logs": ("user_id", "uid"),
        }.items():
            for field in fields:
                try:
                    deleted_documents += _delete_query_documents(db, collection_name, field, uid)
                except Exception as exc:
                    # A missing index or collection must not block deletion of
                    # the remaining account data; log it for operational review.
                    logger.warning("account delete query failed collection=%s field=%s uid=%s: %s", collection_name, field, uid, exc)

        user_ref = db.collection("users").document(uid)
        for subcollection in ("symbols", "fortunes", "private_state"):
            try:
                deleted_documents += _delete_collection_documents(db, user_ref.collection(subcollection))
            except Exception as exc:
                logger.warning("account delete subcollection failed name=%s uid=%s: %s", subcollection, uid, exc)

        batch = db.batch()
        for collection_name in ("users", "monetization", "subscriptions"):
            batch.delete(db.collection(collection_name).document(uid))
            deleted_documents += 1
        batch.commit()

        try:
            from app.services.object_storage import delete_user_media

            delete_user_media(uid)
        except Exception as exc:
            # Cloudinary cleanup is best-effort and must not block account deletion.
            logger.warning("account delete Cloudinary cleanup skipped uid=%s: %s", uid, exc)

        from firebase_admin import auth

        auth.delete_user(uid)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            error_code="ACCOUNT_DELETE_FAILED",
            user_message="Hesabın tamamen silinemedi. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    return {"deleted": True, "deleted_documents": deleted_documents}
