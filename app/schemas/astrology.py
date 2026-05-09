from pydantic import BaseModel, Field


class DailyHoroscopeRequest(BaseModel):
    sign: str = Field(min_length=2, max_length=24)
    locale: str = Field(default="tr-TR", max_length=12)
    focus: str | None = Field(default=None, max_length=40)
    relationship_status: str | None = Field(default=None, max_length=40)


class HoroscopeScore(BaseModel):
    label: str
    score: int = Field(ge=0, le=100)
    text: str


class HoroscopeTimelineItem(BaseModel):
    time: str
    title: str
    detail: str


class SymbolConnection(BaseModel):
    symbol: str
    meaning: str
    related_area: str


class DailyHoroscope(BaseModel):
    sign: str
    date: str
    title: str
    summary: str
    full_reading: str
    energy_score: int = Field(ge=0, le=100)
    love: HoroscopeScore
    career: HoroscopeScore
    money: HoroscopeScore
    health: HoroscopeScore
    lucky_color: str
    lucky_number: int = Field(ge=1, le=99)
    compatibility: list[str]
    key_times: list[HoroscopeTimelineItem]
    do_list: list[str]
    avoid_list: list[str]
    ritual: str
    affirmation: str
    symbol_connections: list[SymbolConnection]
    premium_teasers: list[str]
    animation_key: str
    generated_by: str = "backend_openai"
    cached: bool = False


class EnergyCard(BaseModel):
    card_key: str
    title: str
    summary: str
    animation_key: str
    premium_teaser: str
