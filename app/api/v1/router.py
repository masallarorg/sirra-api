from fastapi import APIRouter

from app.api.v1.routes import admin, astrology, fortunes, profile, subscriptions, live_guide, audio

api_router = APIRouter()
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(astrology.router, prefix="/astrology", tags=["astrology"])
api_router.include_router(fortunes.router, prefix="/fortunes", tags=["fortunes"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
api_router.include_router(live_guide.router, prefix="/live-guide", tags=["live-guide"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
