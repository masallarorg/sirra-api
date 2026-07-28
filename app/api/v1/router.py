from fastapi import APIRouter

<<<<<<< HEAD
from app.api.v1.routes import astrology, fortunes, profile, subscriptions, live_guide, audio
=======
from app.api.v1.routes import astrology, fortunes, profile, subscriptions, live_guide
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041

api_router = APIRouter()
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(astrology.router, prefix="/astrology", tags=["astrology"])
api_router.include_router(fortunes.router, prefix="/fortunes", tags=["fortunes"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
api_router.include_router(live_guide.router, prefix="/live-guide", tags=["live-guide"])
<<<<<<< HEAD
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
=======
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
