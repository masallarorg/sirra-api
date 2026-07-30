from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.services.monetization_guard import _is_subscription_active, _subscription_expires_at
from app.services.push_notifications import notify_admin_message

router = APIRouter()


class AdminIdentity(BaseModel):
    is_admin: bool
    uid: str
    email: str | None = None


class AdminOverview(BaseModel):
    users: int = 0
    active_premium: int = 0
    active_trials: int = 0
    disabled_accounts: int = 0
    total_credits: int = 0
    generated_at: str


class AdminUserItem(BaseModel):
    uid: str
    display_name: str = "Sırra kullanıcısı"
    email: str = ""
    credits: int = 0
    is_premium: bool = False
    premium_until: str | None = None
    premium_provider: str = ""
    daily_used: int = 0
    daily_limit: int = 5
    notification_opt_in: bool = False
    account_disabled: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class AdminUsersResponse(BaseModel):
    items: list[AdminUserItem]
    count: int


class PremiumAdminRequest(BaseModel):
    active: bool = True
    days: int | None = Field(default=30, ge=1, le=3650)
    lifetime: bool = False
    reason: str = Field(default="Mobil admin işlemi", min_length=2, max_length=240)

    @model_validator(mode="after")
    def validate_duration(self):
        if self.active and not self.lifetime and self.days is None:
            raise ValueError("Süreli premium için gün sayısı gereklidir.")
        return self


class CreditAdminRequest(BaseModel):
    delta: int | None = Field(default=None, ge=-100000, le=100000)
    absolute: int | None = Field(default=None, ge=0, le=100000)
    reason: str = Field(default="Mobil admin kredi işlemi", min_length=2, max_length=240)

    @model_validator(mode="after")
    def validate_mode(self):
        if (self.delta is None) == (self.absolute is None):
            raise ValueError("Yalnızca delta veya absolute alanlarından biri verilmelidir.")
        return self


class NotificationAdminRequest(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    body: str = Field(min_length=2, max_length=240)
    route: str = Field(default="/", max_length=180)


class AccountAdminRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="Mobil admin hesap işlemi", min_length=2, max_length=240)


def _firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        if settings.firebase_credentials_path:
            firebase_admin.initialize_app(credentials.Certificate(settings.firebase_credentials_path))
        else:
            firebase_admin.initialize_app()
    return firestore.client()


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return parsed.isoformat()
    text = str(value).strip()
    return text or None


def _is_admin_claim(user: CurrentUser) -> bool:
    claims = user.claims or {}
    if claims.get("admin") is True or claims.get("role") == "admin":
        return True
    email = (user.email or "").strip().lower()
    return bool(email and email in settings.admin_emails_list)


