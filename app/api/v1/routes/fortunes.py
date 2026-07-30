import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.fortune import CoffeeFortuneResponse, DreamFortuneRequest, DreamFortuneResponse, FortuneFeedbackRequest, FortuneFeedbackResponse, GenericFortuneRequest, GenericFortuneResponse, SirraCompassResponse
from app.services.openai_fortune import generate_coffee_fortune, generate_dream_fortune, generate_generic_fortune, generate_palm_fortune, generate_soulmate_fortune
from app.services.monetization_guard import commit_fortune_access, reserve_fortune_access, refund_fortune_access
from app.services.symbol_linker import find_cross_fortune_connections
from app.services.image_validation import prepare_openai_image
from app.services.personal_memory import enrich_profile_with_memory, store_fortune_memory
from app.services.push_notifications import notify_fortune_ready
from app.services.sirra_compass import build_sirra_compass, record_fortune_feedback

router = APIRouter()




@router.get("/sirra-compass", response_model=SirraCompassResponse)
async def sirra_compass(current_user: CurrentUser = Depends(require_current_user)) -> SirraCompassResponse:
    payload = await build_sirra_compass(current_user.uid)
    return SirraCompassResponse.model_validate(payload)


@router.post("/{fortune_id}/feedback", response_model=FortuneFeedbackResponse)
async def fortune_feedback(
    fortune_id: str,
    request: FortuneFeedbackRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> FortuneFeedbackResponse:
    payload = await record_fortune_feedback(
        user_id=current_user.uid,
        fortune_id=fortune_id,
        status=request.status,
        note=request.note,
    )
    return FortuneFeedbackResponse.model_validate(payload)

@router.post("/generate", response_model=GenericFortuneResponse)
async def generate_fortune(request: GenericFortuneRequest, current_user: CurrentUser = Depends(require_current_user)) -> GenericFortuneResponse:
    request.profile = request.profile or {}
    request.profile["focus"] = request.focus
    request.profile = await enrich_profile_with_memory(user_id=current_user.uid, profile=request.profile, focus=request.focus)
    reservation = await reserve_fortune_access(user_id=current_user.uid, fortune_type=request.type_id, device_id=current_user.device_id)
    try:
        result = await generate_generic_fortune(request)
        result.cross_fortune_connections = await find_cross_fortune_connections(
            user_id=current_user.uid,
            new_symbols=result.symbols,
        )
        await _save_generic_history(user_id=current_user.uid, result=result, request=request)
        await store_fortune_memory(user_id=current_user.uid, fortune_id=result.fortune_id, fortune_type=result.type, symbols=result.symbols, summary=result.summary, focus=request.focus)
        await notify_fortune_ready(user_id=current_user.uid, fortune_id=result.fortune_id, title="Fal yorumun")
        await commit_fortune_access(reservation)
        return GenericFortuneResponse(fortune_id=result.fortune_id, status="completed", result=result, access=reservation.access_state)
    except Exception:
        await refund_fortune_access(reservation)
        raise


@router.post("/coffee", response_model=CoffeeFortuneResponse)
async def coffee_fortune(
    images: Annotated[list[UploadFile], File()],
    profile_json: Annotated[str, Form()] = "{}",
    focus: Annotated[str, Form()] = "Genel enerji",
    current_user: CurrentUser = Depends(require_current_user),
) -> CoffeeFortuneResponse:
    if not 1 <= len(images) <= 3:
        raise AppError(
            error_code="COFFEE_IMAGE_COUNT_INVALID",
            user_message="Kahve falı için 1 ile 3 arasında fotoğraf yüklemelisin.",
            developer_message=f"Received {len(images)} images",
            status_code=422,
        )

    try:
        profile = json.loads(profile_json or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="PROFILE_JSON_INVALID",
            user_message="Profil bilgileri okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc

    profile["focus"] = focus or profile.get("focus") or "Genel enerji"
    profile = await enrich_profile_with_memory(user_id=current_user.uid, profile=profile, focus=profile["focus"])

    image_bytes: list[bytes] = []
    for image in images:
        data = await image.read()
        prepared = prepare_openai_image(
            data,
            error_prefix="COFFEE_IMAGE",
            user_message="Fotoğraf çok küçük veya okunamadı. Lütfen fincanı daha net çekip tekrar yükle.",
        )
        image_bytes.append(prepared.bytes)

    reservation = await reserve_fortune_access(user_id=current_user.uid, fortune_type="coffee", device_id=current_user.device_id)
    try:
        result = await generate_coffee_fortune(user_id=current_user.uid, profile=profile, image_bytes=image_bytes)
        result.cross_fortune_connections = await find_cross_fortune_connections(
            user_id=current_user.uid,
            new_symbols=[symbol.symbol for symbol in result.detected_symbols],
        )
        await _save_coffee_history(user_id=current_user.uid, result=result, profile=profile)
        await store_fortune_memory(user_id=current_user.uid, fortune_id=result.fortune_id, fortune_type="coffee", symbols=[symbol.symbol for symbol in result.detected_symbols], summary=result.summary, focus=profile.get("focus"))
        await notify_fortune_ready(user_id=current_user.uid, fortune_id=result.fortune_id, title="Kahve falın")
        await commit_fortune_access(reservation)

        return CoffeeFortuneResponse(
            fortune_id=result.fortune_id,
            status="completed",
            result=result,
            access=reservation.access_state,
        )
    except Exception:
        await refund_fortune_access(reservation)
        raise



@router.post("/palm", response_model=GenericFortuneResponse)
async def palm_fortune(
    right_palm_image: Annotated[UploadFile, File()],
    left_palm_image: Annotated[UploadFile, File()],
    profile_json: Annotated[str, Form()] = "{}",
    focus: Annotated[str, Form()] = "Genel enerji",
    hand: Annotated[str, Form()] = "Sağ ve sol el",
    question: Annotated[str, Form()] = "",
    current_user: CurrentUser = Depends(require_current_user),
) -> GenericFortuneResponse:
    right_data = prepare_openai_image(
        await right_palm_image.read(),
        error_prefix="PALM_RIGHT_IMAGE",
        user_message="Sağ el fotoğrafı okunamadı. Lütfen avuç içini daha net çekip tekrar dene.",
    ).bytes
    left_data = prepare_openai_image(
        await left_palm_image.read(),
        error_prefix="PALM_LEFT_IMAGE",
        user_message="Sol el fotoğrafı okunamadı. Lütfen avuç içini daha net çekip tekrar dene.",
    ).bytes
    try:
        profile = json.loads(profile_json or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="PROFILE_JSON_INVALID",
            user_message="Profil bilgileri okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc
    profile["focus"] = focus
    profile["hand"] = hand
    profile["question"] = question
    profile["right_palm_uploaded"] = True
    profile["left_palm_uploaded"] = True
    profile = await enrich_profile_with_memory(user_id=current_user.uid, profile=profile, focus=focus)
    reservation = await reserve_fortune_access(user_id=current_user.uid, fortune_type="palm", device_id=current_user.device_id)
    try:
        result = await generate_palm_fortune(user_id=current_user.uid, profile=profile, right_image_bytes=right_data, left_image_bytes=left_data)
        result.cross_fortune_connections = await find_cross_fortune_connections(
            user_id=current_user.uid,
            new_symbols=result.symbols,
        )
        request = GenericFortuneRequest(
            type_id="palm",
            focus=focus,
            payload={"hand": hand, "question": question, "right_palm_photo_added": True, "left_palm_photo_added": True, "analysis_mode": "real_two_hand_palm_photo"},
            profile=profile,
        )
        await _save_generic_history(user_id=current_user.uid, result=result, request=request)
        await store_fortune_memory(user_id=current_user.uid, fortune_id=result.fortune_id, fortune_type=result.type, symbols=result.symbols, summary=result.summary, focus=focus)
        await notify_fortune_ready(user_id=current_user.uid, fortune_id=result.fortune_id, title="Fal yorumun")
        await commit_fortune_access(reservation)
        return GenericFortuneResponse(fortune_id=result.fortune_id, status="completed", result=result, access=reservation.access_state)
    except Exception:
        await refund_fortune_access(reservation)
        raise


@router.post("/soulmate", response_model=GenericFortuneResponse)
async def soulmate_fortune(
    selfie: Annotated[UploadFile, File()],
    profile_json: Annotated[str, Form()] = "{}",
    focus: Annotated[str, Form()] = "Aşk",
    theme: Annotated[str, Form()] = "Gizemli portre",
    current_user: CurrentUser = Depends(require_current_user),
) -> GenericFortuneResponse:
    data = prepare_openai_image(
        await selfie.read(),
        error_prefix="SOULMATE_SELFIE",
        user_message="Selfie fotoğrafı okunamadı. Lütfen daha net bir fotoğrafla tekrar dene.",
    ).bytes
    try:
        profile = json.loads(profile_json or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            error_code="PROFILE_JSON_INVALID",
            user_message="Profil bilgileri okunamadı. Lütfen tekrar dene.",
            developer_message=str(exc),
            status_code=422,
        ) from exc
    profile["focus"] = focus
    profile["theme"] = theme
    profile = await enrich_profile_with_memory(user_id=current_user.uid, profile=profile, focus=focus)
    reservation = await reserve_fortune_access(user_id=current_user.uid, fortune_type="soulmate", device_id=current_user.device_id)
    try:
        result = await generate_soulmate_fortune(user_id=current_user.uid, profile=profile, image_bytes=data)
        result.cross_fortune_connections = await find_cross_fortune_connections(
            user_id=current_user.uid,
            new_symbols=result.symbols,
        )
        request = GenericFortuneRequest(type_id="soulmate", focus=focus, payload={"theme": theme, "selfie_added": True}, profile=profile)
        await _save_generic_history(user_id=current_user.uid, result=result, request=request)
        await store_fortune_memory(user_id=current_user.uid, fortune_id=result.fortune_id, fortune_type=result.type, symbols=result.symbols, summary=result.summary, focus=focus)
        await notify_fortune_ready(user_id=current_user.uid, fortune_id=result.fortune_id, title="Fal yorumun")
        await commit_fortune_access(reservation)
        return GenericFortuneResponse(fortune_id=result.fortune_id, status="completed", result=result, access=reservation.access_state)
    except Exception:
        await refund_fortune_access(reservation)
        raise


@router.post("/dream", response_model=DreamFortuneResponse)
async def dream_fortune(request: DreamFortuneRequest, current_user: CurrentUser = Depends(require_current_user)) -> DreamFortuneResponse:
    request.user_id = current_user.uid
    request.profile = await enrich_profile_with_memory(user_id=current_user.uid, profile=request.profile or {}, focus="Rüya")
    reservation = await reserve_fortune_access(user_id=current_user.uid, fortune_type="dream", device_id=current_user.device_id)
    try:
        result = await generate_dream_fortune(request)
        result.cross_fortune_connections = await find_cross_fortune_connections(
            user_id=current_user.uid,
            new_symbols=result.symbols,
        )
        await store_fortune_memory(user_id=current_user.uid, fortune_id=result.fortune_id, fortune_type=result.type, symbols=result.symbols, summary=result.summary, focus="Rüya")
        await notify_fortune_ready(user_id=current_user.uid, fortune_id=result.fortune_id, title="Rüya yorumun")
        await commit_fortune_access(reservation)
        return DreamFortuneResponse(status="completed", result=result, access=reservation.access_state)
    except Exception:
        await refund_fortune_access(reservation)
        raise


async def _save_coffee_history(*, user_id: str, result, profile: dict) -> None:
    if settings.mock_ai or settings.allow_mock_auth:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                cred = credentials.Certificate(settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()

        db = firestore.client()
        now = datetime.now(UTC)
        payload = result.model_dump()
        db.collection("users").document(user_id).collection("fortunes").document(result.fortune_id).set(
            {
                "fortune_id": result.fortune_id,
                "type": "coffee",
                "created_at": now,
                "profile_snapshot": profile,
                "payload": payload,
                "symbols": [symbol.symbol for symbol in result.detected_symbols],
            },
            merge=True,
        )
    except Exception:
        # History save should never make a completed reading fail. Operational logs can be added later.
        return



async def _save_generic_history(*, user_id: str, result, request: GenericFortuneRequest) -> None:
    if settings.mock_ai or settings.allow_mock_auth:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            if settings.firebase_credentials_path:
                cred = credentials.Certificate(settings.firebase_credentials_path)
                firebase_admin.initialize_app(cred)
            else:
                firebase_admin.initialize_app()

        db = firestore.client()
        now = datetime.now(UTC)
        payload = result.model_dump()
        # Generated portrait bytes are returned to the current device and stored locally.
        # Never write multi-megabyte base64 image data into a Firestore history document.
        payload.pop("portrait_image_base64", None)
        db.collection("users").document(user_id).collection("fortunes").document(result.fortune_id).set(
            {
                "fortune_id": result.fortune_id,
                "type": result.type,
                "created_at": now,
                "profile_snapshot": request.profile,
                "request_payload": request.payload,
                "focus": request.focus,
                "payload": payload,
                "symbols": result.symbols,
            },
            merge=True,
        )
    except Exception:
        return
