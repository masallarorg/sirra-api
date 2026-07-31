from pydantic import BaseModel, Field, field_validator


class AstrologyDeriveRequest(BaseModel):
    birth_date: str
    birth_time: str
    birth_place: str | None = None
    birth_latitude: float = Field(ge=-90, le=90)
    birth_longitude: float = Field(ge=-180, le=180)
    birth_timezone: str = "Europe/Istanbul"

    @field_validator("birth_date", "birth_time", "birth_timezone")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Bu alan boş bırakılamaz.")
        return clean


class AstrologyDeriveResponse(BaseModel):
    sun_sign: str
    moon_sign: str
    rising_sign: str
    calculation_quality: str
    birth_timezone: str
    birth_latitude: float
    birth_longitude: float


class UserProfile(BaseModel):
    user_id: str | None = None
    display_name: str
    email: str | None = None
    birth_date: str | None = None
    birth_date_display: str | None = None
    birth_time: str | None = None
    birth_place: str | None = None
    birth_latitude: float | None = Field(default=None, ge=-90, le=90)
    birth_longitude: float | None = Field(default=None, ge=-180, le=180)
    birth_timezone: str | None = None
    zodiac_sign: str | None = None
    zodiac_label: str | None = None
    rising_sign: str | None = None
    moon_sign: str | None = None
    astrology_auto_fill: bool = True
    astrology_calculation_quality: str | None = None
    relationship_status: str | None = None
    main_interest: str | None = Field(default=None, description="love, career, money, family, future")
    reading_tone: str | None = None
    smart_suggestions: bool = True
    automatic_personalization: bool = True
    fast_mode: bool = True
    data_saver: bool = False
    notification_opt_in: bool = False
    selfie_path: str | None = None
    selfie_consent_accepted: bool = False
    selfie_persona_tags: list[str] = Field(default_factory=list)
    addressing_preference: str | None = None
    gender_identity: str | None = None
    soulmate_portrait_preference: str | None = None
    is_premium: bool = False
    premium_until: str | None = None
