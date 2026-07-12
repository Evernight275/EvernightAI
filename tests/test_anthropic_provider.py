from typing import Any, cast

import httpx
import pytest

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderResponseError
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
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.infra.adapters.providers.anthropic.instance import AnthropicProviderInstance
from EvernightAI.infra.adapters.providers.anthropic.mapper import (
    AnthropicStreamNormalizer,
    from_anthropic_response,
    to_anthropic_request,
)


def make_config(*, discover_models: bool = False) -> ProviderConfig:
    return ProviderConfig(
        provider_id="anthropic-main",
        name="Anthropic Main",
        type=ProviderType.ANTHROPIC,
        discover_models=discover_models,
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


def make_tool() -> ToolDefinition:
    return ToolDefinition(
        name="list_directory",
        description="List files in a directory.",
        parameters_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    )


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


def test_maps_tools_to_anthropic_request() -> None:
    assert to_anthropic_request(make_messages(), "claude-test", [make_tool()]) == {
        "model": "claude-test",
        "max_tokens": 1024,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            }
        ],
        "system": "Be brief.",
        "tools": [
            {
                "name": "list_directory",
                "description": "List files in a directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
            }
        ],
    }


def test_maps_url_and_base64_images_to_anthropic_request() -> None:
    message = Content(
        role=MessageRole.USER,
        content=[
            ContentPart(
                type=ContentPartType.IMAGE,
                url="https://example.test/image.webp",
            ),
            ContentPart(
                type=ContentPartType.IMAGE,
                data="aW1hZ2U=",
                mime_type="image/png",
            ),
        ],
    )

    request = to_anthropic_request([message], "claude-test")

    assert request["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": "https://example.test/image.webp",
                    },
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "aW1hZ2U=",
                    },
                },
            ],
        }
    ]


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


def test_maps_anthropic_tool_use_response_to_chat_response() -> None:
    mapped = from_anthropic_response(
        {
            "id": "msg-1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "list_directory",
                    "input": {"path": "."},
                }
            ],
            "stop_reason": "tool_use",
        }
    )

    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="toolu-1",
            tool_call={"name": "list_directory", "arguments": {"path": "."}},
        )
    ]
    assert mapped.finish_reason == "tool_use"


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


def test_normalizes_anthropic_text_delta_and_message_delta_events() -> None:
    normalizer = AnthropicStreamNormalizer()
    start_events = normalizer.map_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg-1",
                "model": "claude-test",
                "usage": {"input_tokens": 3, "output_tokens": 0},
            },
        },
    )
    delta_events = normalizer.map_event(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hi"},
        },
    )
    completed_events = normalizer.map_event(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": 3, "output_tokens": 2},
        },
    )

    assert [event.event_type for event in start_events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.USAGE,
    ]
    assert delta_events[0].event_type is ChatStreamEventType.MESSAGE_DELTA
    assert delta_events[0].text_delta == "Hi"
    assert [event.event_type for event in completed_events] == [
        ChatStreamEventType.USAGE,
        ChatStreamEventType.MESSAGE_COMPLETED,
    ]
    assert completed_events[-1].finish_reason == "end_turn"


def test_normalizes_anthropic_unknown_event_as_raw() -> None:
    event = AnthropicStreamNormalizer().map_event(
        "unknown",
        {"type": "unknown", "id": "msg-1", "value": 1},
    )[0]

    assert event.event_type is ChatStreamEventType.RAW
    assert event.response_id == "msg-1"
    assert event.raw_event == "unknown"


def test_maps_assistant_tool_calls_empty_messages_and_tool_results() -> None:
    request = to_anthropic_request(
        [
            Content(role=MessageRole.SYSTEM),
            Content(role=MessageRole.USER),
            Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="Checking")],
                tool_calls=[
                    ToolCall(
                        tool_call_id="toolu-1",
                        tool_call={"name": "lookup", "arguments": "invalid"},
                    )
                ],
            ),
            Content(
                role=MessageRole.TOOL,
                tool_call_id="toolu-1",
                content=[ContentPart(type=ContentPartType.TEXT, text="result")],
            ),
        ],
        "claude-test",
        [ToolDefinition(name="empty", description="No arguments")],
    )

    assert request == {
        "model": "claude-test",
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": ""}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Checking"},
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "lookup",
                        "input": {},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu-1",
                        "content": "result",
                    }
                ],
            },
        ],
        "system": "",
        "tools": [
            {
                "name": "empty",
                "description": "No arguments",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    }


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT)],
            ),
            "Text content part requires text",
        ),
        (
            Content(
                role=MessageRole.ASSISTANT,
                tool_calls=[ToolCall(tool_call_id="toolu-1", tool_call={})],
            ),
            "Tool call requires a function name",
        ),
        (
            Content(role=MessageRole.TOOL, content=[]),
            "Tool result requires a tool call id",
        ),
        (
            Content(
                role=MessageRole.TOOL,
                tool_call_id="toolu-1",
                content=[ContentPart(type=ContentPartType.IMAGE, url="image.png")],
            ),
            "tool message only supports text content",
        ),
    ],
)
def test_rejects_unsupported_anthropic_message_content(
    message: Content,
    error: str,
) -> None:
    with pytest.raises(ChatInputError, match=error):
        to_anthropic_request([message], "claude-test")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"model": "claude-test"}, "did not include content"),
        ({"content": []}, "did not include model"),
    ],
)
def test_rejects_malformed_anthropic_responses(
    response: dict[str, Any],
    error: str,
) -> None:
    with pytest.raises(ProviderResponseError, match=error):
        from_anthropic_response(response)


