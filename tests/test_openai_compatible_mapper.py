import pytest
from types import SimpleNamespace
from typing import Any, cast

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.stream import ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.infra.adapters.providers.openai_compatible.mapper import (
    OpenAIChatStreamNormalizer,
    from_openai_chat_completion,
    from_openai_chat_completion_chunk,
    to_openai_content_part,
    to_openai_message,
    to_openai_messages,
    to_openai_tool,
    to_openai_tool_call,
    to_openai_tool_calls,
    to_openai_tools,
)
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)


def test_maps_text_messages_to_chat_completion_message_params() -> None:
    messages = [
        Content(
            role=MessageRole.SYSTEM,
            content=[ContentPart(type=ContentPartType.TEXT, text="You are helpful.")],
        ),
        Content(
            role=MessageRole.USER,
            content=[ContentPart(type=ContentPartType.TEXT, text="Hello")],
            name="cyrene",
        ),
    ]

    assert to_openai_messages(messages) == [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello", "name": "cyrene"},
    ]


def test_maps_user_image_content_part() -> None:
    message = Content(
        role=MessageRole.USER,
        content=[
            ContentPart(type=ContentPartType.TEXT, text="Describe this: "),
            ContentPart(
                type=ContentPartType.IMAGE,
                url="https://example.test/image.png",
                detail="high",
            ),
        ],
    )

    assert to_openai_message(message) == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this: "},
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://example.test/image.png",
                    "detail": "high",
                },
            },
        ],
    }


def test_maps_base64_image_content_part_to_data_uri() -> None:
    message = Content(
        role=MessageRole.USER,
        content=[
            ContentPart(
                type=ContentPartType.IMAGE,
                data="aW1hZ2U=",
                mime_type="image/png",
            )
        ],
    )

    assert to_openai_message(message) == {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
            }
        ],
    }


def test_rejects_base64_image_without_mime_type() -> None:
    with pytest.raises(ChatInputError, match="requires mime_type"):
        to_openai_content_part(
            ContentPart(type=ContentPartType.IMAGE, data="aW1hZ2U=")
        )


def test_rejects_mismatched_image_data_uri_mime_type() -> None:
    with pytest.raises(ChatInputError, match="does not match"):
        to_openai_content_part(
            ContentPart(
                type=ContentPartType.IMAGE,
                data="data:image/png;base64,aW1hZ2U=",
                mime_type="image/jpeg",
            )
        )


def test_rejects_ambiguous_image_sources() -> None:
    with pytest.raises(ChatInputError, match="either url or data"):
        to_openai_content_part(
            ContentPart(
                type=ContentPartType.IMAGE,
                url="https://example.test/image.png",
                data="aW1hZ2U=",
                mime_type="image/png",
            )
        )


def test_rejects_invalid_base64_image_data() -> None:
    with pytest.raises(ChatInputError, match="valid base64"):
        to_openai_content_part(
            ContentPart(
                type=ContentPartType.IMAGE,
                data="not-base64",
                mime_type="image/png",
            )
        )


def test_maps_tool_definition_to_chat_completion_tool_param() -> None:
    tool = ToolDefinition(
        name="add",
        description="Add two numbers",
        parameters_schema={
            "type": "object",
            "properties": {
                "left": {"type": "number"},
                "right": {"type": "number"},
            },
            "required": ["left", "right"],
        },
    )

    assert to_openai_tool(tool) == {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "left": {"type": "number"},
                    "right": {"type": "number"},
                },
                "required": ["left", "right"],
            },
        },
    }


def test_maps_tool_definitions_to_chat_completion_tool_params() -> None:
    tools = [
        ToolDefinition(name="read_file", description="Read a file"),
        ToolDefinition(name="write_file", description="Write a file"),
    ]

    assert to_openai_tools(tools) == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write a file",
            },
        },
    ]


def test_maps_assistant_tool_call_arguments_to_json_string() -> None:
    tool_call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "add", "arguments": {"left": 1, "right": 2}},
    )

    assert to_openai_tool_call(tool_call) == {
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "add",
            "arguments": '{"left": 1, "right": 2}',
        },
    }
    assert to_openai_message(
        Content(role=MessageRole.ASSISTANT, tool_calls=[tool_call])
    ) == {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "add",
                    "arguments": '{"left": 1, "right": 2}',
                },
            }
        ],
    }


