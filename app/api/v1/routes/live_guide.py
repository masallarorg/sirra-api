import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.live_guide import LiveGuideRequest, LiveGuideResponse
from app.services.monetization_guard import _firestore_client, _is_subscription_active
from app.services.image_validation import prepare_openai_image
from app.services.openai_client import call_openai_responses, extract_output_text, image_data_url

router = APIRouter()


def _active_premium(user_id: str) -> bool:
    if settings.mock_ai and settings.allow_mock_auth:
        return True
    db = _firestore_client()
    sub_snap = db.collection("subscriptions").document(user_id).get()
    if _is_subscription_active(sub_snap.to_dict() if sub_snap.exists else None):
        return True

    # Transition fallback: users/{uid} is only accepted when it also carries a
    # valid expiry. A bare is_premium=true flag is not enough; otherwise old
    # manual edits become endless premium.
    user_snap = db.collection("users").document(user_id).get()
    user_data = user_snap.to_dict() if user_snap.exists else {}
    if _is_subscription_active(user_data):
        return True
    entitlement = str(user_data.get("entitlement") or "").lower()
    return entitlement == "pro" and _is_subscription_active({**user_data, "entitlement": "premium"})


@router.post("/chat", response_model=LiveGuideResponse)
async def live_guide_chat(
    payload_json: Annotated[str, Form()],
    selfie: Annotated[UploadFile | None, File()] = None,
    current_user: CurrentUser = Depends(require_current_user),
) -> LiveGuideResponse:
    if not _active_premium(current_user.uid):
        raise AppError(
            error_code="LIVE_GUIDE_PRO_REQUIRED",
            user_message="Canlı Rehber sadece Pro/Premium üyelere açıktır.",
            developer_message=f"uid={current_user.uid}",
            status_code=402,
        )
    try:
        request = LiveGuideRequest.model_validate(json.loads(payload_json or "{}"))
    except Exception as exc:
        raise AppError(
            error_code="LIVE_GUIDE_PAYLOAD_INVALID",
            user_message="Mesaj bilgisi okunamadi. Lutfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc
    image_bytes = None
    if selfie is not None:
        image_bytes = prepare_openai_image(
            await selfie.read(),
            error_prefix="LIVE_GUIDE_SELFIE",
            user_message="Selfie fotoğrafı okunamadı. Lütfen daha net bir fotoğrafla tekrar dene.",
            min_bytes=512,
        ).bytes
    reply = await _generate_reply(current_user.uid, request, image_bytes)
    return LiveGuideResponse(reply=reply, messages_remaining=9)


async def _generate_reply(user_id: str, request: LiveGuideRequest, image_bytes: bytes | None) -> str:
    if settings.mock_ai or not settings.openai_api_key:
        return _fallback_reply(request)

    rules = {
        "user_id_hint": user_id[-6:],
        "profile": request.profile,
        "energy_preference": request.energy_preference,
        "persona_tags": request.persona_tags,
        "selfie_added": bool(image_bytes),
        "policy": [
            "Turkce cevap ver.",
            "Kimlik, yas, etnik koken, saglik veya kesin cinsiyet tahmini yapma.",
            "Selfie varsa yalnizca ifade tonu, bakis enerjisi ve sembolik persona icin kullan.",
            "Kesin kader garantisi verme; olasilik ve sezgisel yorum dili kullan.",
            "Cevap merak uyandirsin, ama korkutucu veya manipulative olmasin.",
            "Kullanici yapay zeka kelimesini sormadikca teknik sistem aciklamasi yapma.",
        ],
    }
    content: list[dict] = [
        {"type": "input_text", "text": json.dumps({"message": request.message, "context": rules}, ensure_ascii=False)}
    ]
    if image_bytes and len(image_bytes) > 512:
        content.append({"type": "input_image", "image_url": image_data_url(image_bytes)})
    payload = {
        "model": settings.openai_model,
        "instructions": "Sen Sirra Canli Rehberisin. Kisa, derin, sezgisel ve profesyonel fal/astroloji sohbeti yap. Kendini insan falci olarak tanitma. Hassas ozellik tahmini yapma.",
        "input": [{"role": "user", "content": content}],
    }
    try:
        response_json = await call_openai_responses(
            payload,
            error_code="OPENAI_LIVE_GUIDE",
            user_message="Canlı Rehber yanıtı hazırlanırken sorun oluştu. Lütfen tekrar dene.",
            timeout_seconds=60.0,
        )
        return _extract_text(response_json) or _fallback_reply(request)
    except Exception:
        return _fallback_reply(request)


def _extract_text(data: dict) -> str:
    try:
        return extract_output_text(data, empty_error_code="OPENAI_LIVE_GUIDE_EMPTY").strip()
    except AppError:
        return ""


def _fallback_reply(request: LiveGuideRequest) -> str:
    energy = {
        "kadin": "daha yumusak, sezgisel ve duygusal bir ton",
        "erkek": "daha net, guclu ve karar odakli bir ton",
        "notr": "dengeli ve tarafsiz bir ton",
    }.get(request.energy_preference, "dengeli bir ton")
    selfie_line = " Selfie tonun, bakis enerjisi ve ifade izini daha kisisel okumama yardim ediyor." if request.selfie_added else " Selfie eklemeden de profil ve ruh halin uzerinden ilerleyebilirim."
    return (
        f"Mesajinda dikkatimi ceken ana iz, bekledigin cevapla kendi ic sesin arasinda kalman. {energy} ile bakinca, "
        "bugun netlestirmen gereken konu tek bir kisiden cok, o kisinin sende uyandirdigi beklenti gibi gorunuyor."
        f"{selfie_line} Istersen simdi bunu ask, is veya para tarafinda daha derin acabilirim."
    )
