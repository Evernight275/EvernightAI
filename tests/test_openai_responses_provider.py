from __future__ import annotations

from types import SimpleNamespace
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
    ResponseOutputRefusal,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderNotFoundError, ProviderResponseError
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
    from_openai_response_stream_event,
    OpenAIResponsesStreamNormalizer,
    to_openai_response_function_call,
    to_openai_response_input,
    to_openai_response_input_item,
    to_openai_response_tools,
)


def make_config(*, discover_models: bool = False) -> ProviderConfig:
    return ProviderConfig(
        provider_id="openai-responses-main",
        name="OpenAI Responses Main",
        type=ProviderType.OPENAI_RESPONSES,
        discover_models=discover_models,
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
    assert to_openai_response_input(
        [
            *make_messages(),
            Content(
                role=MessageRole.ASSISTANT,
                content=[ContentPart(type=ContentPartType.TEXT, text="Hi")],
            ),
        ]
    ) == [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": "Be brief."}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Hello"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hi"}],
        },
    ]


def test_maps_empty_assistant_message_to_empty_output_text() -> None:
    assert to_openai_response_input_item(Content(role=MessageRole.ASSISTANT)) == {
        "role": "assistant",
        "content": [{"type": "output_text", "text": ""}],
    }


def test_rejects_multi_item_message_when_single_item_requested() -> None:
    message = Content(
        role=MessageRole.ASSISTANT,
        content=[ContentPart(type=ContentPartType.TEXT, text="Need a tool.")],
        tool_calls=[
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "add", "arguments": {"left": 1}},
            )
        ],
    )

    with pytest.raises(ChatInputError, match="maps to multiple"):
        to_openai_response_input_item(message)


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


def test_maps_response_function_call_string_arguments_without_reencoding() -> None:
    tool_call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "search", "arguments": '{"query":"你好"}'},
    )

    assert to_openai_response_function_call(tool_call) == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "search",
        "arguments": '{"query":"你好"}',
    }


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


def test_maps_openai_response_with_text_and_tool_calls() -> None:
    mapped = from_openai_response(
        make_response(
            output=[
                ResponseOutputMessage(
                    id="msg-1",
                    content=[
                        ResponseOutputText(
                            annotations=[],
                            text="I will call it.",
                            type="output_text",
                        )
                    ],
                    role="assistant",
                    status="completed",
                    type="message",
                ),
                ResponseFunctionToolCall(
                    arguments="raw arguments",
                    call_id="call-1",
                    name="search",
                    type="function_call",
                ),
            ]
        )
    )

    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="I will call it.")
    ]
    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "search", "arguments": "raw arguments"},
        )
    ]


def test_maps_openai_response_usage_and_metadata_details() -> None:
    response = cast(
        Response,
        SimpleNamespace(
            id="resp-1",
            created_at=123.0,
            model="gpt-test",
            object="response",
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(type="output_text", text="Hi"),
                        SimpleNamespace(type="refusal", text="No"),
                        SimpleNamespace(type="output_text", text=None),
                    ],
                ),
                SimpleNamespace(
                    type="function_call",
                    call_id="",
                    name="ignored",
                    arguments="{}",
                ),
                SimpleNamespace(
                    type="function_call",
                    call_id="call-2",
                    name="lookup",
                    arguments=None,
                ),
            ],
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
            status="incomplete",
            error=SimpleNamespace(model_dump=lambda: {"code": "rate_limit"}),
            incomplete_details=SimpleNamespace(model_dump=lambda: {"reason": "max_tokens"}),
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                input_tokens_details=SimpleNamespace(model_dump=lambda: {"cached_tokens": 2}),
                output_tokens_details=SimpleNamespace(model_dump=lambda: {"reasoning_tokens": 3}),
            ),
        ),
    )

    mapped = from_openai_response(response)

    assert mapped.message.content == [ContentPart(type=ContentPartType.TEXT, text="Hi")]
    assert mapped.message.tool_calls == [
        ToolCall(tool_call_id="call-2", tool_call={"name": "lookup", "arguments": {}})
    ]
    assert mapped.metadata["error"] == {"code": "rate_limit"}
    assert mapped.metadata["incomplete_details"] == {"reason": "max_tokens"}
    assert mapped.usage is not None
    assert mapped.usage.prompt_tokens == 10
    assert mapped.usage.completion_tokens == 5
    assert mapped.usage.total_tokens == 15
    assert mapped.usage.metadata == {
        "input_tokens_details": {"cached_tokens": 2},
        "output_tokens_details": {"reasoning_tokens": 3},
    }


