from datetime import UTC, datetime, timedelta
from typing import Any
<<<<<<< HEAD
import hashlib
import logging
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

from fastapi import APIRouter, Depends

from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
<<<<<<< HEAD
from app.schemas.profile import AstrologyDeriveRequest, AstrologyDeriveResponse, UserProfile
from app.services.daily_access_clock import daily_access_key
from app.services.monetization_guard import _is_subscription_active, _subscription_expires_at, _subscription_has_lifetime_access
from app.services.natal_chart import calculate_natal_summary

router = APIRouter()
logger = logging.getLogger(__name__)
=======
from app.schemas.profile import UserProfile
from app.services.daily_access_clock import daily_access_key
from app.services.monetization_guard import _is_subscription_active, _subscription_expires_at, _subscription_has_lifetime_access

router = APIRouter()
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

WELCOME_CREDITS = 7
WELCOME_TRIAL_DAYS = 1
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


def _payload_from_profile(profile: UserProfile, current_user: CurrentUser) -> dict[str, Any]:
    now = datetime.now(UTC)
    email = _clean(profile.email) or _clean(current_user.email)
    payload = {
        "uid": current_user.uid,
        "user_id": current_user.uid,
<<<<<<< HEAD
        "display_name": _clean(profile.display_name) or _clean(current_user.name) or "Misafir",
=======
        "display_name": _clean(profile.display_name) or _clean(current_user.name) or "Sırra kullanıcısı",
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        "email": email,
        "birth_date": _clean(profile.birth_date),
        "birth_date_display": _clean(profile.birth_date_display),
        "birth_time": _clean(profile.birth_time),
        "birth_place": _clean(profile.birth_place),
<<<<<<< HEAD
        "birth_latitude": profile.birth_latitude,
        "birth_longitude": profile.birth_longitude,
        "birth_timezone": _clean(profile.birth_timezone) or "Europe/Istanbul",
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        "zodiac_sign": _clean(profile.zodiac_sign),
        "zodiac_label": _clean(profile.zodiac_label),
        "rising_sign": _clean(profile.rising_sign),
        "moon_sign": _clean(profile.moon_sign),
<<<<<<< HEAD
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
=======
        "relationship_status": _clean(profile.relationship_status),
        "main_interest": _clean(profile.main_interest),
        "notification_opt_in": bool(profile.notification_opt_in),
        "selfie_path": _clean(profile.selfie_path),
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        "selfie_consent_accepted": bool(profile.selfie_consent_accepted),
        "selfie_persona_tags": [str(tag).strip() for tag in (profile.selfie_persona_tags or []) if str(tag).strip()][:12],
        "addressing_preference": _clean(profile.addressing_preference),
        "profile_completed": bool(profile.birth_date and profile.zodiac_sign),
        "updated_at": now,
        "last_login_at": now,
    }
<<<<<<< HEAD
    # Premium status, expiry and credit fields are server-owned. Never trust
    # values supplied by a mobile profile payload.
=======
    premium_until = _parse_datetime(getattr(profile, "premium_until", None) or getattr(profile, "expires_at", None))
    if premium_until and premium_until > now:
        payload["is_premium"] = True
        payload["premium_until"] = premium_until
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    return payload


def _subscription_active(data: dict[str, Any] | None) -> bool:
    return _is_subscription_active(data)


def _ensure_welcome_entitlement(db, user_id: str) -> dict[str, Any]:
    """Idempotently grant every new account 7 credits and a 1-day premium trial.

    It never adds 7 credits twice: the balance becomes at least 7 and the
    welcome_credits_granted/welcome_trial_granted flags are persisted.
    """
    now = datetime.now(UTC)
    today = daily_access_key(now)
    trial_ends_at = now + timedelta(days=WELCOME_TRIAL_DAYS)
    user_ref = db.collection("users").document(user_id)
    money_ref = db.collection("monetization").document(user_id)
    sub_ref = db.collection("subscriptions").document(user_id)

    user_snap = user_ref.get()
    money_snap = money_ref.get()
    sub_snap = sub_ref.get()
    user_data = user_snap.to_dict() if user_snap.exists else {}
    money_data = money_snap.to_dict() if money_snap.exists else {}
    sub_data = sub_snap.to_dict() if sub_snap.exists else {}

