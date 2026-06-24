import httpx
import pytest

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
from EvernightAI.infra.adapters.http_errors import (
    raise_httpx_provider_error,
    translate_httpx_provider_error,
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://provider.test/chat")


def _status_error(status_code: int, text: str = "upstream error") -> httpx.HTTPStatusError:
    response = httpx.Response(
        status_code,
        headers={"x-request-id": "req_http"},
        text=text,
        request=_request(),
    )
    return httpx.HTTPStatusError("bad response", request=_request(), response=response)


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (httpx.ReadTimeout("slow", request=_request()), ProviderRequestTimeoutError),
        (httpx.ConnectError("network down", request=_request()), ProviderUnavailableError),
        (_status_error(401), ProviderAuthorizationError),
        (_status_error(403), ProviderAuthorizationError),
        (_status_error(404), ProviderNotFoundError),
        (_status_error(409), ProviderConflictError),
        (_status_error(429), ProviderRateLimitError),
        (_status_error(500), ProviderUnavailableError),
        (_status_error(400), ProviderRequestError),
        (_status_error(302), ProviderResponseError),
        (httpx.DecodingError("bad json"), ProviderResponseError),
        (httpx.ProtocolError("bad protocol"), ProviderRequestError),
    ],
)
def test_translates_httpx_errors_to_provider_errors(
    error: httpx.HTTPError,
    expected_type: type[Exception],
) -> None:
    translated = translate_httpx_provider_error(error)

    assert isinstance(translated, expected_type)
    assert translated.cause is error


def test_httpx_error_translation_preserves_response_detail() -> None:
    translated = translate_httpx_provider_error(_status_error(429, '{"error":"limit"}'))

    assert translated.detail == (
        "status_code=429; request_id=req_http; body='{\"error\":\"limit\"}'"
    )


def test_httpx_error_translation_ignores_unread_streaming_response_body() -> None:
    response = httpx.Response(
        503,
        headers={"x-request-id": "req_stream"},
        stream=httpx.ByteStream(b"temporarily unavailable"),
        request=_request(),
    )
    error = httpx.HTTPStatusError(
        "server unavailable",
        request=_request(),
        response=response,
    )

    translated = translate_httpx_provider_error(error)

    assert isinstance(translated, ProviderUnavailableError)
    assert translated.detail == "status_code=503; request_id=req_stream"


def test_raise_httpx_provider_error_preserves_exception_chain() -> None:
    error = httpx.ConnectError("network down", request=_request())

    with pytest.raises(ProviderUnavailableError) as exc_info:
        raise_httpx_provider_error(error)

    assert exc_info.value.cause is error
    assert exc_info.value.__cause__ is error