def test_maps_openai_response_to_chat_response() -> None:
    mapped = from_openai_response(make_response())

    assert mapped.response_id == "resp-1"
    assert mapped.model_id == "gpt-test"
    assert mapped.finish_reason == "completed"
    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Hi")
    ]


def test_maps_openai_response_refusal_to_chat_response() -> None:
    mapped = from_openai_response(
        make_response(
            output=[
                ResponseOutputMessage(
                    id="msg-1",
                    content=[
                        ResponseOutputRefusal(
                            refusal="I cannot help with that.",
                            type="refusal",
                        )
                    ],
                    role="assistant",
                    status="completed",
                    type="message",
                )
            ]
        )
    )

    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="I cannot help with that.")
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


def test_openai_response_allows_empty_success_output() -> None:
    mapped = from_openai_response(make_response(output=[]))

    assert mapped.message.role is MessageRole.ASSISTANT
    assert mapped.message.content is None
    assert mapped.message.tool_calls is None


def test_openai_response_error_without_output_raises_provider_response_error() -> None:
    response = cast(
        Response,
        SimpleNamespace(
            id="resp-1",
            created_at=123.0,
            model="gpt-test",
            object="response",
            output=[],
            status="failed",
            error=SimpleNamespace(model_dump=lambda: {"message": "failed"}),
            incomplete_details=None,
            usage=None,
        ),
    )

    with pytest.raises(
        ProviderResponseError,
        match="failed before producing output",
    ):
        from_openai_response(response)


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


def test_openai_response_rejects_invalid_message_role_and_content() -> None:
    with pytest.raises(ChatInputError, match="Unsupported message role"):
        to_openai_response_input_item(Content.model_construct(role="developer"))

    with pytest.raises(ChatInputError, match="requires a function name"):
        to_openai_response_function_call(
            ToolCall(tool_call_id="call-1", tool_call={"arguments": {}})
        )

    with pytest.raises(ChatInputError, match="requires text"):
        to_openai_response_input_item(
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT)],
            )
        )

    with pytest.raises(ChatInputError, match="requires url or data"):
        to_openai_response_input_item(
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.IMAGE)],
            )
        )

    with pytest.raises(ChatInputError, match="Unsupported content part type"):
        to_openai_response_input_item(
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.VIDEO, url="video.mp4")],
            )
        )

    with pytest.raises(ChatInputError, match="only supports text content"):
        to_openai_response_input_item(
            Content(
                role=MessageRole.TOOL,
                tool_call_id="call-1",
                content=[
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        url="https://example.test/image.png",
                    )
                ],
            )
        )


def test_maps_single_response_stream_event() -> None:
    event = ResponseTextDeltaEvent(
        content_index=0,
        delta="Hi",
        item_id="msg-1",
        logprobs=[],
        output_index=0,
        sequence_number=0,
        type="response.output_text.delta",
    )

    mapped = from_openai_response_stream_event(event)

    assert mapped.event_type is ChatStreamEventType.MESSAGE_DELTA
    assert mapped.text_delta == "Hi"


def test_response_stream_normalizer_falls_back_to_raw_events() -> None:
    normalizer = OpenAIResponsesStreamNormalizer()

    assert normalizer._map_payload({"type": "response.output_item.added"}).event_type is (
        ChatStreamEventType.RAW
    )
    assert normalizer._map_payload({"type": "response.output_text.delta", "delta": ""}).event_type is (
        ChatStreamEventType.RAW
    )
    assert normalizer._map_payload(
        {"type": "response.function_call_arguments.delta", "delta": ""}
    ).event_type is ChatStreamEventType.RAW
    assert normalizer._map_payload(
        {"type": "response.function_call_arguments.done"}
    ).event_type is ChatStreamEventType.RAW
    assert normalizer._map_payload({"type": "response.output_item.done"}).event_type is (
        ChatStreamEventType.RAW
    )
    assert normalizer._map_payload({"type": "response.completed"}).event_type is (
        ChatStreamEventType.RAW
    )
    raw = normalizer._map_payload({"type": None, "id": 123})
    assert raw.event_type is ChatStreamEventType.RAW
    assert raw.response_id is None
    assert raw.raw_event == "response.event"


