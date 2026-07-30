from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.services.openai_client import close_openai_client


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.8.3",
        description="Sırra - Fal ve Astroloji API",
    )

    app.add_middleware(GZipMiddleware, minimum_size=900)

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts_list,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials and settings.cors_origins_list != ["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "X-Device-Install-Id"],
    )

    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    async def root() -> dict:
        return {"status": "ok", "name": settings.app_name, "docs": "/docs", "api": "/api/v1"}

    @app.head("/")
    async def root_head() -> None:
        return None

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "environment": settings.environment, "version": "1.8.3"}

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        await close_openai_client()

    return app


app = create_app()
