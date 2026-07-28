from fastapi import APIRouter, Depends

from app.core.rate_limit import check_rate_limit
from app.core.security import CurrentUser, require_current_user
from app.schemas.astrology import DailyHoroscope, DailyHoroscopeRequest, EnergyCard
from app.services.openai_astrology import generate_daily_horoscope, normalize_sign

router = APIRouter()


@router.post("/daily", response_model=DailyHoroscope)
async def daily_horoscope(
    request: DailyHoroscopeRequest,
    current_user: CurrentUser = Depends(require_current_user),
) -> DailyHoroscope:
    check_rate_limit(current_user, "daily_horoscope")
    return await generate_daily_horoscope(request=request, user=current_user)


@router.get("/daily/{sign}", response_model=DailyHoroscope)
async def daily_horoscope_compat(
    sign: str,
    current_user: CurrentUser = Depends(require_current_user),
) -> DailyHoroscope:
    check_rate_limit(current_user, "daily_horoscope")
    normalized = normalize_sign(sign)
    request = DailyHoroscopeRequest(sign=normalized)
    return await generate_daily_horoscope(request=request, user=current_user)


@router.get("/energy-card", response_model=EnergyCard)
async def daily_energy_card(current_user: CurrentUser = Depends(require_current_user)) -> EnergyCard:
    check_rate_limit(current_user, "energy_card")
    return EnergyCard(
        card_key="mountain_path",
        title="Dagin Yolu",
        summary="Bugun kolay degil ama yukselis getiren bir yol aciliyor.",
        animation_key="card_flip_mountain",
        premium_teaser="Bu kartin ask ve para tarafindaki gizli detayi premium analizde acilir.",
    )
