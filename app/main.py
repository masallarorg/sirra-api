from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.2.1",
        description="Sırra - Fal ve Astroloji API",
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts_list,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "X-Device-Install-Id"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    async def root() -> dict:
        return {"status": "ok", "name": settings.app_name, "docs": "/docs", "api": "/api/v1"}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
