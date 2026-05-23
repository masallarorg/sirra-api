from datetime import UTC, datetime, timedelta
from typing import Any
import hashlib
import logging
import json

import httpx

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.subscription import SubscriptionStatus
from app.services.security_guard import device_hash, require_device_hash
from app.services.daily_access_clock import daily_access_key
from app.services.monetization_guard import (
    PREMIUM_DAILY_LIMIT,
    WELCOME_CREDITS,
    _is_subscription_active,
    _subscription_expires_at,
    latest_credit_balance,
)

router = APIRouter()
logger = logging.getLogger(__name__)

PREMIUM_PRODUCT_DURATIONS = {
    "sirra_premium_weekly": 7,
    "sirra_premium_monthly": 30,
    "sirra_premium_yearly": 365,
}

CREDIT_PRODUCT_AMOUNTS = {
    "sirra_credits_10": 10,
    "sirra_credits_30_v1": 30,
    "sirra_credits_75": 75,
    # Backward-compatible legacy IDs. Keep them so old test builds/webhooks do not break.
    "credits_10": 10,
    "credits_30": 30,
    "credits_75": 75,
    "nura_credits_10": 10,
    "nura_credits_30": 30,
    "nura_credits_75": 75,
}


class CreditBalanceSyncRequest(BaseModel):
    credits: int = Field(ge=0, le=10000)


class CreditBalanceSyncResponse(BaseModel):
    user_id: str
    credits: int
    server_credits_before: int
    updated: bool



class GooglePlayVerifyRequest(BaseModel):
    product_id: str
    purchase_token: str
    is_subscription: bool = False
    purchase_id: str | None = None
    package_name: str | None = None


class GooglePlayVerifyResponse(BaseModel):
    user_id: str
    product_id: str
    processed: bool
    entitlement: str = "free"
    credits: int = 0
    expires_at: str | None = None
    access: dict[str, Any] = Field(default_factory=dict)


class SelfiePremiumClaimRequest(BaseModel):
    consent_accepted: bool
    selfie_added: bool = False
    persona_tags: list[str] = Field(default_factory=list)
    device_install_id: str | None = None


class SelfiePremiumClaimResponse(BaseModel):
    user_id: str
    active: bool
    entitlement: str
    expires_at: str
    provider: str = "welcome_trial"
    credits: int = 0
    access: dict[str, Any] = Field(default_factory=dict)


class RewardedCreditClaimResponse(BaseModel):
    user_id: str
    credits: int
    reward_credits: int
    daily_rewarded_ads_used: int
    daily_rewarded_ads_limit: int


def _firestore_client():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
            else:
                firebase_admin.initialize_app()
        return firestore.client()
    except Exception as exc:
        raise AppError(
            error_code="SUBSCRIPTION_FIREBASE_NOT_READY",
            user_message="Premium durumu okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc




def _purchase_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _google_play_product_kind(product_id: str) -> str:
    if product_id in PREMIUM_PRODUCT_DURATIONS:
        return "subscription"
    if product_id in CREDIT_PRODUCT_AMOUNTS:
        return "credit"
    raise AppError(
        error_code="GOOGLE_PLAY_PRODUCT_UNKNOWN",
        user_message="Bu ürün uygulama tarafından tanınmıyor.",
        developer_message=f"product_id={product_id}",
        status_code=422,
    )


def _google_play_credentials():
    try:
        from google.oauth2 import service_account
    except Exception as exc:
        raise AppError(
            error_code="GOOGLE_PLAY_AUTH_PACKAGE_MISSING",
            user_message="Google Play doğrulama servisi hazır değil.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    if settings.google_play_service_account_json:
        try:
            info = json.loads(settings.google_play_service_account_json)
            return service_account.Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as exc:
            raise AppError(
                error_code="GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_INVALID",
                user_message="Google Play doğrulama anahtarı okunamadı.",
                developer_message=str(exc),
                status_code=503,
                retryable=True,
            ) from exc
    if settings.google_play_service_account_path:
        try:
            return service_account.Credentials.from_service_account_file(settings.google_play_service_account_path, scopes=scopes)
        except Exception as exc:
            raise AppError(
                error_code="GOOGLE_PLAY_SERVICE_ACCOUNT_FILE_INVALID",
                user_message="Google Play doğrulama anahtarı okunamadı.",
                developer_message=str(exc),
                status_code=503,
                retryable=True,
            ) from exc
    raise AppError(
        error_code="GOOGLE_PLAY_SERVICE_ACCOUNT_MISSING",
        user_message="Satın alma doğrulaması henüz yapılandırılmadı.",
        developer_message="Set GOOGLE_PLAY_SERVICE_ACCOUNT_JSON or GOOGLE_PLAY_SERVICE_ACCOUNT_PATH in Render.",
        status_code=503,
        retryable=True,
    )


def _google_play_access_token() -> str:
    try:
        from google.auth.transport.requests import Request
        credentials = _google_play_credentials()
        credentials.refresh(Request())
        return credentials.token
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            error_code="GOOGLE_PLAY_ACCESS_TOKEN_FAILED",
            user_message="Google Play satın alma doğrulaması yapılamadı.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc


async def _google_play_get_purchase(*, product_id: str, purchase_token: str, is_subscription: bool, package_name: str) -> dict[str, Any]:
    token = _google_play_access_token()
    safe_token = purchase_token.strip()
    if is_subscription:
        url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package_name}/purchases/subscriptionsv2/tokens/{safe_token}"
    else:
        url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package_name}/purchases/products/{product_id}/tokens/{safe_token}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if response.status_code >= 400:
        raise AppError(
            error_code="GOOGLE_PLAY_PURCHASE_VERIFY_FAILED",
            user_message="Google Play satın alma doğrulanamadı.",
            developer_message=response.text[:1200],
            status_code=400,
        )
    return response.json()


