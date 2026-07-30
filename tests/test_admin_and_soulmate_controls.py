import base64

import pytest
from pydantic import ValidationError

from app.api.v1.routes.admin import CreditAdminRequest, PremiumAdminRequest, _is_admin_claim
from app.core.config import settings
from app.core.security import CurrentUser
from app.services import openai_client


def test_admin_claim_allows_explicit_admin_claim():
    user = CurrentUser(uid="admin-1", email="owner@example.com", claims={"admin": True})
    assert _is_admin_claim(user) is True


def test_credit_request_requires_exactly_one_mode():
    with pytest.raises(ValidationError):
        CreditAdminRequest(reason="test")
    with pytest.raises(ValidationError):
        CreditAdminRequest(delta=2, absolute=4, reason="test")
    assert CreditAdminRequest(delta=5, reason="test").delta == 5


def test_premium_request_requires_duration_for_timed_grant():
    with pytest.raises(ValidationError):
        PremiumAdminRequest(active=True, lifetime=False, days=None, reason="test")
    assert PremiumAdminRequest(active=True, lifetime=True, days=None, reason="test").lifetime is True


@pytest.mark.asyncio
async def test_soulmate_image_edit_returns_base64(monkeypatch):
    expected = base64.b64encode(b"jpeg-data").decode("ascii")

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"b64_json":"ok"}]}'
        headers = {}

        def json(self):
            return {"data": [{"b64_json": expected}]}

    class FakeClient:
        def __init__(self):
            self.kwargs = None

        async def post(self, *args, **kwargs):
            self.kwargs = (args, kwargs)
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(openai_client, "_get_client", lambda: fake)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    encoded, mime = await openai_client.call_openai_image_edit(
        image_bytes=b"input-image",
        prompt="fictional graphite portrait",
        error_code="TEST_IMAGE",
        user_message="test",
    )
    assert encoded == expected
    assert mime == "image/jpeg"
    assert fake.kwargs is not None
    assert fake.kwargs[0][0] == "/images/edits"
    assert fake.kwargs[1]["files"][0][0] == "image[]"

@pytest.mark.asyncio
async def test_soulmate_image_generation_does_not_send_customer_image(monkeypatch):
    expected = base64.b64encode(b"new-fictional-portrait").decode("ascii")

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"b64_json":"ok"}]}'
        headers = {}

        def json(self):
            return {"data": [{"b64_json": expected}]}

    class FakeClient:
        def __init__(self):
            self.kwargs = None

        async def post(self, *args, **kwargs):
            self.kwargs = (args, kwargs)
            return FakeResponse()

    fake = FakeClient()
    monkeypatch.setattr(openai_client, "_get_client", lambda: fake)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    encoded, mime = await openai_client.call_openai_image_generate(
        prompt="new fictional graphite partner portrait",
        error_code="TEST_IMAGE_GENERATE",
        user_message="test",
    )
    assert encoded == expected
    assert mime == "image/jpeg"
    assert fake.kwargs is not None
    assert fake.kwargs[0][0] == "/images/generations"
    assert "files" not in fake.kwargs[1]
    assert fake.kwargs[1]["json"]["n"] == 1
