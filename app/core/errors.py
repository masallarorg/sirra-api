from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uuid


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        user_message: str,
        developer_message: str = "",
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.user_message = user_message
        self.developer_message = developer_message
        self.status_code = status_code
        self.retryable = retryable


class ErrorResponse(BaseModel):
    error_code: str
    user_message: str
    developer_message: str
    retryable: bool
    correlation_id: str


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id", f"req_{uuid.uuid4().hex[:12]}")
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=exc.error_code,
                user_message=exc.user_message,
                developer_message=exc.developer_message,
                retryable=exc.retryable,
                correlation_id=correlation_id,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id", f"req_{uuid.uuid4().hex[:12]}")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error_code="INTERNAL_SERVER_ERROR",
                user_message="Beklenmeyen bir sorun oluştu. Lütfen tekrar dene.",
                developer_message=str(exc),
                retryable=True,
                correlation_id=correlation_id,
            ).model_dump(),
        )
