"""
Centralized domain exceptions + FastAPI handlers.

ASSESSMENT: every public failure mode maps to a structured JSON body
with a stable `code` field so clients and tests can assert deterministically.
"""
from __future__ import annotations

from typing import Any
import logging
from fastapi.encoders import jsonable_encoder

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class AppError(Exception):
    """Base application error with HTTP status and machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "app_error",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", *, code: str = "not_found"):
        super().__init__(message, code=code, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str = "Conflict", *, code: str = "conflict"):
        super().__init__(message, code=code, status_code=status.HTTP_409_CONFLICT)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded", *, code: str = "rate_limited"):
        super().__init__(message, code=code, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


class ServiceUnavailableError(AppError):
    def __init__(self, message: str = "Service unavailable", *, code: str = "unavailable"):
        super().__init__(message, code=code, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


class ErrorBody(BaseModel):
    error: str
    code: str
    details: Any = None


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorBody(error=exc.message, code=exc.code, details=exc.details).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=ErrorBody(
                error="Validation failed",
                code="validation_error",
                details=jsonable_encoder(exc.errors(), custom_encoder={ValueError: str}),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled request error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorBody(
                error="Internal server error",
                code="internal_error",
                details=None,
            ).model_dump(),
        )