def test_maps_assistant_tool_call_string_arguments_without_reencoding() -> None:
    tool_call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "search", "arguments": '{"query":"你好"}'},
    )

    assert to_openai_tool_calls([tool_call]) == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "search",
                "arguments": '{"query":"你好"}',
            },
        }
    ]


def test_maps_tool_result_message() -> None:
    message = Content(
        role=MessageRole.TOOL,
        tool_call_id="call-1",
        content=[ContentPart(type=ContentPartType.TEXT, text='{"result": 3}')],
    )

    assert to_openai_message(message) == {
        "role": "tool",
        "content": '{"result": 3}',
        "tool_call_id": "call-1",
    }


def test_maps_chat_completion_response_to_chat_response() -> None:
    response = ChatCompletion(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "finish_reason": "tool_calls",
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Let me calculate.",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "add",
                                    "arguments": '{"left": 1, "right": 2}',
                                },
                            }
                        ],
                    },
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion",
        usage=cast(
            Any,
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        ),
    )

    mapped = from_openai_chat_completion(response)

    assert mapped.response_id == "chatcmpl-1"
    assert mapped.model_id == "gpt-test"
    assert mapped.finish_reason == "tool_calls"
    assert mapped.message.role is MessageRole.ASSISTANT
    assert mapped.message.content == [
        ContentPart(type=ContentPartType.TEXT, text="Let me calculate.")
    ]
    assert mapped.message.tool_calls == [
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "add", "arguments": {"left": 1, "right": 2}},
        )
    ]
    assert mapped.usage is not None
    assert mapped.usage.total_tokens == 15


def test_maps_chat_completion_response_without_content_or_usage() -> None:
    response = ChatCompletion(
        id="chatcmpl-empty",
        choices=cast(
            Any,
            [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {"role": "assistant", "content": None},
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion",
        system_fingerprint="fp-test",
    )

    mapped = from_openai_chat_completion(response)

    assert mapped.message.content is None
    assert mapped.message.tool_calls is None
    assert mapped.usage is None
    assert mapped.metadata == {
        "created": 123,
        "choice_index": 0,
        "system_fingerprint": "fp-test",
    }


def test_maps_chat_completion_response_usage_details_and_refusal() -> None:
    response = ChatCompletion(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "No.",
                        "refusal": "safety",
                    },
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion",
        usage=cast(
            Any,
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_tokens_details": {
                    "cached_tokens": 2,
                    "cache_write_tokens": 4,
                },
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        ),
    )

    mapped = from_openai_chat_completion(response)

    assert mapped.metadata["refusal"] == "safety"
    assert mapped.usage is not None
    assert mapped.usage.cached_prompt_tokens == 2
    assert mapped.usage.cache_write_prompt_tokens == 4
    assert mapped.usage.metadata == {
        "prompt_tokens_details": {
            "audio_tokens": None,
            "cached_tokens": 2,
            "cache_write_tokens": 4,
        },
        "completion_tokens_details": {
            "accepted_prediction_tokens": None,
            "audio_tokens": None,
            "reasoning_tokens": 3,
            "rejected_prediction_tokens": None,
        },
    }


def test_rejects_chat_completion_response_without_choices() -> None:
    response = ChatCompletion(
        id="chatcmpl-empty",
        choices=[],
        created=123,
        model="gpt-test",
        object="chat.completion",
    )

    with pytest.raises(ProviderResponseError, match="did not include choices"):
        from_openai_chat_completion(response)


def test_rejects_unsupported_response_tool_call_type() -> None:
    response = cast(
        ChatCompletion,
        SimpleNamespace(
            id="chatcmpl-1",
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    index=0,
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                type="custom",
                                function=SimpleNamespace(
                                    name="add",
                                    arguments="{}",
                                ),
                            )
                        ],
                        refusal=None,
                    ),
                )
            ],
            created=123,
            model="gpt-test",
            system_fingerprint=None,
            usage=None,
        ),
    )

    with pytest.raises(ProviderResponseError, match="Unsupported OpenAI tool call"):
        from_openai_chat_completion(response)