async def require_admin_user(current_user: CurrentUser = Depends(require_current_user)) -> CurrentUser:
    if _is_admin_claim(current_user):
        return current_user
    if settings.allow_mock_auth and (current_user.claims or {}).get("mock"):
        return current_user
    try:
        db = _firestore_client()
        snapshot = db.collection("admins").document(current_user.uid).get()
        data = snapshot.to_dict() if snapshot.exists else {}
        if data and data.get("active") is True:
            return current_user
    except Exception as exc:
        raise AppError(
            error_code="ADMIN_AUTH_CHECK_FAILED",
            user_message="Admin yetkisi doğrulanamadı.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc
    raise AppError(
        error_code="ADMIN_FORBIDDEN",
        user_message="Bu alan yalnızca yetkili admin hesabına açıktır.",
        developer_message=f"Admin access denied for uid={current_user.uid}",
        status_code=403,
    )


def _audit(db, *, admin: CurrentUser, action: str, target_uid: str, details: dict[str, Any]) -> None:
    from firebase_admin import firestore

    db.collection("admin_audit_logs").document().set(
        {
            "admin_uid": admin.uid,
            "admin_email": admin.email,
            "action": action,
            "target_uid": target_uid,
            "details": details,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )


def _user_item(db, user_doc, *, include_auth: bool = False) -> AdminUserItem:
    data = user_doc.to_dict() or {}
    uid = user_doc.id
    sub_doc = db.collection("subscriptions").document(uid).get()
    sub = sub_doc.to_dict() if sub_doc.exists else {}
    monet_doc = db.collection("monetization").document(uid).get()
    monet = monet_doc.to_dict() if monet_doc.exists else {}
    premium_until = _subscription_expires_at(sub or {})
    disabled = False
    if include_auth:
        try:
            from firebase_admin import auth

            disabled = bool(auth.get_user(uid).disabled)
        except Exception:
            disabled = bool(data.get("account_disabled") is True)
    return AdminUserItem(
        uid=uid,
        display_name=str(data.get("display_name") or "Sırra kullanıcısı"),
        email=str(data.get("email") or ""),
        credits=max(0, int((monet or {}).get("credits") or 0)),
        is_premium=_is_subscription_active(sub or {}),
        premium_until=_as_iso(premium_until),
        premium_provider=str((sub or {}).get("provider") or ""),
        daily_used=max(0, int((monet or {}).get("premium_used") or (monet or {}).get("premium_daily_used") or 0)),
        daily_limit=max(1, int((monet or {}).get("premium_daily_limit") or 5)),
        notification_opt_in=bool(data.get("notification_opt_in") is True),
        account_disabled=disabled,
        created_at=_as_iso(data.get("created_at")),
        updated_at=_as_iso(data.get("updated_at")),
    )


@router.get("/me", response_model=AdminIdentity)
async def admin_me(admin: CurrentUser = Depends(require_admin_user)) -> AdminIdentity:
    return AdminIdentity(is_admin=True, uid=admin.uid, email=admin.email)


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(admin: CurrentUser = Depends(require_admin_user)) -> AdminOverview:
    del admin
    db = _firestore_client()
    users = list(db.collection("users").limit(1000).stream())
    active_premium = 0
    active_trials = 0
    total_credits = 0
    disabled_accounts = 0
    for user in users:
        uid = user.id
        sub_doc = db.collection("subscriptions").document(uid).get()
        sub = sub_doc.to_dict() if sub_doc.exists else {}
        if _is_subscription_active(sub or {}):
            active_premium += 1
            provider = str((sub or {}).get("provider") or "").lower()
            product = str((sub or {}).get("product_id") or "").lower()
            if "trial" in provider or "trial" in product:
                active_trials += 1
        monet_doc = db.collection("monetization").document(uid).get()
        monet = monet_doc.to_dict() if monet_doc.exists else {}
        total_credits += max(0, int((monet or {}).get("credits") or 0))
        if (user.to_dict() or {}).get("account_disabled") is True:
            disabled_accounts += 1
    return AdminOverview(
        users=len(users),
        active_premium=active_premium,
        active_trials=active_trials,
        disabled_accounts=disabled_accounts,
        total_credits=total_credits,
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get("/users", response_model=AdminUsersResponse)
async def admin_users(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=40, ge=1, le=100),
    admin: CurrentUser = Depends(require_admin_user),
) -> AdminUsersResponse:
    del admin
    db = _firestore_client()
    clean = q.strip().lower()
    docs = list(db.collection("users").limit(max(limit * 4, 100)).stream())
    if clean:
        docs = [
            doc
            for doc in docs
            if clean in doc.id.lower()
            or clean in str((doc.to_dict() or {}).get("email") or "").lower()
            or clean in str((doc.to_dict() or {}).get("display_name") or "").lower()
        ]
    docs = docs[:limit]
    return AdminUsersResponse(items=[_user_item(db, doc, include_auth=True) for doc in docs], count=len(docs))


@router.post("/users/{uid}/premium", response_model=AdminUserItem)
async def admin_set_premium(
    uid: str,
    request: PremiumAdminRequest,
    admin: CurrentUser = Depends(require_admin_user),
) -> AdminUserItem:
    from firebase_admin import firestore

    db = _firestore_client()
    now = datetime.now(UTC)
    ref = db.collection("subscriptions").document(uid)
    if request.active:
        expires_at = None if request.lifetime else now + timedelta(days=request.days or 30)
        payload: dict[str, Any] = {
            "active": True,
            "is_premium": True,
            "entitlement": "lifetime" if request.lifetime else "premium",
            "provider": "admin_mobile",
            "product_id": "sirra_premium_lifetime" if request.lifetime else "admin_premium_grant",
            "started_at": now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "lifetime": request.lifetime,
            "admin_reason": request.reason,
            "admin_uid": admin.uid,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    else:
        payload = {
            "active": False,
            "is_premium": False,
            "entitlement": "free",
            "provider": "admin_mobile",
            "expires_at": now.isoformat(),
            "lifetime": False,
            "admin_reason": request.reason,
            "admin_uid": admin.uid,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
    ref.set(payload, merge=True)
    _audit(db, admin=admin, action="set_premium", target_uid=uid, details={"active": request.active, "days": request.days, "lifetime": request.lifetime, "reason": request.reason})
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise AppError(error_code="ADMIN_USER_NOT_FOUND", user_message="Kullanıcı bulunamadı.", developer_message=uid, status_code=404)
    return _user_item(db, user_doc, include_auth=True)


@router.post("/users/{uid}/credits", response_model=AdminUserItem)
async def admin_set_credits(
    uid: str,
    request: CreditAdminRequest,
    admin: CurrentUser = Depends(require_admin_user),
) -> AdminUserItem:
    from firebase_admin import firestore

    db = _firestore_client()
    ref = db.collection("monetization").document(uid)
    transaction = db.transaction()

    @firestore.transactional
    def apply(tx):
        snapshot = ref.get(transaction=tx)
        data = snapshot.to_dict() if snapshot.exists else {}
        current = max(0, int((data or {}).get("credits") or 0))
        next_value = request.absolute if request.absolute is not None else current + int(request.delta or 0)
        next_value = max(0, min(100000, int(next_value)))
        tx.set(
            ref,
            {
                "credits": next_value,
                "credits_updated_at": firestore.SERVER_TIMESTAMP,
                "last_access_kind": "admin_credit_change",
                "admin_reason": request.reason,
                "admin_uid": admin.uid,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        return next_value

    next_value = apply(transaction)
    _audit(db, admin=admin, action="set_credits", target_uid=uid, details={"delta": request.delta, "absolute": request.absolute, "result": next_value, "reason": request.reason})
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise AppError(error_code="ADMIN_USER_NOT_FOUND", user_message="Kullanıcı bulunamadı.", developer_message=uid, status_code=404)
    return _user_item(db, user_doc, include_auth=True)


@router.post("/users/{uid}/notify")
async def admin_notify_user(
    uid: str,
    request: NotificationAdminRequest,
    admin: CurrentUser = Depends(require_admin_user),
) -> dict[str, Any]:
    sent = await notify_admin_message(user_id=uid, title=request.title, body=request.body, route=request.route)
    db = _firestore_client()
    _audit(db, admin=admin, action="send_notification", target_uid=uid, details={"title": request.title, "route": request.route, "sent": sent})
    return {"status": "sent" if sent else "no_registered_device", "sent": sent}


@router.post("/users/{uid}/account", response_model=AdminUserItem)
async def admin_set_account(
    uid: str,
    request: AccountAdminRequest,
    admin: CurrentUser = Depends(require_admin_user),
) -> AdminUserItem:
    from firebase_admin import auth, firestore

    if uid == admin.uid and not request.enabled:
        raise AppError(
            error_code="ADMIN_SELF_DISABLE_FORBIDDEN",
            user_message="Kendi admin hesabını mobil panelden devre dışı bırakamazsın.",
            developer_message=f"Admin attempted self-disable: {uid}",
            status_code=400,
        )

    db = _firestore_client()
    try:
        auth.update_user(uid, disabled=not request.enabled)
        if not request.enabled:
            auth.revoke_refresh_tokens(uid)
    except Exception as exc:
        raise AppError(
            error_code="ADMIN_ACCOUNT_UPDATE_FAILED",
            user_message="Hesap durumu güncellenemedi.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc
    db.collection("users").document(uid).set(
        {
            "account_disabled": not request.enabled,
            "admin_reason": request.reason,
            "admin_uid": admin.uid,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    _audit(db, admin=admin, action="set_account_enabled", target_uid=uid, details={"enabled": request.enabled, "reason": request.reason})
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise AppError(error_code="ADMIN_USER_NOT_FOUND", user_message="Kullanıcı bulunamadı.", developer_message=uid, status_code=404)
    return _user_item(db, user_doc, include_auth=True)
