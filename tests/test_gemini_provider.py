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
    PromptCacheMode,
    PromptCachePolicy,
)
from EvernightAI.core.schema.provider import (
    ProviderConfig,
    ProviderModelConfig,
    ProviderType,
)
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.infra.adapters.providers.gemini.instance import GeminiProviderInstance
from EvernightAI.infra.adapters.providers.gemini.mapper import (
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


def test_maps_tools_to_gemini_request() -> None:
    assert to_gemini_request(make_messages(), [make_tool()]) == {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello"}],
            }
        ],
        "systemInstruction": {"parts": [{"text": "Be brief."}]},
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "list_directory",
                        "description": "List files in a directory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                            },
                            "required": ["path"],
                        },
                    }
                ]
            }
        ],
    }


def test_maps_inline_image_to_gemini_request() -> None:
    message = Content(
        role=MessageRole.USER,
        content=[
            ContentPart(type=ContentPartType.TEXT, text="Describe this"),
            ContentPart(
                type=ContentPartType.IMAGE,
                data="aW1hZ2U=",
                mime_type="image/png",
            ),
        ],
    )

    assert to_gemini_request([message]) == {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "Describe this"},
                    {
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": "aW1hZ2U=",
                        }
                    },
                ],
            }
        ]
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


def test_maps_gemini_function_call_response_to_chat_response() -> None:
    mapped = from_gemini_response(
        {
            "responseId": "resp-1",
            "modelVersion": "gemini-test",
            "candidates": [
                {
                    "index": 0,
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "list_directory",
                                    "args": {"path": "."},
                                }
                            }
                        ]
                    },
                }
            ],
        },
        "gemini-test",
    )

    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="resp-1:tool:0",
            tool_call={"name": "list_directory", "arguments": {"path": "."}},
        )
    ]


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


def test_maps_assistant_tool_calls_empty_messages_and_tool_results() -> None:
    request = to_gemini_request(
        [
            Content(role=MessageRole.USER),
            Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="Checking")],
                tool_calls=[
                    ToolCall(
                        tool_call_id="call-1",
                        tool_call={"name": "lookup", "arguments": "invalid"},
                    )
                ],
            ),
            Content(
                role=MessageRole.TOOL,
                tool_call_id="call-1",
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="result "),
                    ContentPart(type=ContentPartType.TEXT, text="ok"),
                ],
                metadata={"tool_name": "lookup"},
            ),
        ]
    )

    assert request == {
        "contents": [
            {"role": "user", "parts": [{"text": ""}]},
            {
                "role": "model",
                "parts": [
                    {"text": "Checking"},
                    {"functionCall": {"name": "lookup", "args": {}}},
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "lookup",
                            "response": {"content": "result ok"},
                        }
                    }
                ],
            },
        ]
    }


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.IMAGE, url="image.png")],
            ),
            "remote URLs are not supported",
        ),
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
                tool_calls=[ToolCall(tool_call_id="call-1", tool_call={})],
            ),
            "Tool call requires a function name",
        ),
        (
            Content(
                role=MessageRole.TOOL,
                tool_call_id="call-1",
                content=[ContentPart(type=ContentPartType.IMAGE, url="image.png")],
            ),
            "tool message only supports text content",
        ),
    ],
)
def test_rejects_unsupported_gemini_message_content(
    message: Content,
    error: str,
) -> None:
    with pytest.raises(ChatInputError, match=error):
        to_gemini_request([message])


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({}, "did not include candidates"),
        ({"candidates": [None]}, "candidate is invalid"),
        ({"candidates": [{}]}, "did not include content"),
        (
            {"candidates": [{"content": {"parts": "invalid"}}]},
            "content parts are invalid",
        ),
    ],
)
def test_rejects_malformed_gemini_responses(
    response: dict[str, Any],
    error: str,
) -> None:
    with pytest.raises(ProviderResponseError, match=error):
        from_gemini_response(response, "fallback-model")


