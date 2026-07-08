from typing import NoReturn

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ContentFilterFinishReasonError,
    InternalServerError,
    InvalidWebhookSignatureError,
    LengthFinishReasonError,
    NotFoundError,
    OAuthError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
    WebSocketConnectionClosedError,
    WebSocketQueueFullError,
)

from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.error.provider import (
    ProviderAuthorizationError,
    ProviderConflictError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderRequestTimeoutError,
    ProviderResponseError,
    ProviderUnavailableError,
)

OpenAICompatibleError = OpenAIError | InvalidWebhookSignatureError


def translate_openai_compatible_error(
    error: OpenAICompatibleError,
) -> EvernightAIError:
    """Translate OpenAI SDK errors into EvernightAI provider errors."""
    if isinstance(error, APITimeoutError):
        return _wrap(ProviderRequestTimeoutError, error)
    if isinstance(error, (APIConnectionError, WebSocketConnectionClosedError)):
        return _wrap(ProviderUnavailableError, error)
    if isinstance(error, WebSocketQueueFullError):
        return _wrap(ProviderRequestError, error)

    if isinstance(
        error,
        (
            AuthenticationError,
            PermissionDeniedError,
            OAuthError,
            InvalidWebhookSignatureError,
        ),
    ):
        return _wrap(ProviderAuthorizationError, error)
    if isinstance(error, RateLimitError):
        return _wrap(ProviderRateLimitError, error)
    if isinstance(error, ConflictError):
        return _wrap(ProviderConflictError, error)
    if isinstance(error, NotFoundError):
        return _wrap(ProviderNotFoundError, error)
    if isinstance(error, (BadRequestError, UnprocessableEntityError)):
        return _wrap(ProviderRequestError, error)
    if isinstance(error, InternalServerError):
        return _wrap(ProviderUnavailableError, error)

    if isinstance(error, APIResponseValidationError):
        return _wrap(ProviderResponseError, error)
    if isinstance(error, APIStatusError):
        return _translate_status_error(error)
    if isinstance(error, (LengthFinishReasonError, ContentFilterFinishReasonError)):
        return _wrap(ProviderResponseError, error)
    if isinstance(error, APIError):
        return _wrap(ProviderRequestError, error)

    return _wrap(ProviderRequestError, error)


def raise_openai_compatible_error(error: OpenAICompatibleError) -> NoReturn:
    translated = translate_openai_compatible_error(error)
    raise translated from error


def _translate_status_error(error: APIStatusError) -> EvernightAIError:
    status_code = error.status_code

    if status_code in {401, 403}:
        return _wrap(ProviderAuthorizationError, error)
    if status_code == 404:
        return _wrap(ProviderNotFoundError, error)
    if status_code == 409:
        return _wrap(ProviderConflictError, error)
    if status_code == 429:
        return _wrap(ProviderRateLimitError, error)
    if status_code >= 500:
        return _wrap(ProviderUnavailableError, error)
    if 400 <= status_code < 500:
        return _wrap(ProviderRequestError, error)

    return _wrap(ProviderResponseError, error)


def _wrap(
    error_type: type[EvernightAIError],
    error: Exception,
) -> EvernightAIError:
    return error_type(
        _message_from(error),
        detail=_detail_from(error),
        cause=error,
    )


def _message_from(error: Exception) -> str:
    message = getattr(error, "message", None)
    if message:
        return str(message)

    text = str(error)
    if text:
        return text

    return error.__class__.__name__


def _detail_from(error: Exception) -> str | None:
    detail: list[str] = []

    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        detail.append(f"status_code={status_code}")

    request_id = getattr(error, "request_id", None)
    if request_id:
        detail.append(f"request_id={request_id}")

    body = getattr(error, "body", None)
    if body is not None:
        detail.append(f"body={body!r}")

    return "; ".join(detail) or None
