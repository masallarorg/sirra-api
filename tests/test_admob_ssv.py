import base64
import time
from urllib.parse import quote

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import settings
from app.core.errors import AppError
from app.services import admob_ssv


def _signed_query(private_key, *, ad_unit: str, amount: int = 2, timestamp_ms: int | None = None) -> tuple[str, str]:
    timestamp_ms = timestamp_ms or int(time.time() * 1000)
    transaction_id = "txn/replay-safe:123"
    signed = (
        "ad_network=5450213213286189855"
        f"&ad_unit={quote(ad_unit, safe='')}"
        "&custom_data=session_abc123"
        f"&reward_amount={amount}"
        "&reward_item=credit"
        f"&timestamp={timestamp_ms}"
        f"&transaction_id={quote(transaction_id, safe='')}"
        "&user_id=user_42"
    )
    signature = private_key.sign(signed.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{signed}&signature={quote(encoded, safe='')}&key_id=77", transaction_id


@pytest.mark.asyncio
async def test_verifies_exact_admob_signed_query(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    async def fake_keys():
        return {77: pem}

    monkeypatch.setattr(admob_ssv, "_fetch_verifier_keys", fake_keys)
    monkeypatch.setattr(settings, "admob_rewarded_ad_unit_id", "ca-app-pub-1/2")
    raw_query, transaction_id = _signed_query(private_key, ad_unit="ca-app-pub-1/2")

    callback = await admob_ssv.verify_reward_callback(raw_query)

    assert callback.user_id == "user_42"
    assert callback.custom_data == "session_abc123"
    assert callback.reward_amount == 2
    assert callback.transaction_id == transaction_id


@pytest.mark.asyncio
async def test_rejects_tampered_reward_amount(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    async def fake_keys():
        return {77: pem}

    monkeypatch.setattr(admob_ssv, "_fetch_verifier_keys", fake_keys)
    monkeypatch.setattr(settings, "admob_rewarded_ad_unit_id", "ca-app-pub-1/2")
    raw_query, _ = _signed_query(private_key, ad_unit="ca-app-pub-1/2")
    tampered = raw_query.replace("reward_amount=2", "reward_amount=200")

    with pytest.raises(AppError) as error:
        await admob_ssv.verify_reward_callback(tampered)
    assert error.value.error_code == "ADMOB_SSV_SIGNATURE_MISMATCH"


def test_split_signed_query_preserves_original_escaping():
    raw = "custom_data=a%2Bb%20c&user_id=u&signature=YWJjZA&key_id=9"
    signed, signature, key_id = admob_ssv.split_signed_query(raw)
    assert signed == b"custom_data=a%2Bb%20c&user_id=u"
    assert signature == "YWJjZA"
    assert key_id == 9


def test_split_signed_query_rejects_missing_signature():
    with pytest.raises(AppError) as error:
        admob_ssv.split_signed_query("user_id=u&key_id=9")
    assert error.value.error_code == "ADMOB_SSV_SIGNATURE_MISSING"