def test_maps_gemini_response_fallbacks_and_usage_metadata() -> None:
    mapped = from_gemini_response(
        {
            "responseId": None,
            "candidates": [
                {
                    "content": {
                        "parts": [
                            None,
                            {"text": 1},
                            {"functionCall": {"name": "", "args": {}}},
                            {"functionCall": {"name": "lookup", "args": []}},
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": "3",
                "candidatesTokenCount": 2,
                "totalTokenCount": 2,
                "cachedContentTokenCount": 1,
            },
        },
        "fallback-model",
    )

    assert mapped.model_id == "fallback-model"
    assert mapped.message.content is None
    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="gemini:tool:0",
            tool_call={"name": "lookup", "arguments": {}},
        )
    ]
    assert mapped.usage is not None
    assert mapped.usage.prompt_tokens is None
    assert mapped.usage.cached_prompt_tokens == 1
    assert mapped.usage.metadata == {"cachedContentTokenCount": 1}


def test_normalizes_gemini_usage_finish_and_malformed_stream_parts() -> None:
    chunk = {
        "responseId": 7,
        "modelVersion": [],
        "usageMetadata": {
            "promptTokenCount": 2,
            "candidatesTokenCount": 1,
            "totalTokenCount": 3,
            "thoughtsTokenCount": 1,
        },
        "candidates": [
            None,
            {
                "index": 2,
                "content": {
                    "parts": [
                        None,
                        {"text": ""},
                        {"functionCall": {"name": "missing-args"}},
                        {"functionCall": {"name": "lookup", "args": {"q": "x"}}},
                    ]
                },
                "finishReason": "MAX_TOKENS",
            },
        ],
    }

    events = from_gemini_stream_chunk(chunk)

    assert [event.event_type for event in events] == [
        ChatStreamEventType.USAGE,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
        ChatStreamEventType.MESSAGE_COMPLETED,
    ]
    assert events[0].usage is not None
    assert events[0].usage.metadata == {"thoughtsTokenCount": 1}
    assert events[1].tool_call_id == "gemini:tool:2:3"
    assert events[2].finish_reason == "MAX_TOKENS"
    assert all(event.response_id is None and event.model_id is None for event in events)


@pytest.mark.parametrize(
    "chunk",
    [
        {"candidates": "invalid"},
        {"candidates": [{"content": {"parts": "invalid"}}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": ""}}]}}]},
    ],
)
def test_preserves_unrecognized_gemini_stream_chunks_as_raw(
    chunk: dict[str, Any],
) -> None:
    events = from_gemini_stream_chunk(chunk)

    assert len(events) == 1
    assert events[0].event_type is ChatStreamEventType.RAW
    assert events[0].raw_data == chunk


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
async def test_gemini_instance_chat_forwards_tools() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gemini-test",
            messages=make_messages(),
            tools=[make_tool()],
        )
    )

    assert fake_client.requests[-1]["json"] == to_gemini_request(
        make_messages(),
        [make_tool()],
    )

    await instance.close()


@pytest.mark.asyncio
async def test_gemini_prompt_cache_policy_uses_provider_implicit_caching() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client
    request = ChatRequest(
        model_id="gemini-test",
        messages=make_messages(),
        prompt_cache=PromptCachePolicy(
            mode=PromptCacheMode.PREFER_EXPLICIT,
            scope_id="owner-scope",
        ),
    )

    await instance.chat(request)
    stream = await instance.chat_stream(request)
    _ = [event async for event in stream]

    assert fake_client.requests[0]["json"] == to_gemini_request(make_messages())
    assert fake_client.requests[1]["json"] == to_gemini_request(make_messages())

    await instance.close()


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
async def test_gemini_instance_stream_forwards_tools() -> None:
    instance = GeminiProviderInstance(make_config())
    fake_client = FakeGeminiClient()
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(
            model_id="gemini-test",
            messages=make_messages(),
            tools=[make_tool()],
        )
    )
    _ = [event async for event in stream]

    assert fake_client.requests[-1]["json"] == to_gemini_request(
        make_messages(),
        [make_tool()],
    )

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
