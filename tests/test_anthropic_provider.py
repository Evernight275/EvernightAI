from typing import Any, cast

import httpx
import pytest

from EvernightAI.core.error.provider import ProviderUnavailableError
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
from EvernightAI.infra.adapters.anthropic.instance import AnthropicProviderInstance
from EvernightAI.infra.adapters.anthropic.mapper import (
    AnthropicStreamNormalizer,
    from_anthropic_response,
    to_anthropic_request,
)


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="anthropic-main",
        name="Anthropic Main",
        type=ProviderType.ANTHROPIC,
        model={"claude-test": ProviderModelConfig(model_id="claude-test")},
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


def test_maps_messages_to_anthropic_request() -> None:
    assert to_anthropic_request(make_messages(), "claude-test") == {
        "model": "claude-test",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            }
        ],
        "system": "Be brief.",
    }


def test_maps_anthropic_response_to_chat_response() -> None:
    mapped = from_anthropic_response(
        {
            "id": "msg-1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": "Hi"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
    )

    assert mapped.response_id == "msg-1"
    assert mapped.model_id == "claude-test"
    assert mapped.finish_reason == "end_turn"
    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]
    assert mapped.usage is not None
    assert mapped.usage.total_tokens == 5


def test_normalizes_anthropic_tool_use_stream_events() -> None:
    normalizer = AnthropicStreamNormalizer()

    events = [
        event
        for raw_event, data in [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg-1",
                        "model": "claude-test",
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "add",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": "{\"left\": 1}",
                    },
                },
            ),
            (
                "content_block_stop",
                {"type": "content_block_stop", "index": 0},
            ),
        ]
        for event in normalizer.map_event(raw_event, data)
    ]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.TOOL_CALL_START,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
    ]
    assert events[-1].tool_call == ToolCall(
        tool_call_id="toolu-1",
        tool_call={"name": "add", "arguments": {"left": 1}},
    )


@pytest.mark.asyncio
async def test_anthropic_instance_chat_maps_request_and_response() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient()
    cast(Any, instance)._client = fake_client

    response = await instance.chat(
        ChatRequest(model_id="claude-test", messages=make_messages())
    )

    assert fake_client.requests == [
        {
            "url": "/v1/messages",
            "json": to_anthropic_request(make_messages(), "claude-test"),
            "timeout": 30.0,
        }
    ]
    assert response.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]

    await instance.close()

    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_anthropic_instance_stream_allows_undeclared_model() -> None:
    instance = AnthropicProviderInstance(
        ProviderConfig(
            provider_id="anthropic-main",
            name="Anthropic Main",
            type=ProviderType.ANTHROPIC,
        )
    )
    fake_client = FakeAnthropicClient()
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="provider-model", messages=make_messages())
    )
    events = [event async for event in stream]

    assert fake_client.requests == [
        {
            "url": "/v1/messages",
            "json": {
                **to_anthropic_request(make_messages(), "provider-model"),
                "stream": True,
            },
            "timeout": 30.0,
        }
    ]
    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.DONE,
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_anthropic_instance_stream_translates_network_errors() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient(
        stream_error=httpx.ConnectError(
            "network down",
            request=httpx.Request("POST", "https://anthropic.test/stream"),
        )
    )
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="claude-test", messages=make_messages())
    )

    with pytest.raises(ProviderUnavailableError, match="network down"):
        _ = [event async for event in stream]

    await instance.close()


class FakeAnthropicClient:
    def __init__(self, stream_error: httpx.HTTPError | None = None) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False
        self._stream_error = stream_error

    async def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> httpx.Response:
        self.requests.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        if json.get("stream") is True:
            return httpx.Response(
                200,
                text=(
                    'event: message_start\n'
                    'data: {"type": "message_start", '
                    '"message": {"id": "msg-1", "model": "provider-model"}}\n\n'
                ),
                request=httpx.Request("POST", url),
            )

        return httpx.Response(
            200,
            json={
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "Hi"}],
                "stop_reason": "end_turn",
            },
            request=httpx.Request("POST", url),
        )

    def stream(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> "FakeAnthropicStreamContext":
        self.requests.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeAnthropicStreamContext(
            httpx.Response(
                200,
                text=(
                    'event: message_start\n'
                    'data: {"type": "message_start", '
                    '"message": {"id": "msg-1", "model": "provider-model"}}\n\n'
                ),
                request=httpx.Request(method, url),
            ),
            error=self._stream_error,
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeAnthropicStreamContext:
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
