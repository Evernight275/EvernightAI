from __future__ import annotations

from typing import Any, cast

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderResponseError
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


def make_response(model_id: str = "gpt-test", output: list[Any] | None = None) -> Response:
    return Response(
        id="resp-1",
        created_at=123.0,
        model=model_id,
        object="response",
        output=(
            [
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
            ]
            if output is None
            else output
        ),
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


def test_maps_assistant_tool_calls_to_openai_response_input() -> None:
    messages = [
        Content(
            role=MessageRole.ASSISTANT,
            tool_calls=[
                ToolCall(
                    tool_call_id="call-1",
                    tool_call={"name": "add", "arguments": {"left": 1}},
                )
            ],
        ),
        Content(
            role=MessageRole.TOOL,
            tool_call_id="call-1",
            content=[ContentPart(type=ContentPartType.TEXT, text='{"result": 1}')],
        ),
    ]

    assert to_openai_response_input(messages) == [
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "add",
            "arguments": '{"left": 1}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"result": 1}',
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


def test_maps_openai_response_function_call_to_chat_response() -> None:
    mapped = from_openai_response(
        make_response(
            output=[
                ResponseFunctionToolCall(
                    arguments='{"left": 1}',
                    call_id="call-1",
                    name="add",
                    type="function_call",
                )
            ]
        )
    )

    assert mapped.message.content is None
    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "add", "arguments": {"left": 1}},
        )
    ]


def test_openai_response_requires_text_or_tool_calls() -> None:
    with pytest.raises(
        ProviderResponseError,
        match="did not include output text or tool calls",
    ):
        from_openai_response(make_response(output=[]))


def test_openai_response_tool_message_requires_call_id() -> None:
    with pytest.raises(ChatInputError, match="Tool message requires tool_call_id"):
        to_openai_response_input(
            [
                Content(
                    role=MessageRole.TOOL,
                    content=[
                        ContentPart(type=ContentPartType.TEXT, text='{"result": 1}')
                    ],
                )
            ]
        )


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
async def test_openai_responses_instance_chat_maps_reasoning_effort_metadata() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=make_messages(),
            metadata={
                "request_id": "req-1",
                "reasoning_effort": "high",
            },
        )
    )

    assert responses.params == {
        "model": "gpt-test",
        "input": to_openai_response_input(make_messages()),
        "timeout": 30.0,
        "reasoning_effort": "high",
    }

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_ignores_unknown_provider_metadata() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=make_messages(),
            metadata={
                "request_id": "req-1",
                "reasoning_effort": "extreme",
                "temperature": 0,
            },
        )
    )

    assert responses.params == {
        "model": "gpt-test",
        "input": to_openai_response_input(make_messages()),
        "timeout": 30.0,
    }

    await instance.close()


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
    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_COMPLETED,
        ChatStreamEventType.DONE,
    ]

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_stream_maps_reasoning_effort_metadata() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(
            model_id="gpt-test",
            messages=make_messages(),
            metadata={"reasoning_effort": "medium"},
        )
    )
    _ = [event async for event in stream]

    assert responses.params == {
        "model": "gpt-test",
        "input": to_openai_response_input(make_messages()),
        "timeout": 30.0,
        "stream": True,
        "reasoning_effort": "medium",
    }

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_stream_maps_function_call_events() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses(
        stream_events=[
            ResponseOutputItemAddedEvent(
                item=ResponseFunctionToolCall(
                    arguments="",
                    call_id="call-1",
                    id="item-1",
                    name="add",
                    type="function_call",
                ),
                output_index=0,
                sequence_number=0,
                type="response.output_item.added",
            ),
            ResponseFunctionCallArgumentsDeltaEvent(
                delta='{"left":',
                item_id="item-1",
                output_index=0,
                sequence_number=1,
                type="response.function_call_arguments.delta",
            ),
            ResponseFunctionCallArgumentsDoneEvent(
                arguments='{"left": 1}',
                item_id="item-1",
                name="add",
                output_index=0,
                sequence_number=2,
                type="response.function_call_arguments.done",
            ),
        ]
    )
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="gpt-test", messages=make_messages())
    )
    events = [event async for event in stream]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.TOOL_CALL_START,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
        ChatStreamEventType.DONE,
    ]
    assert events[0].tool_call_id == "call-1"
    assert events[1].tool_call_id == "call-1"
    assert events[2].tool_call == ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "add", "arguments": {"left": 1}},
    )

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_stream_maps_text_delta_and_item_done() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses(
        stream_events=[
            ResponseTextDeltaEvent(
                content_index=0,
                delta="Hi",
                item_id="msg-1",
                logprobs=[],
                output_index=0,
                sequence_number=0,
                type="response.output_text.delta",
            ),
            ResponseOutputItemDoneEvent(
                item=ResponseFunctionToolCall(
                    arguments='{"left": 1}',
                    call_id="call-1",
                    id="item-1",
                    name="add",
                    type="function_call",
                ),
                output_index=1,
                sequence_number=1,
                type="response.output_item.done",
            ),
        ]
    )
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    stream = await instance.chat_stream(
        ChatRequest(model_id="gpt-test", messages=make_messages())
    )
    events = [event async for event in stream]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
        ChatStreamEventType.DONE,
    ]
    assert events[0].text_delta == "Hi"
    assert events[1].tool_call == ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "add", "arguments": {"left": 1}},
    )

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_lists_remote_models_with_declared_fallback() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    fake_client = FakeClient(
        FakeResponses(),
        models=FakeModels(["gpt-test", "remote-response-model"]),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == [
        "gpt-test",
        "remote-response-model",
    ]
    assert (
        await instance.get_model("remote-response-model")
    ).model_id == "remote-response-model"

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_falls_back_to_declared_models() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    fake_client = FakeClient(
        FakeResponses(),
        models=FakeModels(
            [],
            error=RuntimeError("models unavailable"),
        ),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gpt-test"]

    await instance.close()


class FakeResponses:
    def __init__(self, stream_events: list[Any] | None = None) -> None:
        self.params: dict[str, object] | None = None
        self._stream_events = stream_events

    async def create(self, **params: object) -> Response | FakeResponseStream:
        self.params = params
        if params.get("stream") is True:
            events = self._stream_events or [
                    ResponseCompletedEvent(
                        response=make_response("provider-model"),
                        sequence_number=0,
                        type="response.completed",
                    )
                ]
            return FakeResponseStream(events)

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


class FakeRemoteModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class FakeModelsPage:
    def __init__(self, model_ids: list[str]) -> None:
        self.data = [FakeRemoteModel(model_id) for model_id in model_ids]


class FakeModels:
    def __init__(
        self,
        model_ids: list[str],
        *,
        error: Exception | None = None,
    ) -> None:
        self._model_ids = model_ids
        self._error = error

    async def list(self) -> FakeModelsPage:
        if self._error is not None:
            raise self._error

        return FakeModelsPage(self._model_ids)


class FakeClient:
    def __init__(
        self,
        responses: FakeResponses,
        *,
        models: FakeModels | None = None,
    ) -> None:
        self.responses = responses
        self.models = models or FakeModels([])
        self.closed = False

    async def close(self) -> None:
        self.closed = True
