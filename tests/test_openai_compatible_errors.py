import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ContentFilterFinishReasonError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    WebSocketConnectionClosedError,
    WebSocketQueueFullError,
    APIError,
)

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
from EvernightAI.infra.adapters.openai_compatible.errors import (
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
            InternalServerError("upstream down", response=_response(500), body=None),
            ProviderUnavailableError,
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


def test_raise_openai_compatible_error_preserves_exception_chain() -> None:
    error = APIConnectionError(message="network down", request=_request())

    with pytest.raises(ProviderUnavailableError) as exc_info:
        raise_openai_compatible_error(error)

    assert exc_info.value.cause is error
    assert exc_info.value.__cause__ is error