async def _google_play_consume_product(*, product_id: str, purchase_token: str, package_name: str) -> None:
    try:
        token = _google_play_access_token()
        url = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{package_name}/purchases/products/{product_id}/tokens/{purchase_token}:consume"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code >= 400:
            # Do not roll back granted credits after a successful purchase verification.
            # The purchase token hash prevents duplicate credit grants.
            logger.warning("Google Play consume failed product_id=%s status=%s body=%s", product_id, response.status_code, response.text[:500])
    except Exception as exc:
        logger.warning("Google Play consume failed product_id=%s: %s", product_id, exc)


def _subscription_expiry_from_google(data: dict[str, Any], fallback_days: int) -> datetime:
    line_items = data.get("lineItems") if isinstance(data.get("lineItems"), list) else []
    expiry = None
    for item in line_items:
        if isinstance(item, dict) and item.get("expiryTime"):
            expiry = str(item.get("expiryTime"))
            break
    if expiry:
        try:
            parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return parsed.astimezone(UTC)
        except Exception:
            pass
    return datetime.now(UTC) + timedelta(days=fallback_days)


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


def _status_from_data(user_id: str, data: dict[str, Any] | None) -> SubscriptionStatus:
    data = data or {}
    active = _is_subscription_active(data)
    expires = _subscription_expires_at(data)
    entitlement = "premium" if active else "free"
    return SubscriptionStatus(
        user_id=user_id,
        active=active,
        entitlement=entitlement,
        provider=str(data.get("provider") or "revenuecat"),
        expires_at=expires.isoformat() if expires else None,
    )


def _clamped_counter(*values: Any, maximum: int = 100000) -> int:
    parsed: list[int] = []
    for value in values:
        try:
            parsed.append(max(0, int(value or 0)))
        except Exception:
            pass
    return min(max(parsed) if parsed else 0, maximum)


