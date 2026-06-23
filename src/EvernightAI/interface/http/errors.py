from typing import cast

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from EvernightAI.core.error.base import (
    AuthorizationError,
    ConfigurationError,
    ConflictError,
    DependencyError,
    EvernightAIError,
    NotFoundError,
    RateLimitError,
    RequestError,
    RequestTimeoutError,
    ResponseError,
    StateError,
    UnsupportedError,
    ValidationError,
)
from EvernightAI.core.error.provider import ProviderUnavailableError


async def handle_evernight_error(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    error = cast(EvernightAIError, exc)
    return JSONResponse(
        status_code=status_code_for_error(error),
        content={
            "error": {
                "type": error.error_type,
                "message": str(error),
                "detail": error.detail,
            }
        },
    )


async def handle_request_validation_error(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    error = cast(RequestValidationError, exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "type": "ValidationError",
                "message": "Invalid request",
                "detail": jsonable_encoder(error.errors()),
            }
        },
    )


def status_code_for_error(exc: EvernightAIError) -> int:
    if isinstance(exc, NotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, (ValidationError, ConfigurationError, UnsupportedError)):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, AuthorizationError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, ConflictError):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, StateError):
        return status.HTTP_409_CONFLICT
    if isinstance(exc, RateLimitError):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(exc, RequestTimeoutError):
        return status.HTTP_504_GATEWAY_TIMEOUT
    if isinstance(exc, (ProviderUnavailableError, DependencyError)):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, (RequestError, ResponseError)):
        return status.HTTP_502_BAD_GATEWAY

    return status.HTTP_500_INTERNAL_SERVER_ERROR