def test_maps_chat_completion_chunk_to_chat_stream_event() -> None:
    chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "delta": {"role": "assistant", "content": "Hel"},
                    "finish_reason": None,
                    "index": 0,
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
    )

    event = from_openai_chat_completion_chunk(chunk)

    assert event.event_type is ChatStreamEventType.RAW
    assert event.raw_event == "chat.completion.chunk"
    assert event.response_id == "chatcmpl-1"
    assert event.model_id == "gpt-test"
    assert event.raw_data == {
        "id": "chatcmpl-1",
        "choices": [
            {
                "delta": {"content": "Hel", "role": "assistant"},
                "index": 0,
            }
        ],
        "created": 123,
        "model": "gpt-test",
        "object": "chat.completion.chunk",
    }


def test_normalizes_chat_completion_text_chunk() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "delta": {"role": "assistant", "content": "Hel"},
                    "finish_reason": None,
                    "index": 0,
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
    )

    events = normalizer.map_chunk(chunk)

    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_START,
        ChatStreamEventType.MESSAGE_DELTA,
    ]
    assert events[1].text_delta == "Hel"


def test_normalizes_chunk_with_usage_and_no_choices() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunk = ChatCompletionChunk(
        id="chatcmpl-usage",
        choices=[],
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
        usage=cast(
            Any,
            {
                "prompt_tokens": 7,
                "completion_tokens": 0,
                "total_tokens": 7,
                "prompt_tokens_details": {
                    "cached_tokens": 1,
                    "cache_write_tokens": 3,
                },
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        ),
    )

    events = normalizer.map_chunk(chunk)

    assert [event.event_type for event in events] == [ChatStreamEventType.USAGE]
    assert events[0].usage is not None
    assert events[0].usage.total_tokens == 7
    assert events[0].usage.cached_prompt_tokens == 1
    assert events[0].usage.cache_write_prompt_tokens == 3
    assert events[0].usage.metadata == {
        "prompt_tokens_details": {
            "audio_tokens": None,
            "cached_tokens": 1,
            "cache_write_tokens": 3,
        },
        "completion_tokens_details": {
            "accepted_prediction_tokens": None,
            "audio_tokens": None,
            "reasoning_tokens": 0,
            "rejected_prediction_tokens": None,
        },
    }


def test_normalizes_chunk_with_finish_reason_to_message_completed() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "delta": {},
                    "finish_reason": "stop",
                    "index": 2,
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
    )

    events = normalizer.map_chunk(chunk)

    assert [event.event_type for event in events] == [
        ChatStreamEventType.MESSAGE_COMPLETED
    ]
    assert events[0].finish_reason == "stop"
    assert events[0].metadata == {"choice_index": 2}


def test_normalizes_chat_completion_tool_call_chunks() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunks = [
        ChatCompletionChunk(
            id="chatcmpl-1",
            choices=cast(
                Any,
                [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "add",
                                        "arguments": "{\"left\":",
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                        "index": 0,
                    }
                ],
            ),
            created=123,
            model="gpt-test",
            object="chat.completion.chunk",
        ),
        ChatCompletionChunk(
            id="chatcmpl-1",
            choices=cast(
                Any,
                [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "arguments": "1}",
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                        "index": 0,
                    }
                ],
            ),
            created=123,
            model="gpt-test",
            object="chat.completion.chunk",
        ),
    ]

    events = [event for chunk in chunks for event in normalizer.map_chunk(chunk)]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.TOOL_CALL_START,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
    ]
    assert events[-1].tool_call == ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "add", "arguments": {"left": 1}},
    )


