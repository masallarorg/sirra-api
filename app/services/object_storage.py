from __future__ import annotations

import io
import logging
import re
from urllib.parse import quote

import httpx
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_KEY_PART = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class StoredObject:
    key: str
    url: str
    provider: str = "cloudinary"


def _active_provider() -> str:
    requested = str(settings.storage_provider or "").strip().lower()
    # Migration guard: an old STORAGE_PROVIDER=r2 variable must not keep the
    # removed R2 adapter active after valid Cloudinary credentials are added.
    if settings.cloudinary_configured:
        return "cloudinary"
    return requested or "cloudinary"


def storage_enabled() -> bool:
    return _active_provider() == "cloudinary" and settings.cloudinary_configured


def storage_status() -> dict[str, Any]:
    credentials = settings.cloudinary_credentials
    unsigned = settings.cloudinary_unsigned_configured
    cloud_name = settings.cloudinary_cloud_name_value
    return {
        "provider": _active_provider(),
        "enabled": storage_enabled(),
        "cloud_name_configured": bool(cloud_name),
        "credentials_configured": bool(credentials),
        "unsigned_preset_configured": unsigned,
        "credential_source": settings.cloudinary_credential_source,
        "api_key_suffix": credentials[1][-4:] if credentials and len(credentials[1]) >= 4 else None,
        "upload_auth": "unsigned_upload_preset" if unsigned else "sdk_signature_with_basic_auth_fallback",
        "private_delivery": not unsigned,
    }


def _safe_part(value: str, fallback: str) -> str:
    clean = _SAFE_KEY_PART.sub("_", str(value or "").strip()).strip("._-")
    return clean[:120] or fallback


def _folder_root() -> str:
    return _safe_part(settings.cloudinary_folder_root, "sirra")


def _configure_cloudinary() -> None:
    credentials = settings.cloudinary_credentials
    if not credentials:
        raise RuntimeError("Cloudinary signed credentials are not configured")
    cloud_name, api_key, api_secret = credentials
    import cloudinary

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def _cloudinary_error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error.get("message"))[:500]
            if error:
                return str(error)[:500]
    except Exception:
        pass
    return response.text[:500]


def safe_storage_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    credentials = settings.cloudinary_credentials
    if credentials:
        _, api_key, api_secret = credentials
        if api_secret:
            text = text.replace(api_secret, "[REDACTED_CLOUDINARY_SECRET]")
        if api_key:
            text = text.replace(api_key, f"***{api_key[-4:]}")
    return text[:900]