<<<<<<< HEAD
    current_credits = int((money_data or {}).get("credits") or 0)
=======
    current_credits = max(int((user_data or {}).get("credits") or 0), int((money_data or {}).get("credits") or 0))
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    target_credits = max(current_credits, WELCOME_CREDITS)
    daily_date = str((money_data or {}).get("daily_date") or today)
    premium_used = max(int((money_data or {}).get("premium_used") or 0), int((money_data or {}).get("premium_daily_used") or 0))
    free_used = max(int((money_data or {}).get("free_used") or 0), int((money_data or {}).get("standard_free_daily_used") or 0))
    daily_reset_applied = daily_date != today
    if daily_reset_applied:
        daily_date = today
        premium_used = 0
        free_used = 0

    money_payload = {
        "credits": target_credits,
        "welcome_credits_granted": True,
        "welcome_trial_granted": True,
        "daily_date": daily_date,
        "premium_used": premium_used,
        "premium_daily_used": premium_used,
        "premium_daily_limit": PREMIUM_DAILY_LIMIT,
        "premium_daily_remaining": max(0, PREMIUM_DAILY_LIMIT - premium_used),
        "free_used": free_used,
        "standard_free_daily_used": free_used,
        "last_access_kind": "welcome_registration",
        "authoritative_daily_state": True,
        "daily_reset_applied": daily_reset_applied,
        "credits_updated_at": now,
        "updated_at": now,
    }
    if not money_snap.exists:
        money_payload["created_at"] = now
    money_ref.set(money_payload, merge=True)

    should_grant_trial = not _subscription_active(sub_data) and sub_data.get("welcome_trial_granted") is not True
    expires_at = _subscription_expires_at(sub_data) if not should_grant_trial else trial_ends_at
    if should_grant_trial:
        sub_ref.set({
            "user_id": user_id,
            "active": True,
            "entitlement": "premium",
            "provider": "backend_welcome_trial",
            "product_id": "welcome_trial_1_day",
            "expires_at": trial_ends_at.isoformat(),
            "premium_daily_limit": PREMIUM_DAILY_LIMIT,
            "welcome_trial_granted": True,
            "created_at": now,
            "updated_at": now,
        }, merge=True)
    elif _subscription_active(sub_data):
        expires_at = _subscription_expires_at(sub_data)

    has_active_subscription = should_grant_trial or _subscription_active(sub_data)
    is_premium = bool(has_active_subscription and (_subscription_has_lifetime_access(sub_data) or (expires_at is not None and expires_at > now)))
<<<<<<< HEAD
    # Do not mirror credits or premium status into users/{uid}. That document is
    # intentionally profile-only; monetization/{uid} and subscriptions/{uid}
    # remain the sole sources of financial and entitlement truth.
=======
    user_ref.set({
        "credits": target_credits,
        "welcome_credits_granted": True,
        "welcome_trial_granted": True,
        "is_premium": bool(is_premium),
        "premium_until": expires_at if expires_at else None,
        "daily_date": daily_date,
        "premium_used": premium_used,
        "premium_daily_used": premium_used,
        "premium_daily_limit": PREMIUM_DAILY_LIMIT,
        "premium_daily_remaining": max(0, PREMIUM_DAILY_LIMIT - premium_used),
        "premium_daily_exhausted": premium_used >= PREMIUM_DAILY_LIMIT,
        "last_access_kind": "welcome_registration",
        "authoritative_daily_state": True,
        "daily_reset_applied": daily_reset_applied,
        "credits_updated_at": now,
        "updated_at": now,
    }, merge=True)
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

    return {
        "credits": target_credits,
        "charged_credits": 0,
        "access_kind": "welcome_registration",
        "premium_daily_used": premium_used,
        "premium_used": premium_used,
        "premium_daily_limit": PREMIUM_DAILY_LIMIT,
        "premium_daily_remaining": max(0, PREMIUM_DAILY_LIMIT - premium_used),
        "premium_daily_exhausted": premium_used >= PREMIUM_DAILY_LIMIT,
        "standard_free_daily_used": free_used,
        "free_used": free_used,
        "daily_date": daily_date,
        "is_premium": bool(is_premium),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "user_message": None,
        "authoritative_daily_state": True,
        "daily_reset_applied": daily_reset_applied,
        "daily_reset_timezone": "Europe/Istanbul",
        "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
    }