def test_normalizes_tool_call_chunk_without_index() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunk = ChatCompletionChunk.model_construct(
        id="chatcmpl-1",
        choices=[
            Choice.model_construct(
                delta=ChoiceDelta.model_construct(
                    role=None,
                    content=None,
                    tool_calls=[
                        ChoiceDeltaToolCall.model_construct(
                            id="call-1",
                            type="function",
                            function=ChoiceDeltaToolCallFunction.model_construct(
                                name="add",
                                arguments=None,
                            ),
                        )
                    ],
                ),
                finish_reason=None,
                index=0,
            )
        ],
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
    )

    events = normalizer.map_chunk(chunk)

    assert [event.event_type for event in events] == [
        ChatStreamEventType.TOOL_CALL_START
    ]
    assert events[0].metadata == {"choice_index": 0, "tool_call_index": 0}
    assert events[0].tool_call_id == "call-1"
    assert events[0].tool_name == "add"


def test_skips_incomplete_streamed_tool_calls_on_completion() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunks = [
        ChatCompletionChunk(
            id="chatcmpl-1",
            choices=cast(
                Any,
                [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"arguments": "not-json"},
                                },
                                {
                                    "index": 1,
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {
                                        "name": "search",
                                        "arguments": "raw arguments",
                                    },
                                },
                            ]
                        },
                        "finish_reason": None,
                        "index": 0,
                    }
                ],
            ),
            created=123,
            model="gpt-test",
            object="chat.completion.chunk",
        ),
        ChatCompletionChunk(
            id="chatcmpl-1",
            choices=cast(
                Any,
                [
                    {
                        "delta": {},
                        "finish_reason": "tool_calls",
                        "index": 0,
                    }
                ],
            ),
            created=123,
            model="gpt-test",
            object="chat.completion.chunk",
        ),
    ]

    events = [event for chunk in chunks for event in normalizer.map_chunk(chunk)]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.TOOL_CALL_START,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_START,
        ChatStreamEventType.TOOL_CALL_DELTA,
        ChatStreamEventType.TOOL_CALL_COMPLETED,
    ]
    assert events[-1].metadata == {"tool_call_index": 1}
    assert events[-1].tool_call == ToolCall(
        tool_call_id="call-2",
        tool_call={"name": "search", "arguments": "raw arguments"},
    )


def test_normalizer_falls_back_to_raw_event_for_empty_semantic_chunk() -> None:
    normalizer = OpenAIChatStreamNormalizer()
    chunk = ChatCompletionChunk(
        id="chatcmpl-1",
        choices=cast(
            Any,
            [
                {
                    "delta": {},
                    "finish_reason": None,
                    "index": 0,
                }
            ],
        ),
        created=123,
        model="gpt-test",
        object="chat.completion.chunk",
    )

    events = normalizer.map_chunk(chunk)

    assert [event.event_type for event in events] == [ChatStreamEventType.RAW]


def test_rejects_unsupported_content_part() -> None:
    with pytest.raises(ChatInputError):
        to_openai_content_part(ContentPart(type=ContentPartType.VIDEO, url="video.mp4"))


def test_rejects_unsupported_message_role() -> None:
    message = Content.model_construct(role="developer")

    with pytest.raises(ChatInputError, match="Unsupported message role"):
        to_openai_message(message)


def test_rejects_tool_message_without_tool_call_id() -> None:
    with pytest.raises(ChatInputError):
        to_openai_message(
            Content(
                role=MessageRole.TOOL,
                content=[ContentPart(type=ContentPartType.TEXT, text="result")],
            )
        )


def test_rejects_non_text_system_message_content() -> None:
    with pytest.raises(ChatInputError, match="only supports text content"):
        to_openai_message(
            Content(
                role=MessageRole.SYSTEM,
                content=[
                    ContentPart(
                        type=ContentPartType.IMAGE,
                        url="https://example.test/image.png",
                    )
                ],
            )
        )


def test_rejects_text_part_without_text() -> None:
    with pytest.raises(ChatInputError, match="requires text"):
        to_openai_message(
            Content(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT)],
            )
        )


def test_rejects_image_part_without_url_or_data() -> None:
    with pytest.raises(ChatInputError, match="requires url or data"):
        to_openai_content_part(ContentPart(type=ContentPartType.IMAGE))


def test_rejects_tool_call_without_function_name() -> None:
    with pytest.raises(ChatInputError, match="requires a function name"):
        to_openai_tool_call(ToolCall(tool_call_id="call-1", tool_call={}))