def _upload_with_unsigned_preset(
    *,
    cloud_name: str,
    upload_preset: str,
    filename: str,
    data: bytes,
    content_type: str,
    public_id: str,
    uid: str,
    folder: str,
) -> dict[str, Any]:
    endpoint = f"https://api.cloudinary.com/v1_1/{quote(cloud_name, safe='')}/image/upload"
    form = {
        "upload_preset": upload_preset,
        "public_id": public_id,
        "tags": f"sirra,sirra_user_{uid},sirra_category_{folder}",
        "context": f"owner_uid={uid}|category={folder}|content_type={content_type}",
    }
    with httpx.Client(timeout=httpx.Timeout(75.0, connect=12.0)) as client:
        response = client.post(
            endpoint,
            data=form,
            files={"file": (filename, data, content_type)},
        )
    if response.status_code >= 400:
        header_error = response.headers.get("X-Cld-Error", "").strip()
        body_error = _cloudinary_error_text(response)
        detail = header_error or body_error
        raise RuntimeError(
            f"Cloudinary unsigned upload failed status={response.status_code} error={detail}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("public_id"):
        raise RuntimeError("Cloudinary unsigned upload returned an invalid response")
    return payload


def _upload_with_basic_auth(
    *,
    cloud_name: str,
    api_key: str,
    api_secret: str,
    filename: str,
    data: bytes,
    content_type: str,
    public_id: str,
    extension: str,
    uid: str,
    folder: str,
) -> dict[str, Any]:
    endpoint = f"https://api.cloudinary.com/v1_1/{quote(cloud_name, safe='')}/image/upload"
    form = {
        "type": "authenticated",
        "public_id": public_id,
        "overwrite": "true",
        "unique_filename": "false",
        "use_filename": "false",
        "invalidate": "true",
        "format": extension,
        "tags": f"sirra,sirra_user_{uid},sirra_category_{folder}",
        "context": f"owner_uid={uid}|category={folder}|content_type={content_type}",
    }
    with httpx.Client(timeout=httpx.Timeout(75.0, connect=12.0)) as client:
        response = client.post(
            endpoint,
            auth=httpx.BasicAuth(api_key, api_secret),
            data=form,
            files={"file": (filename, data, content_type)},
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Cloudinary Basic Auth upload failed status={response.status_code} error={_cloudinary_error_text(response)}"
        )
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("public_id"):
        raise RuntimeError("Cloudinary Basic Auth upload returned an invalid response")
    return payload


def _is_authorization_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(token in text for token in ("authorizationrequired", "unauthorized", "invalid signature", "api key", "401"))


def _private_delivery_url(*, public_id: str, image_format: str, version: int | str | None) -> str:
    _configure_cloudinary()
    from cloudinary.utils import cloudinary_url

    options: dict[str, Any] = {
        "resource_type": "image",
        "type": "authenticated",
        "secure": True,
        "sign_url": True,
        "format": image_format,
    }
    if version is not None:
        options["version"] = version
    url, _ = cloudinary_url(public_id, **options)
    return str(url)


def upload_user_bytes(
    *,
    user_id: str,
    category: str,
    object_id: str,
    data: bytes,
    content_type: str,
    extension: str,
    cache_control: str = "private, max-age=3600",
) -> StoredObject | None:
    """Persist app-owned generated media in Cloudinary.

    The upload is server-authenticated and stored with the ``authenticated``
    delivery type. The returned URL is signed by the backend. Storage remains
    best-effort: when Cloudinary is unavailable, the existing base64 response
    fallback keeps the generated fortune result usable.
    """
    del cache_control  # Cloudinary delivery policy is controlled by its CDN.
    if not storage_enabled() or not data:
        return None

    uid = _safe_part(user_id, "user")
    folder = _safe_part(category, "media")
    name = _safe_part(object_id, "object")
    ext = _safe_part(extension.lower().lstrip("."), "jpg")
    public_id = f"{_folder_root()}/users/{uid}/{folder}/{name}"

    if settings.cloudinary_unsigned_configured:
        response = _upload_with_unsigned_preset(
            cloud_name=settings.cloudinary_cloud_name_value,
            upload_preset=settings.cloudinary_unsigned_preset_value,
            filename=f"{name}.{ext}",
            data=data,
            content_type=content_type,
            public_id=public_id,
            uid=uid,
            folder=folder,
        )
        stored_public_id = str(response.get("public_id") or public_id)
        secure_url = str(response.get("secure_url") or "").strip()
        if not secure_url:
            raise RuntimeError("Cloudinary unsigned upload response has no secure_url")
        return StoredObject(key=stored_public_id, url=secure_url)

    _configure_cloudinary()
    from cloudinary import uploader

    payload = io.BytesIO(data)
    payload.name = f"{name}.{ext}"
    try:
        response = uploader.upload(
            payload,
            resource_type="image",
            type="authenticated",
            public_id=public_id,
            overwrite=True,
            unique_filename=False,
            use_filename=False,
            invalidate=True,
            format=ext,
            tags=["sirra", f"sirra_user_{uid}", f"sirra_category_{folder}"],
            context={"owner_uid": uid, "category": folder, "content_type": content_type},
        )
    except Exception as exc:
        if not _is_authorization_error(exc):
            raise
        cloud_name, api_key, api_secret = settings.cloudinary_credentials or ("", "", "")
        logger.warning(
            "Cloudinary SDK authentication was rejected; retrying with server-side Basic Auth cloud=%s key_suffix=%s",
            cloud_name,
            api_key[-4:] if len(api_key) >= 4 else "unknown",
        )
        response = _upload_with_basic_auth(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            filename=f"{name}.{ext}",
            data=data,
            content_type=content_type,
            public_id=public_id,
            extension=ext,
            uid=uid,
            folder=folder,
        )

    stored_public_id = str(response.get("public_id") or public_id)
    stored_format = str(response.get("format") or ext)
    signed_url = _private_delivery_url(
        public_id=stored_public_id,
        image_format=stored_format,
        version=response.get("version"),
    )
    return StoredObject(key=stored_public_id, url=signed_url)


def delete_prefix(prefix: str) -> int:
    if not storage_enabled() or not settings.cloudinary_credentials:
        return 0
    clean_prefix = str(prefix or "").lstrip("/")
    if not clean_prefix:
        return 0

    _configure_cloudinary()
    from cloudinary import api

    deleted = 0
    next_cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "resource_type": "image",
            "type": "authenticated",
            "invalidate": True,
        }
        if next_cursor:
            kwargs["next_cursor"] = next_cursor
        result = api.delete_resources_by_prefix(clean_prefix, **kwargs)
        deleted_map = result.get("deleted", {}) if isinstance(result, dict) else {}
        if isinstance(deleted_map, dict):
            deleted += sum(1 for value in deleted_map.values() if str(value).lower() in {"deleted", "ok"})
        next_cursor = str(result.get("next_cursor") or "") if isinstance(result, dict) else ""
        if not next_cursor:
            break
    return deleted


def delete_user_media(user_id: str) -> int:
    uid = _safe_part(user_id, "user")
    prefix = f"{_folder_root()}/users/{uid}/"
    try:
        return delete_prefix(prefix)
    except Exception as exc:
        logger.warning("Cloudinary user media cleanup skipped uid=%s: %s", uid, exc)
        return 0
