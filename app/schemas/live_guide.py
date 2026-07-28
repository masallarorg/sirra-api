<<<<<<< HEAD
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LiveGuideHistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=1600)

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Geçmiş mesaj boş olamaz.")
        return clean
=======
from pydantic import BaseModel, Field
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041


class LiveGuideRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
<<<<<<< HEAD
    profile: dict[str, Any] = Field(default_factory=dict)
    guide_style: str = Field(default="dengeli", pattern="^(dengeli|yumusak|net|mistik)$")
    persona_tags: list[str] = Field(default_factory=list, max_length=12)
    selfie_added: bool = False
    request_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9_.:-]+$")
    conversation_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9_.:-]+$")
    history: list[LiveGuideHistoryItem] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def _clean_message(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Mesaj boş olamaz.")
        return clean

    @field_validator("persona_tags")
    @classmethod
    def _clean_persona_tags(cls, value: list[str]) -> list[str]:
        return [str(tag).strip()[:64] for tag in value if str(tag).strip()][:12]

    @field_validator("profile")
    @classmethod
    def _limit_profile(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "display_name",
            "zodiac_label",
            "rising_sign",
            "moon_sign",
            "birth_place",
            "relationship_status",
            "main_interest",
            "reading_tone",
            "addressing_preference",
            "automatic_personalization",
        }
        cleaned: dict[str, Any] = {}
        for key, raw in value.items():
            if key not in allowed:
                continue
            if isinstance(raw, bool):
                cleaned[key] = raw
                continue
            text = str(raw).strip()
            if text:
                cleaned[key] = text[:160]
        return cleaned
=======
    profile: dict = Field(default_factory=dict)
    energy_preference: str = "notr"
    persona_tags: list[str] = Field(default_factory=list)
    selfie_added: bool = False
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041


class LiveGuideResponse(BaseModel):
    reply: str
<<<<<<< HEAD
    messages_remaining: int = Field(default=10, ge=0, le=10)
    conversation_id: str
    request_id: str
    reset_at: str | None = None
=======
    messages_remaining: int = 10
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
