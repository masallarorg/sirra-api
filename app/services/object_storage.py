from __future__ import annotations

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
    provider: str = "r2"


def storage_enabled() -> bool:
    return settings.storage_provider.strip().lower() == "r2" and settings.r2_configured


def storage_status() -> dict[str, Any]:
    return {
        "provider": "r2" if settings.storage_provider.strip().lower() == "r2" else settings.storage_provider,
        "enabled": storage_enabled(),
        "bucket_configured": bool(settings.r2_bucket_name),
        "public_url_configured": bool(settings.r2_public_base_url),
    }


def _safe_part(value: str, fallback: str) -> str:
    clean = _SAFE_KEY_PART.sub("_", str(value or "").strip()).strip("._-")
    return clean[:120] or fallback


def _client():
    if not storage_enabled():
        raise RuntimeError("Cloudflare R2 is not configured")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def _object_url(client, key: str) -> str:
    if settings.r2_public_base_url:
        return f"{settings.r2_public_base_url.rstrip('/')}/{key}"
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=max(300, min(int(settings.r2_presigned_url_ttl_seconds), 604800)),
    )


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
    """Persist app-owned media in Cloudflare R2.

    Storage is intentionally best-effort. AI generation and the user-facing
    result must still work when R2 is temporarily unavailable or not yet
    configured.
    """
    if not storage_enabled() or not data:
        return None
    uid = _safe_part(user_id, "user")
    folder = _safe_part(category, "media")
    name = _safe_part(object_id, "object")
    ext = _safe_part(extension.lower().lstrip("."), "bin")
    key = f"users/{uid}/{folder}/{name}.{ext}"
    client = _client()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl=cache_control,
        Metadata={"owner_uid": uid, "category": folder},
    )
    return StoredObject(key=key, url=_object_url(client, key))


def delete_prefix(prefix: str) -> int:
    if not storage_enabled():
        return 0
    clean_prefix = str(prefix or "").lstrip("/")
    if not clean_prefix:
        return 0
    client = _client()
    deleted = 0
    continuation: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": settings.r2_bucket_name,
            "Prefix": clean_prefix,
            "MaxKeys": 1000,
        }
        if continuation:
            kwargs["ContinuationToken"] = continuation
        response = client.list_objects_v2(**kwargs)
        objects = [{"Key": item["Key"]} for item in response.get("Contents", []) if item.get("Key")]
        if objects:
            result = client.delete_objects(
                Bucket=settings.r2_bucket_name,
                Delete={"Objects": objects, "Quiet": True},
            )
            deleted += len(objects) - len(result.get("Errors", []))
        if not response.get("IsTruncated"):
            break
        continuation = response.get("NextContinuationToken")
        if not continuation:
            break
    return deleted


def delete_user_media(user_id: str) -> int:
    uid = _safe_part(user_id, "user")
    try:
        return delete_prefix(f"users/{uid}/")
    except Exception as exc:
        logger.warning("R2 user media cleanup skipped uid=%s: %s", uid, exc)
        return 0
