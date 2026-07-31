import base64

import pytest

from app.api.v1.routes.subscriptions import _reconcile_premium_access_state
from app.core.config import settings
from app.core.errors import AppError
from app.services import openai_fortune


class _Snapshot:
    def __init__(self, data):
        self._data = dict(data or {})
        self.exists = data is not None
        self.update_time = None

    def to_dict(self):
        return dict(self._data)


class _Document:
    def __init__(self, store, collection, document_id):
        self._store = store
        self._collection = collection
        self._document_id = document_id

    def get(self):
        data = self._store.get(self._collection, {}).get(self._document_id)
        return _Snapshot(data)

    def set(self, data, merge=False):
        collection = self._store.setdefault(self._collection, {})
        if merge:
            existing = dict(collection.get(self._document_id) or {})
            existing.update(data)
            collection[self._document_id] = existing
        else:
            collection[self._document_id] = dict(data)


class _Collection:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def document(self, document_id):
        return _Document(self._store, self._name, document_id)


class _Db:
    def __init__(self, store):
        self.store = store

    def collection(self, name):
        return _Collection(self.store, name)


def test_subscription_access_state_no_name_error_and_preserves_lifetime_premium():
    db = _Db(
        {
            "subscriptions": {
                "user-1": {
                    "active": True,
                    "entitlement": "premium",
                    "lifetime": True,
                    "provider": "admin",
                }
            },
            "monetization": {
                "user-1": {
                    "credits": 12,
                    "daily_date": "",
                    "premium_daily_used": 0,
                }
            },
        }
    )

    access = _reconcile_premium_access_state(db, "user-1")

    assert access["is_premium"] is True
    assert access["lifetime"] is True
    assert access["lifetime_premium"] is True
    assert access["premium_daily_limit"] == 5
    assert access["premium_daily_remaining"] == 5
    assert access["authoritative_subscription_state"] is True


@pytest.mark.asyncio
async def test_soulmate_returns_local_portrait_when_both_remote_stages_fail(monkeypatch):
    async def fail_responses(*args, **kwargs):
        raise AppError(
            error_code="VISION_TEMPORARY",
            user_message="temporary",
            status_code=502,
            retryable=True,
        )

    async def fail_image(*args, **kwargs):
        raise AppError(
            error_code="IMAGE_TEMPORARY",
            user_message="temporary",
            status_code=502,
            retryable=True,
        )

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fail_responses)
    monkeypatch.setattr(openai_fortune, "call_openai_image_generate", fail_image)

    result = await openai_fortune.generate_soulmate_fortune(
        user_id="user-local-fallback",
        profile={"focus": "Aşk", "theme": "Gizemli portre"},
        image_bytes=b"valid-selfie-placeholder",
    )

    assert result.type == "soulmate"
    assert result.portrait_mime_type == "image/jpeg"
    assert result.portrait_image_base64
    decoded = base64.b64decode(result.portrait_image_base64)
    assert decoded.startswith(b"\xff\xd8\xff")
    assert len(decoded) > 10_000
    assert len(result.sections) >= 4
