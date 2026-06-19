import json

import pytest
from typing import Any, cast

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.schema.content import (
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.infra.adapters.openai_compatible.mapper import (
    from_openai_chat_completion,
    from_openai_chat_completion_chunk,
    to_openai_content_part,
    to_openai_message,
    to_openai_messages,
    to_openai_tool,
    to_openai_tool_call,
)
from openai.types.chat import ChatCompletion, ChatCompletionChunk


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


def test_maps_chat_completion_chunk_to_sse_event() -> None:
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

    assert event.event == "chat.completion.chunk"
    assert event.event_id == "chatcmpl-1"
    assert json.loads(event.data) == {
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


def test_rejects_unsupported_content_part() -> None:
    with pytest.raises(ChatInputError):
        to_openai_content_part(ContentPart(type=ContentPartType.VIDEO, url="video.mp4"))


def test_rejects_tool_message_without_tool_call_id() -> None:
    with pytest.raises(ChatInputError):
        to_openai_message(
            Content(
                role=MessageRole.TOOL,
                content=[ContentPart(type=ContentPartType.TEXT, text="result")],
            )
        )
