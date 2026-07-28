import json
<<<<<<< HEAD
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo
=======
from datetime import UTC, datetime
from typing import Annotated
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.live_guide import LiveGuideRequest, LiveGuideResponse
<<<<<<< HEAD
from app.services.image_validation import prepare_openai_image
from app.services.monetization_guard import _firestore_client, _is_subscription_active
=======
from app.services.monetization_guard import _firestore_client, _is_subscription_active
from app.services.image_validation import prepare_openai_image
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
from app.services.openai_client import call_openai_responses, extract_output_text, image_data_url

router = APIRouter()

<<<<<<< HEAD
LIVE_GUIDE_DAILY_LIMIT = 10
_TURKEY_TZ = ZoneInfo("Europe/Istanbul")

=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

def _active_premium(user_id: str) -> bool:
    if settings.mock_ai and settings.allow_mock_auth:
        return True
    db = _firestore_client()
    sub_snap = db.collection("subscriptions").document(user_id).get()
<<<<<<< HEAD
    return _is_subscription_active(sub_snap.to_dict() if sub_snap.exists else None)


def _next_reset_iso() -> str:
    now = datetime.now(_TURKEY_TZ)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 1, tzinfo=_TURKEY_TZ).isoformat()


def _consume_daily_message(user_id: str, request_id: str) -> tuple[int, str, str | None]:
    """Consume one daily message with Firestore transaction + idempotency.

    The request id prevents a network retry from charging the same message
    twice. The document lives in users/{uid}/private_state so account deletion
    removes it with the rest of the user's private app state.
    """
    reset_at = _next_reset_iso()
    if settings.mock_ai and settings.allow_mock_auth:
        return LIVE_GUIDE_DAILY_LIMIT - 1, reset_at, None

    from firebase_admin import firestore

    db = _firestore_client()
    day_key = datetime.now(_TURKEY_TZ).strftime("%Y%m%d")
    ref = (
        db.collection("users")
        .document(user_id)
        .collection("private_state")
        .document(f"live_guide_{day_key}")
    )
    transaction = db.transaction()

    @firestore.transactional
    def consume(txn):
        snapshot = ref.get(transaction=txn)
        data = snapshot.to_dict() if snapshot.exists else {}
        used = int((data or {}).get("used") or 0)
        request_ids = [str(item) for item in ((data or {}).get("request_ids") or []) if str(item).strip()]
        responses = (data or {}).get("responses") if isinstance((data or {}).get("responses"), dict) else {}
        if request_id in request_ids:
            cached = str((responses or {}).get(request_id) or "").strip() or None
            return max(0, LIVE_GUIDE_DAILY_LIMIT - used), cached
        if used >= LIVE_GUIDE_DAILY_LIMIT:
            raise AppError(
                error_code="LIVE_GUIDE_DAILY_LIMIT",
                user_message="Bugünkü Canlı Rehber mesaj hakkın doldu. Hakların gece 00:01'de yenilenir.",
                developer_message=f"uid={user_id} day={day_key}",
                status_code=429,
            )
        new_used = used + 1
        request_ids = (request_ids + [request_id])[-32:]
        txn.set(
            ref,
            {
                "user_id": user_id,
                "day_key": day_key,
                "used": new_used,
                "limit": LIVE_GUIDE_DAILY_LIMIT,
                "request_ids": request_ids,
                "updated_at": datetime.now(_TURKEY_TZ),
                "reset_at": reset_at,
            },
            merge=True,
        )
        return max(0, LIVE_GUIDE_DAILY_LIMIT - new_used), None

    remaining, cached_reply = consume(transaction)
    return remaining, reset_at, cached_reply


def _store_request_reply(user_id: str, request_id: str, reply: str) -> None:
    if settings.mock_ai and settings.allow_mock_auth:
        return

    from firebase_admin import firestore

    db = _firestore_client()
    day_key = datetime.now(_TURKEY_TZ).strftime("%Y%m%d")
    ref = (
        db.collection("users")
        .document(user_id)
        .collection("private_state")
        .document(f"live_guide_{day_key}")
    )
    transaction = db.transaction()

    @firestore.transactional
    def store(txn):
        snapshot = ref.get(transaction=txn)
        if not snapshot.exists:
            return
        data = snapshot.to_dict() or {}
        request_ids = [str(item) for item in (data.get("request_ids") or []) if str(item).strip()][-32:]
        if request_id not in request_ids:
            return
        previous = data.get("responses") if isinstance(data.get("responses"), dict) else {}
        responses = {
            key: str(previous[key])[:5000]
            for key in request_ids
            if key in previous and str(previous[key]).strip()
        }
        responses[request_id] = reply[:5000]
        txn.set(
            ref,
            {"responses": responses, "updated_at": datetime.now(_TURKEY_TZ)},
            merge=True,
        )

    store(transaction)
=======
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
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041


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
<<<<<<< HEAD
            user_message="Mesaj bilgisi okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc

=======
            user_message="Mesaj bilgisi okunamadi. Lutfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    image_bytes = None
    if selfie is not None:
        image_bytes = prepare_openai_image(
            await selfie.read(),
            error_prefix="LIVE_GUIDE_SELFIE",
            user_message="Selfie fotoğrafı okunamadı. Lütfen daha net bir fotoğrafla tekrar dene.",
            min_bytes=512,
        ).bytes
