from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.profile import UserProfile

router = APIRouter()


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


def _payload_from_profile(profile: UserProfile, current_user: CurrentUser) -> dict[str, Any]:
    now = datetime.now(UTC)
    email = _clean(profile.email) or _clean(current_user.email)
    return {
        "uid": current_user.uid,
        "user_id": current_user.uid,
        "display_name": _clean(profile.display_name) or _clean(current_user.name) or "Sırra kullanıcısı",
        "email": email,
        "birth_date": _clean(profile.birth_date),
        "birth_date_display": _clean(profile.birth_date_display),
        "zodiac_sign": _clean(profile.zodiac_sign),
        "zodiac_label": _clean(profile.zodiac_label),
        "birth_time": _clean(profile.birth_time),
        "birth_place": _clean(profile.birth_place),
        "rising_sign": _clean(profile.rising_sign),
        "moon_sign": _clean(profile.moon_sign),
        "relationship_status": _clean(profile.relationship_status),
        "main_interest": _clean(profile.main_interest),
        "notification_opt_in": bool(profile.notification_opt_in),
        "selfie_path": _clean(profile.selfie_path),
        "selfie_consent_accepted": bool(profile.selfie_consent_accepted),
        "selfie_persona_tags": [str(tag).strip() for tag in (profile.selfie_persona_tags or []) if str(tag).strip()][:12],
        "addressing_preference": _clean(profile.addressing_preference),
        "is_premium": bool(profile.is_premium),
        "profile_completed": bool(profile.birth_date and profile.zodiac_sign),
        "updated_at": now,
        "last_login_at": now,
    }


@router.post("", response_model=UserProfile)
async def upsert_profile(
    profile: UserProfile,
    current_user: CurrentUser = Depends(require_current_user),
) -> UserProfile:
    """Persist the signed-in user's profile with Firebase Admin.

    This endpoint is intentionally backend-owned. The mobile app must not rely only
    on client Firestore writes, because Firestore rules/configuration mistakes can
    make registration appear successful while the profile document stays empty.
    """
    db = _firestore_client()
    payload = _payload_from_profile(profile, current_user)
    ref = db.collection("users").document(current_user.uid)

    try:
        snapshot = ref.get()
        if not snapshot.exists:
            payload["created_at"] = datetime.now(UTC)
        ref.set(payload, merge=True)
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
        display_name=payload["display_name"] or "Sırra kullanıcısı",
        email=payload.get("email"),
        birth_date=payload.get("birth_date"),
        birth_date_display=payload.get("birth_date_display"),
        birth_time=payload.get("birth_time"),
        birth_place=payload.get("birth_place"),
        zodiac_sign=payload.get("zodiac_sign"),
        zodiac_label=payload.get("zodiac_label"),
        rising_sign=payload.get("rising_sign"),
        moon_sign=payload.get("moon_sign"),
        relationship_status=payload.get("relationship_status"),
        main_interest=payload.get("main_interest"),
        notification_opt_in=payload.get("notification_opt_in", True),
        selfie_path=payload.get("selfie_path"),
        selfie_consent_accepted=payload.get("selfie_consent_accepted", False),
        selfie_persona_tags=payload.get("selfie_persona_tags", []),
        addressing_preference=payload.get("addressing_preference"),
        is_premium=payload.get("is_premium", False),
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
    return UserProfile(
        user_id=current_user.uid,
        display_name=_clean(data.get("display_name")) or _clean(current_user.name) or "Sırra kullanıcısı",
        email=_clean(data.get("email")) or _clean(current_user.email),
        birth_date=_clean(data.get("birth_date")),
        birth_date_display=_clean(data.get("birth_date_display")),
        birth_time=_clean(data.get("birth_time")),
        birth_place=_clean(data.get("birth_place")),
        zodiac_sign=_clean(data.get("zodiac_sign")),
        zodiac_label=_clean(data.get("zodiac_label")),
        rising_sign=_clean(data.get("rising_sign")),
        moon_sign=_clean(data.get("moon_sign")),
        relationship_status=_clean(data.get("relationship_status")),
        main_interest=_clean(data.get("main_interest")),
        notification_opt_in=bool(data.get("notification_opt_in", True)),
        selfie_path=_clean(data.get("selfie_path")),
        selfie_consent_accepted=bool(data.get("selfie_consent_accepted", False)),
        selfie_persona_tags=data.get("selfie_persona_tags") if isinstance(data.get("selfie_persona_tags"), list) else [],
        addressing_preference=_clean(data.get("addressing_preference")),
        is_premium=bool(data.get("is_premium", False)),
    )
