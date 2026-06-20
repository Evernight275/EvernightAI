from __future__ import annotations

from typing import Any, cast

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseOutputMessage,
    ResponseOutputText,
)

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
from EvernightAI.core.schema.tool import ToolDefinition
from EvernightAI.infra.adapters.openai_responses.instance import (
    OpenAIResponsesProviderInstance,
)
from EvernightAI.infra.adapters.openai_responses.mapper import (
    from_openai_response,
    to_openai_response_input,
    to_openai_response_tools,
)


def make_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="openai-responses-main",
        name="OpenAI Responses Main",
        type=ProviderType.OPENAI_RESPONSES,
        model={"gpt-test": ProviderModelConfig(model_id="gpt-test")},
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


def make_response(model_id: str = "gpt-test") -> Response:
    return Response(
        id="resp-1",
        created_at=123.0,
        model=model_id,
        object="response",
        output=[
            ResponseOutputMessage(
                id="msg-1",
                content=[
                    ResponseOutputText(
                        annotations=[],
                        text="Hi",
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        status="completed",
    )


def test_maps_messages_to_openai_response_input() -> None:
    assert to_openai_response_input(make_messages()) == [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": "Be brief."}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Hello"}],
        },
    ]


def test_maps_tool_definition_to_openai_response_tool() -> None:
    tool = ToolDefinition(
        name="lookup",
        description="Lookup a value",
        parameters_schema={"type": "object"},
    )

    assert to_openai_response_tools([tool]) == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a value",
            "parameters": {"type": "object"},
        }
    ]


def test_maps_openai_response_to_chat_response() -> None:
    mapped = from_openai_response(make_response())

    assert mapped.response_id == "resp-1"
    assert mapped.model_id == "gpt-test"
    assert mapped.finish_reason == "completed"
    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]


@pytest.mark.asyncio
async def test_openai_responses_instance_chat_maps_request_and_response() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    response = await instance.chat(
        ChatRequest(model_id="gpt-test", messages=make_messages())
    )

    assert responses.params == {
        "model": "gpt-test",
        "input": to_openai_response_input(make_messages()),
        "timeout": 30.0,
    }
    assert response.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]

    await instance.close()

    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_openai_responses_instance_stream_allows_undeclared_model() -> None:
    instance = OpenAIResponsesProviderInstance(
        ProviderConfig(
            provider_id="openai-responses-main",
            name="OpenAI Responses Main",
            type=ProviderType.OPENAI_RESPONSES,
        )
    )
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="provider-model", messages=make_messages())
    )
    events = [event async for event in stream]

    assert responses.params == {
        "model": "provider-model",
        "input": to_openai_response_input(make_messages()),
        "timeout": 30.0,
        "stream": True,
    }
    assert [event.event for event in events] == ["response.completed", "done"]

    await instance.close()


class FakeResponses:
    def __init__(self) -> None:
        self.params: dict[str, object] | None = None

    async def create(self, **params: object) -> Response | FakeResponseStream:
        self.params = params
        if params.get("stream") is True:
            return FakeResponseStream(
                [
                    ResponseCompletedEvent(
                        response=make_response("provider-model"),
                        sequence_number=0,
                        type="response.completed",
                    )
                ]
            )

        return make_response()


class FakeResponseStream:
    def __init__(self, events: list[ResponseCompletedEvent]) -> None:
        self._events = events

    def __aiter__(self) -> "FakeResponseStream":
        return self

    async def __anext__(self) -> ResponseCompletedEvent:
        if not self._events:
            raise StopAsyncIteration

        return self._events.pop(0)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses
        self.closed = False

    async def close(self) -> None:
        self.closed = True