def _reconcile_premium_access_state(db, user_id: str, *, access_kind: str = "subscription_access_state") -> dict[str, Any]:
    """Server-owned daily entitlement reconciliation.

    Calling this on app start/status fixes two production problems:
    * premium days are derived from the real subscription expiry, not a client flag;
    * premium daily rights reset to 5 at the Turkey-time day boundary even if the
      user has not started a fortune yet.
    """
    sub_ref = db.collection("subscriptions").document(user_id)
    money_ref = db.collection("monetization").document(user_id)
    user_ref = db.collection("users").document(user_id)

    sub_snap = sub_ref.get()
    money_snap = money_ref.get()
    user_snap = user_ref.get()
    sub = sub_snap.to_dict() if sub_snap.exists else {}
    money = money_snap.to_dict() if money_snap.exists else {}
    user_data = user_snap.to_dict() if user_snap.exists else {}

    active = _is_subscription_active(sub)
    expires_at = _subscription_expires_at(sub) if active else None
    today = daily_access_key()
    now = datetime.now(UTC)

    credits = latest_credit_balance(
        money,
        user_data,
        monetization_snapshot=money_snap,
        user_snapshot=user_snap,
        default=WELCOME_CREDITS,
    )
    daily_date = str((money or {}).get("daily_date") or (user_data or {}).get("daily_date") or "")
    premium_used = _clamped_counter(
        (money or {}).get("premium_used"),
        (money or {}).get("premium_daily_used"),
        (user_data or {}).get("premium_used"),
        (user_data or {}).get("premium_daily_used"),
        maximum=PREMIUM_DAILY_LIMIT,
    )
    free_used = _clamped_counter(
        (money or {}).get("free_used"),
        (money or {}).get("standard_free_daily_used"),
        (user_data or {}).get("free_used"),
        (user_data or {}).get("standard_free_daily_used"),
    )
    daily_reset_applied = daily_date != today
    if daily_reset_applied:
        premium_used = 0
        free_used = 0
        daily_date = today

    premium_remaining = max(0, PREMIUM_DAILY_LIMIT - premium_used) if active else 0
    premium_exhausted = bool(active and premium_remaining == 0)
    access = {
        "credits": credits,
        "charged_credits": 0,
        "access_kind": access_kind,
        "premium_daily_used": premium_used,
        "premium_used": premium_used,
        "premium_daily_limit": PREMIUM_DAILY_LIMIT,
        "premium_daily_remaining": premium_remaining,
        "premium_daily_exhausted": premium_exhausted,
        "standard_free_daily_used": free_used,
        "free_used": free_used,
        "daily_date": daily_date,
        "is_premium": bool(active),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "premium_until": expires_at.isoformat() if expires_at else None,
        "user_message": None,
        "authoritative_daily_state": True,
        "force_daily_decrease": daily_reset_applied,
        "daily_reset_applied": daily_reset_applied,
        "daily_reset_timezone": "Europe/Istanbul",
        "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
        "updated_at": now.isoformat(),
    }

    daily_payload = {
        "credits": credits,
        "credits_updated_at": now,
        "daily_date": daily_date,
        "premium_used": premium_used,
        "premium_daily_used": premium_used,
        "premium_daily_limit": PREMIUM_DAILY_LIMIT,
        "premium_daily_remaining": premium_remaining,
        "premium_daily_exhausted": premium_exhausted,
        "free_used": free_used,
        "standard_free_daily_used": free_used,
        "last_access_kind": access_kind,
        "authoritative_daily_state": True,
        "force_daily_decrease": daily_reset_applied,
        "daily_reset_applied": daily_reset_applied,
        "updated_at": now,
    }
    money_ref.set(daily_payload, merge=True)
    user_ref.set(
        {
            **daily_payload,
            "is_premium": bool(active),
            "premium_until": expires_at if expires_at else None,
            "premiumUntil": expires_at if expires_at else None,
            "subscription_checked_at": now,
        },
        merge=True,
    )
    if sub and not active and (sub.get("active") is True or sub.get("entitlement") == "premium"):
        sub_ref.set({"active": False, "entitlement": "free", "expired_checked_at": now, "updated_at": now}, merge=True)
    return access


@router.get("/products")
async def subscription_products() -> dict[str, Any]:
    return {
        "premium": [
            {"id": "sirra_premium_weekly", "title": "Haftalık Premium", "daily_free_fortunes": 5, "duration_days": 7},
            {"id": "sirra_premium_monthly", "title": "Aylık Premium", "daily_free_fortunes": 5, "duration_days": 30},
            {"id": "sirra_premium_yearly", "title": "Yıllık Premium", "daily_free_fortunes": 5, "duration_days": 365},
        ],
        "credits": [
            {"id": "sirra_credits_10", "credits": 10},
            {"id": "sirra_credits_30_v1", "credits": 30},
            {"id": "sirra_credits_75", "credits": 75},
        ],
        "rewarded_ads": {"reward_credits": 2, "daily_limit": 3},
        "welcome_trial": {"premium_days": 1, "once_per_user": True, "once_per_device": True, "selfie_optional": True, "max_premium_devices": 2, "requires_explicit_consent": True},
    }


