from typing import Any, cast

import httpx
import pytest

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


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="gemini-main",
        name="Gemini Main",
        type=ProviderType.GOOGLE,
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


class FakeGeminiClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False

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

    async def aclose(self) -> None:
        self.closed = True
