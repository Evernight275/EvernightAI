import json
from collections.abc import Iterable
from typing import Any, cast

from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionContentPartParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)

from EvernightAI.core.error.chat import ChatInputError
from EvernightAI.core.error.provider import ProviderResponseError
from EvernightAI.core.schema.content import (
    ChatResponse,
    ChatUsage,
    Content,
    ContentPart,
    ContentPartType,
    MessageRole,
)
from EvernightAI.core.schema.stream import SSEEvent
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition


def to_openai_messages(messages: Iterable[Content]) -> list[ChatCompletionMessageParam]:
    return [to_openai_message(message) for message in messages]


def to_openai_message(message: Content) -> ChatCompletionMessageParam:
    if message.role is MessageRole.SYSTEM:
        return cast(
            ChatCompletionMessageParam,
            _without_none(
                {
                    "role": "system",
                    "content": _text_content(message),
                    "name": message.name,
                }
            ),
        )

    if message.role is MessageRole.USER:
        return cast(
            ChatCompletionMessageParam,
            _without_none(
                {
                    "role": "user",
                    "content": _message_content(message),
                    "name": message.name,
                }
            ),
        )

    if message.role is MessageRole.ASSISTANT:
        return cast(
            ChatCompletionMessageParam,
            _without_none(
                {
                    "role": "assistant",
                    "content": _optional_message_content(message),
                    "name": message.name,
                    "tool_calls": (
                        to_openai_tool_calls(message.tool_calls)
                        if message.tool_calls
                        else None
                    ),
                }
            ),
        )

    if message.role is MessageRole.TOOL:
        if not message.tool_call_id:
            raise ChatInputError("Tool message requires tool_call_id")

        return cast(
            ChatCompletionMessageParam,
            {
                "role": "tool",
                "content": _text_content(message),
                "tool_call_id": message.tool_call_id,
            },
        )

    raise ChatInputError(f"Unsupported message role: {message.role}")


def to_openai_tools(tools: Iterable[ToolDefinition]) -> list[ChatCompletionToolParam]:
    return [to_openai_tool(tool) for tool in tools]


def to_openai_tool(tool: ToolDefinition) -> ChatCompletionToolParam:
    return cast(
        ChatCompletionToolParam,
        {
            "type": "function",
            "function": _without_none(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                }
            ),
        },
    )


def to_openai_tool_calls(
    tool_calls: Iterable[ToolCall],
) -> list[ChatCompletionMessageToolCallParam]:
    return [to_openai_tool_call(tool_call) for tool_call in tool_calls]


def to_openai_tool_call(tool_call: ToolCall) -> ChatCompletionMessageToolCallParam:
    call = tool_call.tool_call
    name = call.get("name")
    if not isinstance(name, str) or not name:
        raise ChatInputError("Tool call requires a function name")

    arguments = call.get("arguments", {})

    return {
        "id": tool_call.tool_call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": _json_arguments(arguments),
        },
    }


def from_openai_chat_completion(response: ChatCompletion) -> ChatResponse:
    if not response.choices:
        raise ProviderResponseError("OpenAI response did not include choices")

    choice = response.choices[0]
    message = choice.message

    content = (
        [ContentPart(type=ContentPartType.TEXT, text=message.content)]
        if message.content
        else None
    )
    tool_calls = (
        [from_openai_tool_call(tool_call) for tool_call in message.tool_calls]
        if message.tool_calls
        else None
    )

    metadata: dict[str, Any] = {
        "created": response.created,
        "choice_index": choice.index,
    }
    if response.system_fingerprint:
        metadata["system_fingerprint"] = response.system_fingerprint
    if message.refusal:
        metadata["refusal"] = message.refusal

    return ChatResponse(
        response_id=response.id,
        model_id=response.model,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        ),
        finish_reason=choice.finish_reason,
        usage=_usage_from_openai(response),
        metadata=metadata,
    )


def from_openai_chat_completion_chunk(chunk: ChatCompletionChunk) -> SSEEvent:
    payload = chunk.model_dump(mode="json", exclude_none=True)
    return SSEEvent(
        data=json.dumps(payload, ensure_ascii=False),
        event="chat.completion.chunk",
        id=chunk.id,
    )


def from_openai_tool_call(tool_call: Any) -> ToolCall:
    tool_call_type = getattr(tool_call, "type", None)
    if tool_call_type != "function":
        raise ProviderResponseError(f"Unsupported OpenAI tool call type: {tool_call_type}")

    return ToolCall(
        tool_call_id=tool_call.id,
        tool_call={
            "name": tool_call.function.name,
            "arguments": _parse_json_arguments(tool_call.function.arguments),
        },
    )


def _message_content(message: Content) -> str | list[ChatCompletionContentPartParam]:
    parts = message.content or []
    if not parts:
        return ""

    if all(part.type is ContentPartType.TEXT for part in parts):
        return _join_text_parts(parts)

    return [to_openai_content_part(part) for part in parts]


def _optional_message_content(
    message: Content,
) -> str | list[ChatCompletionContentPartParam] | None:
    if not message.content:
        return None

    return _message_content(message)


def _text_content(message: Content) -> str:
    parts = message.content or []
    if not parts:
        return ""

    if any(part.type is not ContentPartType.TEXT for part in parts):
        raise ChatInputError(f"{message.role} message only supports text content")

    return _join_text_parts(parts)


def to_openai_content_part(part: ContentPart) -> ChatCompletionContentPartParam:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"type": "text", "text": part.text}

    if part.type is ContentPartType.IMAGE:
        url = part.url or part.data
        if not url:
            raise ChatInputError("Image content part requires url or data")

        image_url: dict[str, str] = {"url": url}
        if part.detail:
            image_url["detail"] = part.detail

        return cast(
            ChatCompletionContentPartParam,
            {"type": "image_url", "image_url": image_url},
        )

    raise ChatInputError(f"Unsupported content part type: {part.type}")


def _join_text_parts(parts: Iterable[ContentPart]) -> str:
    texts: list[str] = []
    for part in parts:
        if part.text is None:
            raise ChatInputError("Text content part requires text")
        texts.append(part.text)

    return "".join(texts)


def _json_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments

    return json.dumps(arguments, ensure_ascii=False)


def _parse_json_arguments(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def _usage_from_openai(response: ChatCompletion) -> ChatUsage | None:
    usage = response.usage
    if usage is None:
        return None

    metadata: dict[str, Any] = {}
    if usage.prompt_tokens_details is not None:
        metadata["prompt_tokens_details"] = usage.prompt_tokens_details.model_dump()
    if usage.completion_tokens_details is not None:
        metadata["completion_tokens_details"] = usage.completion_tokens_details.model_dump()

    return ChatUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        metadata=metadata,
    )


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
