from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header

from app.core.config import settings
from app.core.errors import AppError


@dataclass(frozen=True)
class CurrentUser:
    uid: str
    email: str | None = None
    name: str | None = None
    claims: dict | None = None
    device_id: str | None = None


def _mock_user(reason: str = "mock_auth_enabled") -> CurrentUser:
    return CurrentUser(
        uid="dev_user",
        email="dev@example.com",
        name="Dev User",
        claims={"mock": True, "reason": reason},
    )


@lru_cache(maxsize=1)
def _firebase_ready() -> bool:
    try:
        import firebase_admin
        from firebase_admin import credentials
    except Exception as exc:
        if settings.allow_mock_auth:
            return False
        raise AppError(
            error_code="FIREBASE_ADMIN_PACKAGE_MISSING",
            user_message="Oturum dogrulama servisi hazir degil. Lutfen daha sonra tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc

    if firebase_admin._apps:
        return True

    try:
        if settings.firebase_credentials_path:
            cred = credentials.Certificate(settings.firebase_credentials_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
        return True
    except Exception as exc:
        if settings.allow_mock_auth:
            return False
        raise AppError(
            error_code="FIREBASE_ADMIN_NOT_CONFIGURED",
            user_message="Oturum dogrulama servisi hazir degil. Lutfen daha sonra tekrar dene.",
            developer_message=str(exc),
            status_code=503,
            retryable=True,
        ) from exc


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        if settings.allow_mock_auth:
            return None
        raise AppError(
            error_code="AUTH_TOKEN_MISSING",
            user_message="Bu islem icin giris yapman gerekiyor.",
            developer_message="Missing Authorization Bearer token",
            status_code=401,
        )
    return authorization.split(" ", 1)[1].strip()


async def require_current_user(authorization: str | None = Header(default=None), x_device_install_id: str | None = Header(default=None)) -> CurrentUser:
    token = _extract_bearer(authorization)

    # Local development mode: allows Flutter screens and backend endpoints to be tested
    # without Firebase Admin service-account setup. Never use ALLOW_MOCK_AUTH=true in production.
    if token is None and settings.allow_mock_auth:
        return CurrentUser(uid='dev_user', email='dev@example.com', name='Dev User', claims={'mock': True, 'reason': 'missing_authorization_allowed_in_dev'}, device_id=x_device_install_id)

    if settings.allow_mock_auth and token and token.startswith("dev_"):
        return CurrentUser(uid=token.replace("dev_", "", 1), email="dev@example.com", claims={"mock": True}, device_id=x_device_install_id)

    firebase_ready = _firebase_ready()
    if not firebase_ready and settings.allow_mock_auth:
        return CurrentUser(uid='dev_user', email='dev@example.com', name='Dev User', claims={'mock': True, 'reason': 'firebase_admin_not_configured_allowed_in_dev'}, device_id=x_device_install_id)

    try:
        from firebase_admin import auth
        decoded = auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        if settings.allow_mock_auth:
            return CurrentUser(
                uid="dev_user",
                email="dev@example.com",
                name="Dev User",
                claims={"mock": True, "reason": "firebase_token_verify_failed_allowed_in_dev", "detail": str(exc)},
                device_id=x_device_install_id,
            )
        raise AppError(
            error_code="AUTH_TOKEN_INVALID",
            user_message="Oturum suresi dolmus olabilir. Lutfen tekrar giris yap.",
            developer_message=str(exc),
            status_code=401,
        ) from exc

    uid = decoded.get("uid") or decoded.get("sub")
    if not uid:
        raise AppError(
            error_code="AUTH_UID_MISSING",
            user_message="Oturum bilgisi okunamadi. Lutfen tekrar giris yap.",
            developer_message="Firebase token has no uid",
            status_code=401,
        )

    return CurrentUser(
        uid=uid,
        email=decoded.get("email"),
        name=decoded.get("name"),
        claims=decoded,
        device_id=x_device_install_id,
    )
