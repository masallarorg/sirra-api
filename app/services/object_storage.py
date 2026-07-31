from __future__ import annotations

import io
import logging
import re
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
    return {
        "provider": _active_provider(),
        "enabled": storage_enabled(),
        "cloud_name_configured": bool(credentials and credentials[0]),
        "credentials_configured": bool(credentials),
        "private_delivery": True,
    }


def _safe_part(value: str, fallback: str) -> str:
    clean = _SAFE_KEY_PART.sub("_", str(value or "").strip()).strip("._-")
    return clean[:120] or fallback


def _folder_root() -> str:
    return _safe_part(settings.cloudinary_folder_root, "sirra")


def _configure_cloudinary() -> None:
    if not storage_enabled():
        raise RuntimeError("Cloudinary is not configured")
    cloud_name, api_key, api_secret = settings.cloudinary_credentials or ("", "", "")
    import cloudinary

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


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

    _configure_cloudinary()
    from cloudinary import uploader

    payload = io.BytesIO(data)
    payload.name = f"{name}.{ext}"
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

    stored_public_id = str(response.get("public_id") or public_id)
    stored_format = str(response.get("format") or ext)
    signed_url = _private_delivery_url(
        public_id=stored_public_id,
        image_format=stored_format,
        version=response.get("version"),
    )
    return StoredObject(key=stored_public_id, url=signed_url)


def delete_prefix(prefix: str) -> int:
    if not storage_enabled():
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
