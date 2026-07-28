from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, require_current_user
from app.schemas.audio import NarrationRequest, NarrationResponse
from app.services.voice_narration import synthesize_fortune_narration

router = APIRouter()


@router.post("/narrate", response_model=NarrationResponse)
async def narrate_fortune(
    request: NarrationRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> NarrationResponse:
    del current_user
    audio, voice = await synthesize_fortune_narration(text=request.text, title=request.title)
    return NarrationResponse(
        audio_base64=audio,
        voice_name=voice,
        character_count=len(request.text),
    )