def test_response_stream_normalizer_handles_loose_function_call_events() -> None:
    normalizer = OpenAIResponsesStreamNormalizer()

    start = normalizer._map_payload(
        {
            "type": "response.output_item.added",
            "response_id": "resp-1",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "id": "item-1",
                "call_id": None,
                "name": "lookup",
            },
        }
    )
    delta = normalizer._map_payload(
        {
            "type": "response.function_call_arguments.delta",
            "response_id": "resp-1",
            "item_id": "item-1",
            "delta": "{\"query\":",
            "output_index": 0,
        }
    )
    completed = normalizer._map_payload(
        {
            "type": "response.function_call_arguments.done",
            "response_id": "resp-1",
            "item_id": "item-1",
            "arguments": '{"query": "hi"}',
            "output_index": 0,
        }
    )
    duplicate_done = normalizer._map_payload(
        {
            "type": "response.output_item.done",
            "response_id": "resp-1",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "id": "item-1",
                "call_id": "call-ignored",
                "name": "lookup",
                "arguments": '{"query": "hi"}',
            },
        }
    )
    fallback_id_done = normalizer._map_payload(
        {
            "type": "response.output_item.done",
            "response_id": "resp-1",
            "output_index": 1,
            "item": {
                "type": "function_call",
                "item_id": "item-2",
                "name": "raw_lookup",
                "arguments": "raw arguments",
            },
        }
    )

    assert start.event_type is ChatStreamEventType.TOOL_CALL_START
    assert start.tool_call_id is None
    assert start.tool_name == "lookup"
    assert delta.tool_call_id is None
    assert delta.tool_name == "lookup"
    assert completed.tool_call == ToolCall(
        tool_call_id="item-1",
        tool_call={"name": "lookup", "arguments": {"query": "hi"}},
    )
    assert duplicate_done.event_type is ChatStreamEventType.RAW
    assert fallback_id_done.tool_call == ToolCall(
        tool_call_id="item-2",
        tool_call={"name": "raw_lookup", "arguments": "raw arguments"},
    )


def test_response_stream_normalizer_completed_usage_mapping() -> None:
    normalizer = OpenAIResponsesStreamNormalizer()

    event = normalizer._map_payload(
        {
            "type": "response.completed",
            "response": {
                "id": "resp-1",
                "model": "gpt-test",
                "status": "completed",
                "usage": {
                    "input_tokens": "bad",
                    "output_tokens": 5,
                    "total_tokens": 12,
                    "input_tokens_details": {"cached_tokens": 1},
                },
            },
        }
    )

    assert event.event_type is ChatStreamEventType.MESSAGE_COMPLETED
    assert event.usage is not None
    assert event.usage.prompt_tokens is None
    assert event.usage.completion_tokens == 5
    assert event.usage.total_tokens == 12
    assert event.usage.metadata == {
        "input_tokens_details": {"cached_tokens": 1}
    }


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
async def test_openai_responses_instance_chat_maps_timeout_metadata() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    responses = FakeResponses()
    fake_client = FakeClient(responses)
    cast(Any, instance)._client = fake_client

    await instance.chat(
        ChatRequest(
            model_id="gpt-test",
            messages=make_messages(),
            metadata={"timeout_seconds": 12},
        )
    )

    assert responses.params is not None
    assert responses.params["timeout"] == 12.0

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
async def test_openai_responses_instance_lists_declared_models_without_remote_discovery() -> None:
    instance = OpenAIResponsesProviderInstance(make_config())
    fake_client = FakeClient(
        FakeResponses(),
        models=FakeModels(["gpt-test", "remote-response-model"]),
    )
    cast(Any, instance)._client = fake_client

    models = await instance.list_models()

    assert [model.model_id for model in models] == ["gpt-test"]
    with pytest.raises(ProviderNotFoundError):
        await instance.get_model("remote-response-model")
    assert fake_client.models.calls == 0

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_lists_remote_models_when_discovery_enabled() -> None:
    instance = OpenAIResponsesProviderInstance(make_config(discover_models=True))
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
    assert fake_client.models.calls == 2

    await instance.close()


@pytest.mark.asyncio
async def test_openai_responses_instance_falls_back_to_declared_models_when_discovery_fails() -> None:
    instance = OpenAIResponsesProviderInstance(make_config(discover_models=True))
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
    assert fake_client.models.calls == 1

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
        self.calls = 0

    async def list(self) -> FakeModelsPage:
        self.calls += 1
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
