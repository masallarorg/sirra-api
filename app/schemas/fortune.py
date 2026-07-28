from typing import Literal

from pydantic import BaseModel, Field


class FortuneAccessState(BaseModel):
    credits: int
    charged_credits: int = 0
    access_kind: str = "unknown"
    premium_daily_used: int = 0
    premium_used: int = 0
    premium_daily_limit: int = 5
    premium_daily_remaining: int = 0
    premium_daily_exhausted: bool = False
    standard_free_daily_used: int = 0
    free_used: int = 0
    daily_date: str = ""
    is_premium: bool = False
    user_message: str | None = None
    authoritative_daily_state: bool = True
    daily_reset_applied: bool = False
    daily_reset_timezone: str = "Europe/Istanbul"
    daily_reset_rule: str = "Her gün 00:01 Türkiye saatinde yenilenir."



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




class FollowUpQuestion(BaseModel):
    question: str
    mode: str = "chat"


class PersonalInsight(BaseModel):
    title: str
    text: str


class ShareCard(BaseModel):
    title: str
    message: str
    accent: str = "gold"


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
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    personal_insights: list[PersonalInsight] = Field(default_factory=list)
    story_cards: list[ShareCard] = Field(default_factory=list)
    daily_ritual_prompt: str = ""


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
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    personal_insights: list[PersonalInsight] = Field(default_factory=list)
    story_cards: list[ShareCard] = Field(default_factory=list)
    daily_ritual_prompt: str = ""


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
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    personal_insights: list[PersonalInsight] = Field(default_factory=list)
    story_cards: list[ShareCard] = Field(default_factory=list)
    daily_ritual_prompt: str = ""


class GenericFortuneResponse(BaseModel):
    fortune_id: str
    status: str
    result: GenericFortuneResult
    access: FortuneAccessState | None = None



class FortuneFeedbackRequest(BaseModel):
    status: Literal["realized", "partial", "not_realized", "unknown", "reported"] = "unknown"
    note: str = Field(default="", max_length=500)


class FortuneFeedbackResponse(BaseModel):
    status: str = "saved"
    fortune_id: str
    feedback_status: str
    trust_message: str = "Geri bildirimin kişisel içgörüleri ve içerik güvenliğini iyileştirmek için kullanılır."


class SirraCompassResponse(BaseModel):
    user_id: str
    summary_title: str
    trust_message: str
    daily_symbol: dict = Field(default_factory=dict)
    daily_message: str
    desire_signal: dict = Field(default_factory=dict)
    symbol_memory: list[dict] = Field(default_factory=list)
    secret_map: list[dict] = Field(default_factory=list)
    cross_connections: list[dict] = Field(default_factory=list)
    time_capsules: list[dict] = Field(default_factory=list)
    probability_map_30d: list[dict] = Field(default_factory=list)
    feedback_stats: dict = Field(default_factory=dict)
    daily_loop: list[dict] = Field(default_factory=list)
    next_best_actions: list[str] = Field(default_factory=list)
    generated_at: str
