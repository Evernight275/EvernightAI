from typing import NoReturn

import httpx

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


def translate_httpx_provider_error(error: httpx.HTTPError) -> EvernightAIError:
    if isinstance(error, httpx.TimeoutException):
        return _wrap(ProviderRequestTimeoutError, error)
    if isinstance(error, httpx.NetworkError):
        return _wrap(ProviderUnavailableError, error)
    if isinstance(error, httpx.HTTPStatusError):
        return _translate_status_error(error)
    if isinstance(error, httpx.DecodingError):
        return _wrap(ProviderResponseError, error)

    return _wrap(ProviderRequestError, error)


def raise_httpx_provider_error(error: httpx.HTTPError) -> NoReturn:
    translated = translate_httpx_provider_error(error)
    raise translated from error


def _translate_status_error(error: httpx.HTTPStatusError) -> EvernightAIError:
    status_code = error.response.status_code

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
    text = str(error)
    if text:
        return text

    return error.__class__.__name__


def _detail_from(error: Exception) -> str | None:
    detail: list[str] = []

    response = getattr(error, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if status_code is not None:
            detail.append(f"status_code={status_code}")

        request_id = response.headers.get("x-request-id")
        if request_id:
            detail.append(f"request_id={request_id}")

        try:
            text = response.text
        except httpx.ResponseNotRead:
            text = ""
        if text:
            detail.append(f"body={text!r}")

    return "; ".join(detail) or None
