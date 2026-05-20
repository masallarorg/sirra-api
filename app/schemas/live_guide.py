from pydantic import BaseModel, Field


class LiveGuideRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
    profile: dict = Field(default_factory=dict)
    energy_preference: str = "notr"
    persona_tags: list[str] = Field(default_factory=list)
    selfie_added: bool = False


class LiveGuideResponse(BaseModel):
    reply: str
    messages_remaining: int = 10