@router.post("/welcome-persona/claim", response_model=SelfiePremiumClaimResponse)
async def claim_welcome_persona_reward(
    request: SelfiePremiumClaimRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> SelfiePremiumClaimResponse:
    """Grant the first-run persona reward once per account and once per device.

    Selfie is not a biometric gate and is not used to infer gender, age, identity,
    ethnicity, health, or any sensitive attribute. It only unlocks an optional
    personalization profile and a one-time promotional trial after explicit consent.
    """
    if not request.consent_accepted:
        raise AppError(
            error_code="WELCOME_TRIAL_CONSENT_REQUIRED",
            user_message="Başlangıç ödülü için onay vermelisin.",
            developer_message="consent_accepted=false",
            status_code=422,
        )
    device_id = request.device_install_id or current_user.device_id
    hashed_device = require_device_hash(device_id)
    db = _firestore_client()
    try:
        from firebase_admin import firestore
    except Exception as exc:
        raise AppError(
            error_code="FIREBASE_TRANSACTION_NOT_READY",
            user_message="Ödül güvenlik kontrolü tamamlanamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    sub_ref = db.collection("subscriptions").document(current_user.uid)
    monetization_ref = db.collection("monetization").document(current_user.uid)
    user_ref = db.collection("users").document(current_user.uid)
    device_ref = db.collection("promo_devices").document(hashed_device)
    transaction = db.transaction()
    now = datetime.now(UTC)
    today = daily_access_key()

    @firestore.transactional
    def _claim(transaction):
        sub_snap = sub_ref.get(transaction=transaction)
        device_snap = device_ref.get(transaction=transaction)
        money_snap = monetization_ref.get(transaction=transaction)
        sub = sub_snap.to_dict() if sub_snap.exists else {}
        device = device_snap.to_dict() if device_snap.exists else {}
        money = money_snap.to_dict() if money_snap.exists else {}

        if sub.get("welcome_trial_granted") is True or sub.get("welcome_persona_claimed") is True or sub.get("selfie_wheel_claimed") is True:
            raise AppError(
                error_code="WELCOME_PERSONA_ALREADY_CLAIMED",
                user_message="Başlangıç premium ödülü bu hesapta daha önce kullanıldı.",
                developer_message=f"uid={current_user.uid}",
                status_code=409,
            )
        if device and device.get("claimed") is True and device.get("user_id") != current_user.uid:
            raise AppError(
                error_code="WELCOME_PERSONA_DEVICE_ALREADY_USED",
                user_message="Bu cihazda kişisel başlangıç ödülü daha önce kullanıldı.",
                developer_message=f"uid={current_user.uid} device_hash={hashed_device[:8]}",
                status_code=409,
            )

        expires_at = now + timedelta(days=1)
        credits = int(money.get("credits") or 0)
        premium_used = max(int(money.get("premium_used") or 0), int(money.get("premium_daily_used") or 0))
        free_used = max(int(money.get("free_used") or 0), int(money.get("standard_free_daily_used") or 0))
        daily_date = str(money.get("daily_date") or today)
        if daily_date != today:
            premium_used = 0
            free_used = 0
            daily_date = today

        transaction.set(sub_ref, {
            "user_id": current_user.uid,
            "active": True,
            "entitlement": "premium",
            "provider": "welcome_trial",
            "product_id": "welcome_trial_1_day",
            "expires_at": expires_at.isoformat(),
            "welcome_persona_claimed": True,
            "selfie_wheel_claimed": True,
            "selfie_consent_accepted": bool(request.selfie_added),
            "selfie_persona_tags": [str(tag).strip() for tag in (request.persona_tags or []) if str(tag).strip()][:12] if request.selfie_added else [],
            "promo_device_hash": hashed_device,
            "updated_at": now,
        }, merge=True)
        transaction.set(device_ref, {
            "claimed": True,
            "user_id": current_user.uid,
            "claimed_at": now,
            "claim_type": "welcome_trial",
        }, merge=True)
        daily_remaining = max(0, 5 - premium_used)
        daily_payload = {
            "credits": credits,
            "daily_date": daily_date,
            "premium_used": premium_used,
            "premium_daily_used": premium_used,
            "premium_daily_limit": 5,
            "premium_daily_remaining": daily_remaining,
            "premium_daily_exhausted": premium_used >= 5,
            "free_used": free_used,
            "standard_free_daily_used": free_used,
            "last_access_kind": "welcome_trial",
            "authoritative_daily_state": True,
            "daily_reset_applied": False,
            "updated_at": now,
        }
        transaction.set(monetization_ref, daily_payload, merge=True)
        transaction.set(user_ref, {**daily_payload, "is_premium": True, "premium_until": expires_at.isoformat(), "updated_at": now}, merge=True)
        access = {
            "credits": credits,
            "charged_credits": 0,
            "access_kind": "welcome_trial",
            "premium_daily_used": premium_used,
            "premium_used": premium_used,
            "premium_daily_limit": 5,
            "premium_daily_remaining": daily_remaining,
            "premium_daily_exhausted": premium_used >= 5,
            "standard_free_daily_used": free_used,
            "free_used": free_used,
            "daily_date": daily_date,
            "is_premium": True,
            "user_message": None,
            "authoritative_daily_state": True,
            "daily_reset_applied": False,
            "daily_reset_timezone": "Europe/Istanbul",
            "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
        }
        return expires_at, credits, access

    expires_at, credits, access = _claim(transaction)
    return SelfiePremiumClaimResponse(
        user_id=current_user.uid,
        active=True,
        entitlement="premium",
        expires_at=expires_at.isoformat(),
        provider="welcome_trial",
        credits=credits,
        access=access,
    )


@router.post("/selfie-premium/claim", response_model=SelfiePremiumClaimResponse)
async def claim_selfie_premium_day(
    request: SelfiePremiumClaimRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> SelfiePremiumClaimResponse:
    return await claim_welcome_persona_reward(request=request, current_user=current_user)


@router.post("/rewarded-ad/claim", response_model=RewardedCreditClaimResponse)
async def claim_rewarded_ad_credit(current_user: CurrentUser = Depends(require_current_user)) -> RewardedCreditClaimResponse:
    """Grant backend-owned rewarded-ad credits after the mobile ad callback completes.

    The balance is updated in a Firestore transaction and mirrored to both
    monetization/{uid} and users/{uid}. This prevents the old users document or
    old monetization document from overwriting the fresh rewarded-ad credit after
    logout/login.
    """
    db = _firestore_client()
    from firebase_admin import firestore

    money_ref = db.collection("monetization").document(current_user.uid)
    user_ref = db.collection("users").document(current_user.uid)
    today = daily_access_key()
    reward_credits = 2
    daily_limit = 3
    transaction = db.transaction()

    @firestore.transactional
    def _claim(transaction):
        money_snap = money_ref.get(transaction=transaction)
        user_snap = user_ref.get(transaction=transaction)
        money = money_snap.to_dict() if money_snap.exists else {}
        user_data = user_snap.to_dict() if user_snap.exists else {}

        monetization_credits = int((money or {}).get("credits") or 0)
        user_credits = int((user_data or {}).get("credits") or 0)
        credits_before = max(monetization_credits, user_credits)
        daily_date = str((money or {}).get("daily_date") or (user_data or {}).get("rewarded_ads_daily_date") or (user_data or {}).get("daily_date") or "")
        used = int(
            (money or {}).get("rewarded_ads_used")
            or (money or {}).get("daily_rewarded_ads_used")
            or (user_data or {}).get("rewarded_ads_used")
            or (user_data or {}).get("daily_rewarded_ads_used")
            or 0
        )
        if daily_date != today:
            used = 0
        if used >= daily_limit:
            raise AppError(
                error_code="REWARDED_AD_DAILY_LIMIT",
                user_message="Bugünkü reklamla kredi kazanma hakkın doldu. Yarın tekrar deneyebilirsin.",
                developer_message=f"uid={current_user.uid} used={used}",
                status_code=429,
            )

        credits_after = credits_before + reward_credits
        used_after = used + 1
        now = datetime.now(UTC)
        payload = {
            "credits": credits_after,
            "daily_date": today,
            "rewarded_ads_used": used_after,
            "daily_rewarded_ads_used": used_after,
            "daily_rewarded_ads_limit": daily_limit,
            "last_rewarded_credit_amount": reward_credits,
            "last_rewarded_source": "backend_admob_rewarded",
            "last_rewarded_ad_at": now,
            "credits_updated_at": now,
            "updated_at": now,
        }
        transaction.set(money_ref, payload, merge=True)
        transaction.set(user_ref, payload, merge=True)
        return credits_after, used_after, now

    credits, used, now = _claim(transaction)
    try:
        claim_payload = {
            "uid": current_user.uid,
            "amount": reward_credits,
            "source": "admob_rewarded",
            "ad_network": "admob",
            "daily_date": today,
            "daily_used_after": used,
            "daily_limit": daily_limit,
            "created_at": now,
        }
        db.collection("rewarded_ad_claims").add(claim_payload)
        db.collection("credit_ledger").add({
            **claim_payload,
            "type": "rewarded_ad",
            "reason": "AdMob rewarded ad completed",
            "balance_after": credits,
        })
    except Exception as exc:
        logger.warning("rewarded ad claim log failed uid=%s: %s", current_user.uid, exc)
    return RewardedCreditClaimResponse(user_id=current_user.uid, credits=credits, reward_credits=reward_credits, daily_rewarded_ads_used=used, daily_rewarded_ads_limit=daily_limit)



@router.post("/google-play/verify", response_model=GooglePlayVerifyResponse)
async def verify_google_play_purchase(
    request: GooglePlayVerifyRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> GooglePlayVerifyResponse:
    product_id = request.product_id.strip()
    purchase_token = request.purchase_token.strip()
    if not purchase_token:
        raise AppError(
            error_code="GOOGLE_PLAY_PURCHASE_TOKEN_MISSING",
            user_message="Satın alma bilgisi eksik geldi.",
            developer_message="purchase_token is empty",
            status_code=422,
        )

    kind = _google_play_product_kind(product_id)
    is_subscription = kind == "subscription"
    if bool(request.is_subscription) != is_subscription:
        raise AppError(
            error_code="GOOGLE_PLAY_PURCHASE_TYPE_MISMATCH",
            user_message="Satın alma türü ürünle eşleşmiyor.",
            developer_message=f"product_id={product_id} is_subscription={request.is_subscription}",
            status_code=422,
        )

    package_name = (request.package_name or settings.google_play_package_name or "com.sirrafal.app").strip()
    if package_name != settings.google_play_package_name:
        raise AppError(
            error_code="GOOGLE_PLAY_PACKAGE_MISMATCH",
            user_message="Satın alma uygulama paketiyle eşleşmiyor.",
            developer_message=f"request={package_name} expected={settings.google_play_package_name}",
            status_code=422,
        )

    google_data = await _google_play_get_purchase(
        product_id=product_id,
        purchase_token=purchase_token,
        is_subscription=is_subscription,
        package_name=package_name,
    )

    now = datetime.now(UTC)
    token_hash = _purchase_token_hash(purchase_token)
    db = _firestore_client()
    purchase_ref = db.collection("google_play_purchases").document(token_hash)
    user_ref = db.collection("users").document(current_user.uid)
    sub_ref = db.collection("subscriptions").document(current_user.uid)
    money_ref = db.collection("monetization").document(current_user.uid)

    if is_subscription:
        state = str(google_data.get("subscriptionState") or "")
        if state not in {"SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"}:
            raise AppError(
                error_code="GOOGLE_PLAY_SUBSCRIPTION_NOT_ACTIVE",
                user_message="Premium satın alma aktif görünmüyor.",
                developer_message=f"state={state} data={str(google_data)[:900]}",
                status_code=400,
            )
        expires_at = _subscription_expiry_from_google(google_data, PREMIUM_PRODUCT_DURATIONS[product_id])
        purchase_ref.set({
            "user_id": current_user.uid,
            "product_id": product_id,
            "kind": "subscription",
            "package_name": package_name,
            "purchase_id": request.purchase_id,
            "google_state": state,
            "expires_at": expires_at.isoformat(),
            "last_verified_at": now,
            "google_data": google_data,
        }, merge=True)
        sub_ref.set({
            "user_id": current_user.uid,
            "active": True,
            "entitlement": "premium",
            "provider": "google_play",
            "product_id": product_id,
            "purchase_token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "updated_at": now,
        }, merge=True)
        money_snap = money_ref.get()
        money = money_snap.to_dict() if money_snap.exists else {}
        today = daily_access_key()
        daily_date = str((money or {}).get("daily_date") or today)
        premium_used = max(int((money or {}).get("premium_used") or 0), int((money or {}).get("premium_daily_used") or 0))
        free_used = max(int((money or {}).get("free_used") or 0), int((money or {}).get("standard_free_daily_used") or 0))
        daily_reset_applied = daily_date != today
        if daily_reset_applied:
            premium_used = 0
            free_used = 0
            daily_date = today
        credits = int((money or {}).get("credits") or 0)
        daily_remaining = max(0, 5 - premium_used)
        daily_payload = {
            "credits": credits,
            "daily_date": daily_date,
            "premium_used": premium_used,
            "premium_daily_used": premium_used,
            "premium_daily_limit": 5,
            "premium_daily_remaining": daily_remaining,
            "premium_daily_exhausted": premium_used >= 5,
            "free_used": free_used,
            "standard_free_daily_used": free_used,
            "last_access_kind": "premium_purchase",
            "authoritative_daily_state": True,
            "daily_reset_applied": daily_reset_applied,
            "updated_at": now,
        }
        money_ref.set(daily_payload, merge=True)
        user_ref.set({**daily_payload, "is_premium": True, "premium_until": expires_at.isoformat(), "updated_at": now}, merge=True)
        access = {
            "credits": credits,
            "charged_credits": 0,
            "access_kind": "premium_purchase",
            "premium_daily_used": premium_used,
            "premium_used": premium_used,
            "premium_daily_limit": 5,
            "premium_daily_remaining": daily_remaining,
            "premium_daily_exhausted": premium_used >= 5,
            "standard_free_daily_used": free_used,
            "free_used": free_used,
            "daily_date": daily_date,
            "is_premium": True,
            "user_message": None,
            "authoritative_daily_state": True,
            "daily_reset_applied": daily_reset_applied,
            "daily_reset_timezone": "Europe/Istanbul",
            "daily_reset_rule": "Her gün 00:01 Türkiye saatinde yenilenir.",
            "expires_at": expires_at.isoformat(),
        }
        return GooglePlayVerifyResponse(
            user_id=current_user.uid,
            product_id=product_id,
            processed=True,
            entitlement="premium",
            credits=access["credits"],
            expires_at=expires_at.isoformat(),
            access=access,
        )

    purchase_state = int(google_data.get("purchaseState", -1))
    if purchase_state != 0:
        raise AppError(
            error_code="GOOGLE_PLAY_PRODUCT_NOT_PURCHASED",
            user_message="Kredi satın alma aktif görünmüyor.",
            developer_message=f"purchaseState={purchase_state} data={str(google_data)[:900]}",
            status_code=400,
        )

    from firebase_admin import firestore
    credit_amount = CREDIT_PRODUCT_AMOUNTS[product_id]
    snapshot = purchase_ref.get()
    if snapshot.exists:
        money_snap = money_ref.get()
        user_snap = user_ref.get()
        money = money_snap.to_dict() if money_snap.exists else {}
        user_data = user_snap.to_dict() if user_snap.exists else {}
        current_credits = max(int((money or {}).get("credits") or 0), int((user_data or {}).get("credits") or 0))
        return GooglePlayVerifyResponse(
            user_id=current_user.uid,
            product_id=product_id,
            processed=False,
            entitlement="credits",
            credits=current_credits,
            access={"credits": current_credits},
        )

    purchase_ref.set({
        "user_id": current_user.uid,
        "product_id": product_id,
        "kind": "credit",
        "package_name": package_name,
        "purchase_id": request.purchase_id,
        "credits_added": credit_amount,
        "google_purchase_state": purchase_state,
        "processed_at": now,
        "google_data": google_data,
    })
    money_snap_before = money_ref.get()
    user_snap_before = user_ref.get()
    money_before = money_snap_before.to_dict() if money_snap_before.exists else {}
    user_before = user_snap_before.to_dict() if user_snap_before.exists else {}
    base_credits = max(int((money_before or {}).get("credits") or 0), int((user_before or {}).get("credits") or 0))
    next_credits = base_credits + credit_amount
    credit_payload = {
        "credits": next_credits,
        "welcome_credits_granted": True,
        "last_credit_product_id": product_id,
        "last_credit_purchase_token_hash": token_hash,
        "credits_updated_at": now,
        "updated_at": now,
    }
    money_ref.set(credit_payload, merge=True)
    user_ref.set(credit_payload, merge=True)
    await _google_play_consume_product(product_id=product_id, purchase_token=purchase_token, package_name=package_name)
    return GooglePlayVerifyResponse(
        user_id=current_user.uid,
        product_id=product_id,
        processed=True,
        entitlement="credits",
        credits=next_credits,
        access={"credits": next_credits, "credits_updated_at": now.isoformat()},
    )


@router.get("/status", response_model=SubscriptionStatus)
async def subscription_status(current_user: CurrentUser = Depends(require_current_user)) -> SubscriptionStatus:
    db = _firestore_client()
    _reconcile_premium_access_state(db, current_user.uid, access_kind="subscription_status")
    snapshot = db.collection("subscriptions").document(current_user.uid).get()
    return _status_from_data(current_user.uid, snapshot.to_dict() if snapshot.exists else None)


@router.get("/access-state")
async def subscription_access_state(current_user: CurrentUser = Depends(require_current_user)) -> dict[str, Any]:
    db = _firestore_client()
    return _reconcile_premium_access_state(db, current_user.uid, access_kind="subscription_access_state")


@router.post("/credits/sync", response_model=CreditBalanceSyncResponse)
async def sync_credit_balance(
    request: CreditBalanceSyncRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> CreditBalanceSyncResponse:
    """Bring the backend credit balance up to the authenticated device balance.

    The mobile app can add credits immediately after an in-app purchase, while the
    Google Play purchase verification may arrive slightly later in development. Fortune
    generation is charged on the backend, so the backend must not see a lower
    credit balance than the user's signed-in device shows.

    This endpoint never decreases server credits. It only sets the backend balance
    to the larger of the existing backend value and the signed-in device value.
    """
    db = _firestore_client()
    ref = db.collection("monetization").document(current_user.uid)
    user_ref = db.collection("users").document(current_user.uid)
    now = datetime.now(UTC)
    snapshot = ref.get()
    user_snapshot = user_ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}
    user_data = user_snapshot.to_dict() if user_snapshot.exists else {}
    before = max(int((data or {}).get("credits") or 0), int((user_data or {}).get("credits") or 0))
    # Production security: the client must never be able to mint credits by sending an arbitrary balance.
    # Credits are increased by Google Play verification, rewarded-ad claim, or admin tools only.
    if settings.allow_client_credit_sync:
        target = max(before, int(request.credits))
    else:
        target = before
    updated = target != before or not snapshot.exists
    sync_payload = {
        "credits": target,
        "welcome_credits_granted": True,
        "last_client_credit_sync_at": now,
        "last_client_credit_sync_value": int(request.credits),
        "credits_updated_at": now,
        "updated_at": now,
    }
    ref.set(sync_payload, merge=True)
    user_ref.set(sync_payload, merge=True)
    return CreditBalanceSyncResponse(
        user_id=current_user.uid,
        credits=target,
        server_credits_before=before,
        updated=updated,
    )


def _revenuecat_expiry_from_event(event: dict[str, Any], product_id: str, now: datetime) -> datetime | None:
    explicit = _parse_expiry(
        event.get("expiration_at_ms")
        or event.get("expiration_at")
        or event.get("expires_at")
        or event.get("expiresAt")
    )
    if explicit is not None:
        return explicit
    purchased_at = _parse_expiry(event.get("purchased_at_ms") or event.get("purchased_at") or event.get("purchasedAt")) or now
    days = PREMIUM_PRODUCT_DURATIONS.get(product_id)
    if days is None:
        return None
    return purchased_at + timedelta(days=days)

@router.post("/webhook/revenuecat")
async def revenuecat_webhook(payload: dict, x_webhook_secret: str | None = Header(default=None)) -> dict:
    if settings.revenuecat_webhook_secret and x_webhook_secret != settings.revenuecat_webhook_secret:
        raise AppError(
            error_code="REVENUECAT_WEBHOOK_UNAUTHORIZED",
            user_message="Webhook yetkilendirilemedi.",
            developer_message="Missing or invalid X-Webhook-Secret header",
            status_code=401,
        )

    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    app_user_id = str(event.get("app_user_id") or event.get("original_app_user_id") or "").strip()
    if not app_user_id:
        raise AppError(
            error_code="REVENUECAT_USER_ID_MISSING",
            user_message="Webhook kullanıcısı okunamadı.",
            developer_message=str(payload)[:1200],
            status_code=422,
        )

    event_type = str(event.get("type") or "").upper()
    active = event_type not in {"CANCELLATION", "EXPIRATION", "BILLING_ISSUE"}
    product_id = str(event.get("product_id") or event.get("entitlement_id") or "premium")

    db = _firestore_client()
    now = datetime.now(UTC)
    expires_at = _revenuecat_expiry_from_event(event, product_id, now)
    credit_amount = CREDIT_PRODUCT_AMOUNTS.get(product_id)
    if credit_amount and event_type in {"INITIAL_PURCHASE", "NON_RENEWING_PURCHASE", "PURCHASE"}:
        money_ref = db.collection("monetization").document(app_user_id)
        user_ref = db.collection("users").document(app_user_id)
        money_snap = money_ref.get()
        user_snap = user_ref.get()
        money = money_snap.to_dict() if money_snap.exists else {}
        user_data = user_snap.to_dict() if user_snap.exists else {}
        next_credits = max(int((money or {}).get("credits") or 0), int((user_data or {}).get("credits") or 0)) + credit_amount
        credit_payload = {
            "credits": next_credits,
            "welcome_credits_granted": True,
            "last_credit_product_id": product_id,
            "last_credit_event_type": event_type,
            "credits_updated_at": now,
            "updated_at": now,
        }
        money_ref.set(credit_payload, merge=True)
        user_ref.set(credit_payload, merge=True)
        return {"received": True, "user_id": app_user_id, "credits_added": credit_amount, "credits": next_credits}

    db.collection("subscriptions").document(app_user_id).set(
        {
            "user_id": app_user_id,
            "active": active,
            "entitlement": "premium" if active else "free",
            "provider": "revenuecat",
            "product_id": product_id,
            "event_type": event_type,
            "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else (str(expires_at) if expires_at else None),
            "updated_at": now,
            "last_payload": payload,
        },
        merge=True,
    )
    db.collection("users").document(app_user_id).set({"is_premium": active, "premium_until": expires_at if active else None, "premiumUntil": expires_at if active else None, "updated_at": now}, merge=True)
    _reconcile_premium_access_state(db, app_user_id, access_kind="revenuecat_webhook")
    return {"received": True, "user_id": app_user_id, "active": active}
