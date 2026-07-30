import asyncio

from fastapi import APIRouter, Depends

from app.core.errors import AppError
from app.core.security import CurrentUser, require_current_user
from app.schemas.audio import NarrationRequest, NarrationResponse
from app.services.monetization_guard import user_has_active_premium
from app.services.voice_narration import synthesize_fortune_narration

router = APIRouter()


@router.post("/narrate", response_model=NarrationResponse)
async def narrate_fortune(
    request: NarrationRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> NarrationResponse:
    premium = await asyncio.to_thread(user_has_active_premium, current_user.uid)
    if not premium:
        raise AppError(
            error_code="PREMIUM_NARRATION_REQUIRED",
            user_message="Sesli yorum yalnızca Premium üyelikte kullanılabilir.",
            developer_message=f"uid={current_user.uid} attempted narration without premium",
            status_code=403,
        )
    audio, voice = await synthesize_fortune_narration(text=request.text, title=request.title)
    return NarrationResponse(
        audio_base64=audio,
        voice_name=voice,
        character_count=len(request.text),
    )