<<<<<<< HEAD
def _apply_auto_astrology(payload: dict[str, Any]) -> None:
    if payload.get("astrology_auto_fill") is not True:
        return
    required = (
        payload.get("birth_date"),
        payload.get("birth_time"),
        payload.get("birth_latitude"),
        payload.get("birth_longitude"),
    )
    if any(value is None or str(value).strip() == "" for value in required):
        return
    try:
        result = calculate_natal_summary(
            birth_date=str(payload["birth_date"]),
            birth_time=str(payload["birth_time"]),
            latitude=float(payload["birth_latitude"]),
            longitude=float(payload["birth_longitude"]),
            timezone_name=str(payload.get("birth_timezone") or "Europe/Istanbul"),
        )
    except (TypeError, ValueError) as exc:
        logger.info("automatic astrology skipped: %s", exc)
        return
    payload["zodiac_label"] = result.sun_sign
    slug_map = {
        "Koç": "koc", "Boğa": "boga", "İkizler": "ikizler", "Yengeç": "yengec",
        "Aslan": "aslan", "Başak": "basak", "Terazi": "terazi", "Akrep": "akrep",
        "Yay": "yay", "Oğlak": "oglak", "Kova": "kova", "Balık": "balik",
    }
    payload["zodiac_sign"] = slug_map.get(result.sun_sign, payload.get("zodiac_sign"))
    payload["moon_sign"] = result.moon_sign
    payload["rising_sign"] = result.rising_sign
    payload["birth_timezone"] = result.timezone
    payload["birth_latitude"] = result.latitude
    payload["birth_longitude"] = result.longitude
    payload["astrology_calculation_quality"] = result.quality
    payload["astrology_calculated_at"] = datetime.now(UTC)


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


=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
@router.post("", response_model=UserProfile)
async def upsert_profile(
    profile: UserProfile,
    current_user: CurrentUser = Depends(require_current_user),
) -> UserProfile:
    """Persist the signed-in user's profile with Firebase Admin.

    New accounts are also granted the registration entitlement immediately:
    7 credits and a 1-day premium trial. The grant is idempotent.
    """
    db = _firestore_client()
    payload = _payload_from_profile(profile, current_user)
<<<<<<< HEAD
    _apply_auto_astrology(payload)
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    ref = db.collection("users").document(current_user.uid)

    try:
        snapshot = ref.get()
<<<<<<< HEAD
        if not snapshot.exists:
            payload["created_at"] = datetime.now(UTC)
        ref.set(payload, merge=True)
        # This helper is idempotent and is the only registration entitlement
        # writer. Calling it for every upsert also repairs partially-created accounts.
        access = _ensure_welcome_entitlement(db, current_user.uid)
=======
        registration_trial_until = _parse_datetime(payload.get("premium_until"))
        should_grant_welcome = (not snapshot.exists) or (registration_trial_until is not None and registration_trial_until > datetime.now(UTC))
        if not snapshot.exists:
            payload["created_at"] = datetime.now(UTC)
        ref.set(payload, merge=True)
        if should_grant_welcome:
            access = _ensure_welcome_entitlement(db, current_user.uid)
        else:
            fresh = ref.get().to_dict() or {}
            expires_at = _parse_datetime(fresh.get("premium_until") or fresh.get("premiumUntil") or fresh.get("expires_at") or fresh.get("expiresAt"))
            lifetime = bool(fresh.get("lifetime") or fresh.get("lifetime_premium") or fresh.get("is_lifetime_premium"))
            active = bool(fresh.get("is_premium")) and (lifetime or (expires_at is not None and expires_at > datetime.now(UTC)))
            access = {"is_premium": active, "expires_at": expires_at.isoformat() if expires_at else None}
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
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
<<<<<<< HEAD
        display_name=payload["display_name"] or "Misafir",
