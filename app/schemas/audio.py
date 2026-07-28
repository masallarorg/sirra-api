from pydantic import BaseModel, Field


class NarrationRequest(BaseModel):
    text: str = Field(min_length=8, max_length=6000)
    title: str = Field(default="Fal yorumun", max_length=120)
    voice_style: str = Field(default="mystic", max_length=32)


class NarrationResponse(BaseModel):
    audio_base64: str
    mime_type: str = "audio/mpeg"
    voice_name: str
    character_count: int
