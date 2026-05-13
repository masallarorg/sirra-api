from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.subscription import SubscriptionStatus
from app.services.security_guard import device_hash, require_device_hash

router = APIRouter()

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


class SelfiePremiumClaimRequest(BaseModel):
    consent_accepted: bool
    selfie_added: bool = False
    persona_tags: list[str] = []
    device_install_id: str | None = None


class SelfiePremiumClaimResponse(BaseModel):
    user_id: str
    active: bool
    entitlement: str
    expires_at: str
    provider: str = "welcome_trial"
    credits: int = 0
    access: dict[str, Any] = {}


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


def _status_from_data(user_id: str, data: dict[str, Any] | None) -> SubscriptionStatus:
    data = data or {}
    active = bool(data.get("active") or data.get("entitlement") == "premium")
    entitlement = "premium" if active else "free"
    return SubscriptionStatus(
        user_id=user_id,
        active=active,
        entitlement=entitlement,
        provider=str(data.get("provider") or "revenuecat"),
        expires_at=str(data.get("expires_at") or "") or None,
    )


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
        "rewarded_ads": {"reward_credits": 1, "daily_limit": 3},
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
    today = now.date().isoformat()

    @firestore.transactional
    def _claim(transaction):
        sub_snap = sub_ref.get(transaction=transaction)
        device_snap = device_ref.get(transaction=transaction)
        money_snap = monetization_ref.get(transaction=transaction)
        sub = sub_snap.to_dict() if sub_snap.exists else {}
        device = device_snap.to_dict() if device_snap.exists else {}
        money = money_snap.to_dict() if money_snap.exists else {}

        if sub.get("welcome_persona_claimed") is True or sub.get("selfie_wheel_claimed") is True:
            raise AppError(
                error_code="WELCOME_PERSONA_ALREADY_CLAIMED",
                user_message="Bu kişisel başlangıç ödülü bu hesapta daha önce kullanıldı.",
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
        premium_used = int(money.get("premium_used") or 0)
        free_used = int(money.get("free_used") or 0)
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
        transaction.set(monetization_ref, {
            "credits": credits,
            "daily_date": daily_date,
            "premium_used": premium_used,
            "free_used": free_used,
            "updated_at": now,
        }, merge=True)
        transaction.set(user_ref, {"is_premium": True, "updated_at": now}, merge=True)
        access = {
            "credits": credits,
            "charged_credits": 0,
            "access_kind": "welcome_trial",
            "premium_daily_used": premium_used,
            "premium_daily_limit": 5,
            "premium_daily_remaining": max(0, 5 - premium_used),
            "standard_free_daily_used": free_used,
            "daily_date": daily_date,
            "is_premium": True,
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
    """Grant one backend-owned rewarded-ad credit after the mobile ad callback completes."""
    db = _firestore_client()
    ref = db.collection("monetization").document(current_user.uid)
    today = datetime.now(UTC).date().isoformat()
    reward_credits = 1
    daily_limit = 3
    snapshot = ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}
    credits = int(data.get("credits") or 0)
    daily_date = str(data.get("daily_date") or "")
    used = int(data.get("rewarded_ads_used") or 0)
    if daily_date != today:
        used = 0
    if used >= daily_limit:
        raise AppError(
            error_code="REWARDED_AD_DAILY_LIMIT",
            user_message="Bugünkü reklamla kredi kazanma hakkın doldu. Yarın tekrar deneyebilirsin.",
            developer_message=f"uid={current_user.uid} used={used}",
            status_code=429,
        )
    credits += reward_credits
    used += 1
    ref.set({
        "credits": credits,
        "daily_date": today,
        "rewarded_ads_used": used,
        "updated_at": datetime.now(UTC),
    }, merge=True)
    return RewardedCreditClaimResponse(user_id=current_user.uid, credits=credits, reward_credits=reward_credits, daily_rewarded_ads_used=used, daily_rewarded_ads_limit=daily_limit)


@router.get("/status", response_model=SubscriptionStatus)
async def subscription_status(current_user: CurrentUser = Depends(require_current_user)) -> SubscriptionStatus:
    db = _firestore_client()
    snapshot = db.collection("subscriptions").document(current_user.uid).get()
    return _status_from_data(current_user.uid, snapshot.to_dict() if snapshot.exists else None)


@router.post("/credits/sync", response_model=CreditBalanceSyncResponse)
async def sync_credit_balance(
    request: CreditBalanceSyncRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> CreditBalanceSyncResponse:
    """Bring the backend credit balance up to the authenticated device balance.

    The mobile app can add credits immediately after an in-app purchase, while the
    RevenueCat webhook may arrive later or may be disabled in development. Fortune
    generation is charged on the backend, so the backend must not see a lower
    credit balance than the user's signed-in device shows.

    This endpoint never decreases server credits. It only sets the backend balance
    to the larger of the existing backend value and the signed-in device value.
    """
    db = _firestore_client()
    ref = db.collection("monetization").document(current_user.uid)
    now = datetime.now(UTC)
    snapshot = ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}
    before = int((data or {}).get("credits") or 0)
    # Production security: the client must never be able to mint credits by sending an arbitrary balance.
    # Credits are increased by Google Play/RevenueCat webhook, rewarded-ad claim, or admin tools only.
    if settings.allow_client_credit_sync:
        target = max(before, int(request.credits))
    else:
        target = before
    updated = target != before or not snapshot.exists
    ref.set(
        {
            "credits": target,
            "welcome_credits_granted": True,
            "last_client_credit_sync_at": now,
            "last_client_credit_sync_value": int(request.credits),
            "updated_at": now,
        },
        merge=True,
    )
    return CreditBalanceSyncResponse(
        user_id=current_user.uid,
        credits=target,
        server_credits_before=before,
        updated=updated,
    )


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
    expires_at = event.get("expiration_at_ms") or event.get("purchased_at_ms")

    db = _firestore_client()
    now = datetime.now(UTC)
    credit_amount = CREDIT_PRODUCT_AMOUNTS.get(product_id)
    if credit_amount and event_type in {"INITIAL_PURCHASE", "NON_RENEWING_PURCHASE", "PURCHASE"}:
        from firebase_admin import firestore

        db.collection("monetization").document(app_user_id).set(
            {
                "credits": firestore.Increment(credit_amount),
                "welcome_credits_granted": True,
                "last_credit_product_id": product_id,
                "last_credit_event_type": event_type,
                "updated_at": now,
            },
            merge=True,
        )
        return {"received": True, "user_id": app_user_id, "credits_added": credit_amount}

    db.collection("subscriptions").document(app_user_id).set(
        {
            "user_id": app_user_id,
            "active": active,
            "entitlement": "premium" if active else "free",
            "provider": "revenuecat",
            "product_id": product_id,
            "event_type": event_type,
            "expires_at": str(expires_at) if expires_at else None,
            "updated_at": now,
            "last_payload": payload,
        },
        merge=True,
    )
    db.collection("users").document(app_user_id).set({"is_premium": active, "updated_at": now}, merge=True)
    return {"received": True, "user_id": app_user_id, "active": active}