=======
        display_name=payload["display_name"] or "Sırra kullanıcısı",
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        email=payload.get("email"),
        birth_date=payload.get("birth_date"),
        birth_date_display=payload.get("birth_date_display"),
        birth_time=payload.get("birth_time"),
        birth_place=payload.get("birth_place"),
<<<<<<< HEAD
        birth_latitude=payload.get("birth_latitude"),
        birth_longitude=payload.get("birth_longitude"),
        birth_timezone=payload.get("birth_timezone"),
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        zodiac_sign=payload.get("zodiac_sign"),
        zodiac_label=payload.get("zodiac_label"),
        rising_sign=payload.get("rising_sign"),
        moon_sign=payload.get("moon_sign"),
<<<<<<< HEAD
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
=======
        relationship_status=payload.get("relationship_status"),
        main_interest=payload.get("main_interest"),
        notification_opt_in=payload.get("notification_opt_in", True),
        selfie_path=payload.get("selfie_path"),
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        selfie_consent_accepted=payload.get("selfie_consent_accepted", False),
        selfie_persona_tags=payload.get("selfie_persona_tags", []),
        addressing_preference=payload.get("addressing_preference"),
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
<<<<<<< HEAD
    sub_snapshot = db.collection("subscriptions").document(current_user.uid).get()
    sub_data = sub_snapshot.to_dict() if sub_snapshot.exists else {}
    premium_until = _subscription_expires_at(sub_data or {})
    premium_flag = _subscription_active(sub_data or {})
    return UserProfile(
        user_id=current_user.uid,
        display_name=_clean(data.get("display_name")) or _clean(current_user.name) or "Misafir",
=======
    premium_until = _parse_datetime(data.get("premium_until") or data.get("premiumUntil") or data.get("expires_at") or data.get("expiresAt"))
    lifetime = bool(data.get("lifetime") or data.get("lifetime_premium") or data.get("is_lifetime_premium"))
    premium_flag = bool(data.get("is_premium", False)) and (lifetime or (premium_until is not None and premium_until > datetime.now(UTC)))
    return UserProfile(
        user_id=current_user.uid,
        display_name=_clean(data.get("display_name")) or _clean(current_user.name) or "Sırra kullanıcısı",
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        email=_clean(data.get("email")) or _clean(current_user.email),
        birth_date=_clean(data.get("birth_date")),
        birth_date_display=_clean(data.get("birth_date_display")),
        birth_time=_clean(data.get("birth_time")),
        birth_place=_clean(data.get("birth_place")),
<<<<<<< HEAD
        birth_latitude=data.get("birth_latitude"),
        birth_longitude=data.get("birth_longitude"),
        birth_timezone=_clean(data.get("birth_timezone")) or "Europe/Istanbul",
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        zodiac_sign=_clean(data.get("zodiac_sign")),
        zodiac_label=_clean(data.get("zodiac_label")),
        rising_sign=_clean(data.get("rising_sign")),
        moon_sign=_clean(data.get("moon_sign")),
<<<<<<< HEAD
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
=======
        relationship_status=_clean(data.get("relationship_status")),
        main_interest=_clean(data.get("main_interest")),
        notification_opt_in=bool(data.get("notification_opt_in", True)),
        selfie_path=_clean(data.get("selfie_path")),
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
        selfie_consent_accepted=bool(data.get("selfie_consent_accepted", False)),
        selfie_persona_tags=data.get("selfie_persona_tags") if isinstance(data.get("selfie_persona_tags"), list) else [],
        addressing_preference=_clean(data.get("addressing_preference")),
        is_premium=premium_flag,
        premium_until=premium_until.isoformat() if premium_until else None,
    )
<<<<<<< HEAD



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
            from firebase_admin import storage

            bucket = storage.bucket()
            for prefix in (f"users/{uid}/", f"selfies/{uid}/"):
                for blob in bucket.list_blobs(prefix=prefix):
                    blob.delete()
        except Exception as exc:
            # Some deployments intentionally do not configure Firebase Storage.
            logger.warning("account delete storage cleanup skipped uid=%s: %s", uid, exc)

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
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
