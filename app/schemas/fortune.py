from pydantic import BaseModel, Field


class FortuneAccessState(BaseModel):
    credits: int
    charged_credits: int = 0
    access_kind: str = "unknown"
    premium_daily_used: int = 0
    premium_daily_limit: int = 5
    premium_daily_remaining: int = 0
    standard_free_daily_used: int = 0
    daily_date: str = ""
    is_premium: bool = False



class ImageRegion(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)


class SymbolAnimation(BaseModel):
    type: str
    asset_key: str
    duration_ms: int = 1800


class DetectedSymbol(BaseModel):
    symbol: str
    display_name: str
    confidence: float = Field(ge=0, le=1)
    meaning: str
    image_region: ImageRegion
    image_index: int = Field(default=0, ge=0, le=2)
    animation: SymbolAnimation


class FortuneSection(BaseModel):
    score: int = Field(ge=0, le=100)
    text: str


class PremiumLock(BaseModel):
    key: str
    title: str
    teaser: str


class CrossFortuneConnection(BaseModel):
    message: str
    related_fortune_id: str | None = None
    related_symbols: list[str] = Field(default_factory=list)


class CoffeeFortuneResult(BaseModel):
    fortune_id: str
    type: str = "coffee"
    title: str
    summary: str
    detected_symbols: list[DetectedSymbol]
    love: FortuneSection
    career: FortuneSection
    money: FortuneSection
    family: FortuneSection
    cross_fortune_connections: list[CrossFortuneConnection] = Field(default_factory=list)
    premium_locks: list[PremiumLock]


class CoffeeFortuneResponse(BaseModel):
    fortune_id: str
    status: str
    result: CoffeeFortuneResult
    access: FortuneAccessState | None = None


class DreamFortuneRequest(BaseModel):
    user_id: str
    dream_text: str
    profile: dict = Field(default_factory=dict)


class DreamFortuneResult(BaseModel):
    fortune_id: str
    type: str = "dream"
    title: str
    summary: str
    symbols: list[str]
    interpretation: str
    cross_fortune_connections: list[CrossFortuneConnection] = Field(default_factory=list)
    premium_locks: list[PremiumLock]


class DreamFortuneResponse(BaseModel):
    status: str
    result: DreamFortuneResult
    access: dict | None = None



class FortuneDetailBlock(BaseModel):
    title: str
    text: str


class GenericFortuneRequest(BaseModel):
    type_id: str
    focus: str = "Genel enerji"
    payload: dict = Field(default_factory=dict)
    profile: dict = Field(default_factory=dict)


class GenericFortuneResult(BaseModel):
    fortune_id: str
    type: str
    title: str
    summary: str
    primary_message: str
    sections: list[FortuneDetailBlock]
    symbols: list[str] = Field(default_factory=list)
    cross_fortune_connections: list[CrossFortuneConnection] = Field(default_factory=list)
    premium_locks: list[PremiumLock]


class GenericFortuneResponse(BaseModel):
    fortune_id: str
    status: str
    result: GenericFortuneResult
    access: FortuneAccessState | None = None
