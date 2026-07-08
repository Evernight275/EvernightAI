from typing import Any, cast

import httpx
import pytest
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
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
    WebSocketConnectionClosedError,
    WebSocketQueueFullError,
)
from openai.types.chat import ChatCompletion

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
from EvernightAI.infra.adapters.providers.openai_compatible.errors import (
    OpenAICompatibleError,
    raise_openai_compatible_error,
    translate_openai_compatible_error,
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.test/v1/chat/completions")


def _response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers={"x-request-id": "req_test"},
        request=_request(),
    )


def _chat_completion() -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "finish_reason": "length",
                    "index": 0,
                    "message": {"role": "assistant", "content": "truncated"},
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion",
    )


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (APITimeoutError(request=_request()), ProviderRequestTimeoutError),
        (
            APIConnectionError(message="network down", request=_request()),
            ProviderUnavailableError,
        ),
        (
            WebSocketConnectionClosedError("socket closed", unsent_messages=[]),
            ProviderUnavailableError,
        ),
        (
            WebSocketQueueFullError("queue full"),
            ProviderRequestError,
        ),
        (
            AuthenticationError("bad key", response=_response(401), body=None),
            ProviderAuthorizationError,
        ),
        (
            PermissionDeniedError("forbidden", response=_response(403), body=None),
            ProviderAuthorizationError,
        ),
        (
            OAuthError(response=_response(401), body={"error": "oauth"}),
            ProviderAuthorizationError,
        ),
        (
            InvalidWebhookSignatureError("bad webhook"),
            ProviderAuthorizationError,
        ),
        (
            RateLimitError("too many requests", response=_response(429), body=None),
            ProviderRateLimitError,
        ),
        (
            ConflictError("conflict", response=_response(409), body=None),
            ProviderConflictError,
        ),
        (
            NotFoundError("missing model", response=_response(404), body=None),
            ProviderNotFoundError,
        ),
        (
            BadRequestError("invalid request", response=_response(400), body=None),
            ProviderRequestError,
        ),
        (
            UnprocessableEntityError(
                "unprocessable",
                response=_response(422),
                body=None,
            ),
            ProviderRequestError,
        ),
        (
            InternalServerError("upstream down", response=_response(500), body=None),
            ProviderUnavailableError,
        ),
        (
            APIResponseValidationError(
                response=_response(200),
                body={"invalid": "response"},
                message="invalid response",
            ),
            ProviderResponseError,
        ),
        (
            LengthFinishReasonError(completion=_chat_completion()),
            ProviderResponseError,
        ),
        (
            ContentFilterFinishReasonError(),
            ProviderResponseError,
        ),
        (
            APIError("generic api error", request=_request(), body=None),
            ProviderRequestError,
        ),
    ],
)
def test_translates_openai_errors_to_provider_errors(
    error: OpenAICompatibleError,
    expected_type: type[Exception],
) -> None:
    translated = translate_openai_compatible_error(error)

    assert isinstance(translated, expected_type)
    assert translated.cause is error


@pytest.mark.parametrize(
    ("status_code", "expected_type"),
    [
        (401, ProviderAuthorizationError),
        (403, ProviderAuthorizationError),
        (404, ProviderNotFoundError),
        (409, ProviderConflictError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
        (400, ProviderRequestError),
        (302, ProviderResponseError),
    ],
)
def test_translates_generic_openai_status_errors_by_status_code(
    status_code: int,
    expected_type: type[Exception],
) -> None:
    error = APIStatusError(
        f"status {status_code}",
        response=_response(status_code),
        body={"status": status_code},
    )

    translated = translate_openai_compatible_error(error)

    assert isinstance(translated, expected_type)
    assert translated.cause is error


def test_translation_preserves_status_context() -> None:
    error = RateLimitError(
        "too many requests",
        response=_response(429),
        body={"error": "rate_limit"},
    )

    translated = translate_openai_compatible_error(error)

    assert str(translated) == "too many requests"
    assert translated.detail == (
        "status_code=429; request_id=req_test; body={'error': 'rate_limit'}"
    )
    assert translated.cause is error


def test_translation_falls_back_to_exception_class_name_for_empty_message() -> None:
    class EmptyMessageError(Exception):
        def __str__(self) -> str:
            return ""

    error = EmptyMessageError()

    translated = translate_openai_compatible_error(
        cast(OpenAICompatibleError, error),
    )

    assert isinstance(translated, ProviderRequestError)
    assert str(translated) == "EmptyMessageError"
    assert translated.detail is None
    assert translated.cause is error


def test_raise_openai_compatible_error_preserves_exception_chain() -> None:
    error = APIConnectionError(message="network down", request=_request())

    with pytest.raises(ProviderUnavailableError) as exc_info:
        raise_openai_compatible_error(error)

    assert exc_info.value.cause is error
    assert exc_info.value.__cause__ is error