def test_maps_anthropic_response_fallbacks_and_usage_metadata() -> None:
    mapped = from_anthropic_response(
        {
            "model": "claude-test",
            "content": [
                None,
                {"type": "text", "text": 1},
                {"type": "tool_use", "id": "", "name": "ignored"},
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "lookup",
                    "input": [],
                },
            ],
            "usage": {
                "input_tokens": "3",
                "output_tokens": 2,
                "cache_read_input_tokens": 4,
            },
        }
    )

    assert mapped.message.content is None
    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="toolu-1",
            tool_call={"name": "lookup", "arguments": {}},
        )
    ]
    assert mapped.usage is not None
    assert mapped.usage.prompt_tokens is None
    assert mapped.usage.total_tokens is None
    assert mapped.usage.metadata == {"cache_read_input_tokens": 4}


def test_anthropic_stream_normalizer_preserves_malformed_events() -> None:
    normalizer = AnthropicStreamNormalizer()

    malformed_start = normalizer.map_event("message_start", {"message": []})
    malformed_block = normalizer.map_event(
        "content_block_start",
        {"index": "0", "content_block": {}},
    )
    invalid_tool = normalizer.map_event(
        "content_block_start",
        {"index": 0, "content_block": {"type": "tool_use", "id": 1}},
    )
    unknown_delta = normalizer.map_event(
        "content_block_delta",
        {"index": 0, "delta": {"type": "unknown"}},
    )
    orphan_delta = normalizer.map_event(
        "content_block_delta",
        {
            "index": 3,
            "delta": {"type": "input_json_delta", "partial_json": "{}"},
        },
    )
    invalid_stop = normalizer.map_event("content_block_stop", {"index": "0"})
    idle_delta = normalizer.map_event("message_delta", {"delta": {}})

    for events in [
        malformed_start,
        malformed_block,
        invalid_tool,
        unknown_delta,
        orphan_delta,
        invalid_stop,
        idle_delta,
    ]:
        assert len(events) == 1
        assert events[0].event_type is ChatStreamEventType.RAW


def test_anthropic_stream_normalizer_ignores_empty_text_and_non_tool_blocks() -> None:
    normalizer = AnthropicStreamNormalizer()

    assert normalizer.map_event(
        "content_block_start",
        {"index": 0, "content_block": {"type": "text", "text": ""}},
    ) == []
    assert normalizer.map_event(
        "content_block_delta",
        {"index": 0, "delta": {"type": "text_delta", "text": ""}},
    ) == []
    assert normalizer.map_event("content_block_stop", {"index": 0}) == []


@pytest.mark.parametrize("arguments", ["not-json", "[]"])
def test_anthropic_stream_normalizer_drops_invalid_completed_tool_calls(
    arguments: str,
) -> None:
    normalizer = AnthropicStreamNormalizer()
    normalizer.map_event(
        "content_block_start",
        {
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu-1",
                "name": "lookup",
                "input": {},
            },
        },
    )
    normalizer.map_event(
        "content_block_delta",
        {
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": arguments},
        },
    )

    assert normalizer.map_event("content_block_stop", {"index": 0}) == []


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
async def test_anthropic_instance_chat_forwards_tools() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient()
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="claude-test",
            messages=make_messages(),
            tools=[make_tool()],
        )
    )

    assert fake_client.requests[-1]["json"] == to_anthropic_request(
        make_messages(),
        "claude-test",
        [make_tool()],
    )

    await instance.close()


@pytest.mark.asyncio
async def test_anthropic_instance_chat_maps_timeout_metadata() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient()
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="claude-test",
            messages=make_messages(),
            metadata={"timeout_seconds": 12},
        )
    )

    assert fake_client.requests[-1]["timeout"] == 12.0

    await instance.close()


@pytest.mark.asyncio
async def test_anthropic_instance_stream_forwards_tools() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient()
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(
            model_id="claude-test",
            messages=make_messages(),
            tools=[make_tool()],
        )
    )
    _ = [event async for event in stream]

    assert fake_client.requests[-1]["json"] == {
        **to_anthropic_request(make_messages(), "claude-test", [make_tool()]),
        "stream": True,
    }

    await instance.close()


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


@pytest.mark.asyncio
async def test_anthropic_instance_lists_declared_models_without_remote_discovery() -> None:
    instance = AnthropicProviderInstance(make_config())
    fake_client = FakeAnthropicClient(
        models_response={
            "data": [
                {"id": "claude-test"},
                {"id": "claude-remote"},
            ]
        }
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["claude-test"]
    with pytest.raises(ProviderNotFoundError):
        await instance.get_model("claude-remote")
    assert fake_client.requests == []

    await instance.close()


@pytest.mark.asyncio
async def test_anthropic_instance_lists_remote_models_when_discovery_enabled() -> None:
    instance = AnthropicProviderInstance(make_config(discover_models=True))
    fake_client = FakeAnthropicClient(
        models_response={
            "data": [
                {"id": "claude-test"},
                {"id": "claude-remote"},
            ]
        }
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["claude-test", "claude-remote"]
    assert (await instance.get_model("claude-remote")).model_id == "claude-remote"
    assert fake_client.requests == [
        {"url": "/v1/models"},
        {"url": "/v1/models"},
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_anthropic_instance_falls_back_to_declared_models_when_discovery_fails() -> None:
    instance = AnthropicProviderInstance(make_config(discover_models=True))
    fake_client = FakeAnthropicClient(
        get_error=httpx.ConnectError(
            "network down",
            request=httpx.Request("GET", "https://anthropic.test/models"),
        )
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["claude-test"]
    assert fake_client.requests == [{"url": "/v1/models"}]

    await instance.close()


class FakeAnthropicClient:
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
        self._models_response = models_response or {"data": []}
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
