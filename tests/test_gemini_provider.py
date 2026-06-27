from typing import Any, cast

import httpx
import pytest

from EvernightAI.core.error.provider import ProviderNotFoundError, ProviderUnavailableError
from EvernightAI.core.schema.content import (
    ChatRequest,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.gemini.instance import GeminiProviderInstance
from EvernightAI.infra.adapters.gemini.mapper import (
    from_gemini_response,
    from_gemini_stream_chunk,
    to_gemini_request,
)


def make_config(*, discover_models: bool = False) -> ProviderConfig:
    return ProviderConfig(
        provider_id="gemini-main",
        name="Gemini Main",
        type=ProviderType.GOOGLE,
        discover_models=discover_models,
        model={"gemini-test": ProviderModelConfig(model_id="gemini-test")},
    )


def make_messages() -> list[Content]:
    return [
        Content(
            role=MessageRole.SYSTEM,
            content=[ContentPart(type=ContentPartType.TEXT, text="Be brief.")],
        ),
        Content(
            role=MessageRole.USER,
            content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
        ),
    ]


def test_maps_messages_to_gemini_request() -> None:
    assert to_gemini_request(make_messages()) == {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello"}],
            }
        ],
        "systemInstruction": {"parts": [{"text": "Be brief."}]},
    }


def test_maps_gemini_response_to_chat_response() -> None:
    mapped = from_gemini_response(
        {
            "responseId": "resp-1",
            "modelVersion": "gemini-test",
            "candidates": [
                {
                    "index": 0,
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "Hi"}]},
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 2,
                "totalTokenCount": 5,
            },
        },
        "gemini-test",
    )

    assert mapped.response_id == "resp-1"
    assert mapped.model_id == "gemini-test"
    assert mapped.finish_reason == "STOP"
    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]
    assert mapped.usage is not None
    assert mapped.usage.total_tokens == 5


def test_normalizes_gemini_text_and_function_call_chunks() -> None:
    events = from_gemini_stream_chunk(
        {
            "responseId": "resp-1",
            "modelVersion": "gemini-test",
            "candidates": [
                {
                    "index": 0,
                    "content": {
                        "parts": [
                            {"text": "Hi"},
                            {
                                "functionCall": {
                                    "name": "add",
                                    "args": {"left": 1},
                                }
                            },
                        ]
                    },
                }
            ],
        }
    )

    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
    ]
    assert events[0].text_delta == "Hi"
    assert events[1].tool_call == ToolCall(
        tool_call_id="resp-1:tool:0:1",
        tool_call={"name": "add", "arguments": {"left": 1}},
    )


@pytest.mark.asyncio
async def test_gemini_instance_chat_maps_request_and_response() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client

    response = await instance.chat(
        ChatRequest(model_id="gemini-test", messages=make_messages())
    )

    assert fake_client.requests == [
        {
            "url": "/v1beta/models/gemini-test:generateContent",
            "json": to_gemini_request(make_messages()),
            "params": None,
            "timeout": 30.0,
        }
    ]
    assert response.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]

    await instance.close()

    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_gemini_instance_chat_maps_timeout_metadata() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gemini-test",
            messages=make_messages(),
            metadata={"timeout_seconds": 12},
        )
    )

    assert fake_client.requests[-1]["timeout"] == 12.0

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_instance_stream_allows_undeclared_model() -> None:
    instance = GeminiProviderInstance(
        ProviderConfig(
            provider_id="gemini-main",
            name="Gemini Main",
            type=ProviderType.GOOGLE,
        )
    )
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="provider-model", messages=make_messages())
    )
    events = [event async for event in stream]

    assert fake_client.requests == [
        {
            "url": "/v1beta/models/provider-model:streamGenerateContent",
            "json": to_gemini_request(make_messages()),
            "params": {"alt": "sse"},
            "timeout": 30.0,
        }
    ]
    assert [event.raw_event for event in events] == [
        "gemini.generate_content.chunk",
        None,
    ]
    assert [event.event_type for event in events] == [
        ChatStreamEventType.RAW,
        ChatStreamEventType.DONE,
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_instance_stream_translates_network_errors() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient(
        stream_error=httpx.ConnectError(
            "network down",
            request=httpx.Request("POST", "https://gemini.test/stream"),
        )
    )
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="gemini-test", messages=make_messages())
    )

    with pytest.raises(ProviderUnavailableError, match="network down"):
        _ = [event async for event in stream]

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_instance_lists_declared_models_without_remote_discovery() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient(
        models_response={
            "models": [
                {"name": "models/gemini-test"},
                {"name": "models/gemini-remote"},
            ]
        }
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gemini-test"]
    with pytest.raises(ProviderNotFoundError):
        await instance.get_model("gemini-remote")
    assert fake_client.requests == []

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_instance_lists_remote_models_when_discovery_enabled() -> None:
    instance = GeminiProviderInstance(make_config(discover_models=True))
    fake_client = FakeGeminiClient(
        models_response={
            "models": [
                {"name": "models/gemini-test"},
                {"name": "models/gemini-remote"},
            ]
        }
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gemini-test", "gemini-remote"]
    assert (await instance.get_model("gemini-remote")).model_id == "gemini-remote"
    assert fake_client.requests == [
        {"url": "/v1beta/models"},
        {"url": "/v1beta/models"},
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_instance_falls_back_to_declared_models_when_discovery_fails() -> None:
    instance = GeminiProviderInstance(make_config(discover_models=True))
    fake_client = FakeGeminiClient(
        get_error=httpx.ConnectError(
            "network down",
            request=httpx.Request("GET", "https://gemini.test/models"),
        )
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gemini-test"]
    assert fake_client.requests == [{"url": "/v1beta/models"}]

    await instance.close()


class FakeGeminiClient:
    def __init__(
        self,
        stream_error: httpx.HTTPError | None = None,
        *,
        models_response: dict[str, object] | None = None,
        get_error: httpx.HTTPError | None = None,
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False
        self._stream_error = stream_error
        self._models_response = models_response or {"models": []}
        self._get_error = get_error

    async def get(self, url: str) -> httpx.Response:
        self.requests.append({"url": url})
        if self._get_error is not None:
            raise self._get_error

        return httpx.Response(
            200,
            json=self._models_response,
            request=httpx.Request("GET", url),
        )

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        params: dict[str, str] | None = None,
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {
                "url": url,
                "json": json,
                "params": params,
                "timeout": timeout,
            }
        )
        if params == {"alt": "sse"}:
            return httpx.Response(
                200,
                text='data: {"responseId": "resp-1", "candidates": []}\n\n',
                request=httpx.Request("POST", url),
            )

        return httpx.Response(
            200,
            json={
                "responseId": "resp-1",
                "modelVersion": "gemini-test",
                "candidates": [
                    {
                        "index": 0,
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "Hi"}]},
                    }
                ],
            },
            request=httpx.Request("POST", url),
        )

    def stream(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, object],
        params: dict[str, str],
        timeout: float,
    ) -> "FakeGeminiStreamContext":
        self.requests.append(
            {
                "url": url,
                "json": json,
                "params": params,
                "timeout": timeout,
            }
        )
        return FakeGeminiStreamContext(
            httpx.Response(
                200,
                text='data: {"responseId": "resp-1", "candidates": []}\n\n',
                request=httpx.Request(method, url),
            ),
            error=self._stream_error,
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeGeminiStreamContext:
    def __init__(
        self,
        response: httpx.Response,
        *,
        error: httpx.HTTPError | None = None,
    ) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self) -> httpx.Response:
        if self._error is not None:
            raise self._error

        return self._response

    async def __aexit__(self, *args: object) -> None:
        return None
