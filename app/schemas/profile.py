from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    user_id: str | None = None
    display_name: str
    email: str | None = None
    birth_date: str | None = None
    birth_date_display: str | None = None
    birth_time: str | None = None
    birth_place: str | None = None
    zodiac_sign: str | None = None
    zodiac_label: str | None = None
    rising_sign: str | None = None
    moon_sign: str | None = None
    relationship_status: str | None = None
    main_interest: str | None = Field(default=None, description="love, career, money, family, future")
    notification_opt_in: bool = True
    selfie_path: str | None = None
    selfie_consent_accepted: bool = False
    selfie_persona_tags: list[str] = Field(default_factory=list)
    addressing_preference: str | None = None
    is_premium: bool = False
    premium_until: str | None = None
