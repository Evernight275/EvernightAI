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
from EvernightAI.infra.adapters.anthropic.instance import AnthropicProviderInstance
from EvernightAI.infra.adapters.anthropic.mapper import (
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
    assert [event.event for event in events] == [
        "message_start",
        "done",
    ]

    await instance.close()


class FakeAnthropicClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.closed = False

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
                text='event: message_start\ndata: {"type": "message_start"}\n\n',
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

    async def aclose(self) -> None:
        self.closed = True