<<<<<<< HEAD

    messages_remaining, reset_at, cached_reply = _consume_daily_message(
        current_user.uid, request.request_id
    )
    if cached_reply:
        return LiveGuideResponse(
            reply=cached_reply,
            messages_remaining=messages_remaining,
            conversation_id=request.conversation_id,
            request_id=request.request_id,
            reset_at=reset_at,
        )

    reply = await _generate_reply(current_user.uid, request, image_bytes)
    _store_request_reply(current_user.uid, request.request_id, reply)
    return LiveGuideResponse(
        reply=reply,
        messages_remaining=messages_remaining,
        conversation_id=request.conversation_id,
        request_id=request.request_id,
        reset_at=reset_at,
    )
=======
    reply = await _generate_reply(current_user.uid, request, image_bytes)
    return LiveGuideResponse(reply=reply, messages_remaining=9)
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041


async def _generate_reply(user_id: str, request: LiveGuideRequest, image_bytes: bytes | None) -> str:
    if settings.mock_ai or not settings.openai_api_key:
        return _fallback_reply(request)

    rules = {
        "user_id_hint": user_id[-6:],
        "profile": request.profile,
<<<<<<< HEAD
        "guide_style": request.guide_style,
        "persona_tags": request.persona_tags,
        "selfie_added": bool(image_bytes),
        "policy": [
            "Türkçe cevap ver.",
            "Kendini insan danışman gibi tanıtma; AI destekli kişisel rehber olduğunu saklama.",
            "Kimlik, yaş, etnik köken, sağlık veya kesin cinsiyet tahmini yapma.",
            "Selfie varsa yalnızca ifade tonu, bakış enerjisi ve sembolik persona için kullan.",
            "Kesin kader garantisi verme; olasılık ve sezgisel yorum dili kullan.",
            "Kullanıcının mesajındaki dominant işareti, gizli gerilimi ve yakın dönemdeki olası dönüm noktasını birbirine bağla.",
            "Zamanlama gerekiyorsa kesin tarih değil 3-10 gün, 2-4 hafta veya bir sonraki ay döngüsü gibi geniş bir pencere kullan.",
            "Yanıt sesli de dinlenebileceği için doğal Türkçe, temiz noktalama ve kısa-orta uzunlukta cümleler kullan.",
            "Korkutucu, bağımlılık yaratan, manipülatif veya ödeme baskısı kuran dil kullanma.",
            "Yanıtı 2-4 kısa paragraf ve gerektiğinde tek bir takip sorusuyla sınırla.",
        ],
    }

    history_input = [
        {"role": item.role, "content": [{"type": "input_text", "text": item.text}]}
        for item in request.history[-10:]
    ]
    content: list[dict] = [
        {
            "type": "input_text",
            "text": json.dumps({"message": request.message, "context": rules}, ensure_ascii=False),
        }
    ]
    if image_bytes and len(image_bytes) > 512:
        content.append({"type": "input_image", "image_url": image_data_url(image_bytes)})

    payload = {
        "model": settings.openai_model,
        "instructions": (
            "Sen Canlı Rehber adlı AI destekli kişisel fal ve astroloji rehberisin. "
            "Sakin, profesyonel, şeffaf ve duygusal açıdan güvenli bir dille konuş. "
            "Tonun yetişkin, rafine ve gizemli olsun; fakat belirsizlikten korku veya bağımlılık üretme. "
            "Önce kullanıcının asıl sorusunu yansıt, sonra sembolik işareti ve olası yakın dönem gelişmesini bağla. "
            "Tıbbi, hukuki veya finansal profesyonel tavsiye verme."
        ),
        "input": [*history_input, {"role": "user", "content": content}],
=======
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
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    }
    try:
        response_json = await call_openai_responses(
            payload,
            error_code="OPENAI_LIVE_GUIDE",
            user_message="Canlı Rehber yanıtı hazırlanırken sorun oluştu. Lütfen tekrar dene.",
<<<<<<< HEAD
            timeout_seconds=55.0,
        )
        return _extract_text(response_json) or _fallback_reply(request)
    except AppError:
        return _fallback_reply(request)
=======
            timeout_seconds=60.0,
        )
        return _extract_text(response_json) or _fallback_reply(request)
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    except Exception:
        return _fallback_reply(request)


def _extract_text(data: dict) -> str:
    try:
        return extract_output_text(data, empty_error_code="OPENAI_LIVE_GUIDE_EMPTY").strip()
    except AppError:
        return ""


def _fallback_reply(request: LiveGuideRequest) -> str:
<<<<<<< HEAD
    style = {
        "yumusak": "yumuşak ve duygusal",
        "net": "kısa ve net",
        "mistik": "detaylı ve mistik",
        "dengeli": "dengeli ve sakin",
    }.get(request.guide_style, "dengeli ve sakin")
    selfie_line = (
        " Selfie yalnızca ifade tonunu sembolik olarak kişiselleştirmeme yardımcı oluyor."
        if request.selfie_added
        else " Selfie eklemeden de profilindeki bilgilerle ilerleyebilirim."
    )
    return (
        f"Mesajındaki ana tema, beklediğin cevap ile kendi iç sesin arasında kalman. {style.capitalize()} bir okumada, "
        "bugün netleştirmen gereken şey tek bir kişinin ne düşündüğünden çok, bu belirsizliğin sende hangi ihtiyacı uyandırdığı gibi görünüyor."
        f"{selfie_line} Bunu aşk, iş veya yakın gelecek başlığında biraz daha açmamı ister misin?"
=======
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
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
    )
