import json
from collections.abc import Iterable
from typing import Any

from openai.types.responses import Response, ResponseStreamEvent

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
from EvernightAI.core.schema.tool import ToolDefinition


def to_openai_response_input(messages: Iterable[Content]) -> list[dict[str, Any]]:
    return [to_openai_response_input_item(message) for message in messages]


def to_openai_response_input_item(message: Content) -> dict[str, Any]:
    if message.role is MessageRole.SYSTEM:
        return {
            "role": "system",
            "content": _input_content(message),
        }
    if message.role is MessageRole.USER:
        return {
            "role": "user",
            "content": _input_content(message),
        }
    if message.role is MessageRole.ASSISTANT:
        return {
            "role": "assistant",
            "content": _input_content(message),
        }
    if message.role is MessageRole.TOOL:
        if not message.tool_call_id:
            raise ChatInputError("Tool message requires tool_call_id")

        return {
            "type": "function_call_output",
            "call_id": message.tool_call_id,
            "output": _text_content(message),
        }

    raise ChatInputError(f"Unsupported message role: {message.role}")


def to_openai_response_tools(tools: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    return [to_openai_response_tool(tool) for tool in tools]


def to_openai_response_tool(tool: ToolDefinition) -> dict[str, Any]:
    return _without_none(
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema,
        }
    )


def from_openai_response(response: Response) -> ChatResponse:
    output = response.output
    text = _output_text(output)
    if not text:
        raise ProviderResponseError("OpenAI response did not include output text")

    return ChatResponse(
        response_id=response.id,
        model_id=response.model,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=[ContentPart(type=ContentPartType.TEXT, text=text)],
        ),
        finish_reason=response.status,
        usage=_usage_from_openai_response(response),
        metadata={
            "created_at": response.created_at,
            "object": response.object,
            "status": response.status,
            "error": response.error.model_dump() if response.error else None,
            "incomplete_details": (
                response.incomplete_details.model_dump()
                if response.incomplete_details
                else None
            ),
        },
    )


def from_openai_response_stream_event(event: ResponseStreamEvent) -> SSEEvent:
    payload = event.model_dump(mode="json", exclude_none=True)
    return SSEEvent(
        data=json.dumps(payload, ensure_ascii=False),
        event=payload.get("type", "response.event"),
        id=payload.get("id"),
    )


def _input_content(message: Content) -> list[dict[str, Any]]:
    parts = message.content or []
    if not parts:
        return [{"type": "input_text", "text": ""}]

    return [_input_content_part(part) for part in parts]


def _input_content_part(part: ContentPart) -> dict[str, Any]:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"type": "input_text", "text": part.text}

    if part.type is ContentPartType.IMAGE:
        url = part.url or part.data
        if not url:
            raise ChatInputError("Image content part requires url or data")

        return _without_none(
            {
                "type": "input_image",
                "image_url": url,
                "detail": part.detail,
            }
        )

    raise ChatInputError(f"Unsupported content part type: {part.type}")


def _text_content(message: Content) -> str:
    parts = message.content or []
    if not parts:
        return ""

    if any(part.type is not ContentPartType.TEXT for part in parts):
        raise ChatInputError(f"{message.role} message only supports text content")

    texts: list[str] = []
    for part in parts:
        if part.text is None:
            raise ChatInputError("Text content part requires text")
        texts.append(part.text)

    return "".join(texts)


def _output_text(output: Any) -> str:
    texts: list[str] = []
    for item in output:
        item_type = getattr(item, "type", None)
        if item_type != "message":
            continue

        for content_part in getattr(item, "content", []):
            if getattr(content_part, "type", None) == "output_text":
                text = getattr(content_part, "text", None)
                if isinstance(text, str):
                    texts.append(text)

    return "".join(texts)


def _usage_from_openai_response(response: Response) -> ChatUsage | None:
    usage = response.usage
    if usage is None:
        return None

    metadata: dict[str, Any] = {}
    if usage.input_tokens_details is not None:
        metadata["input_tokens_details"] = usage.input_tokens_details.model_dump()
    if usage.output_tokens_details is not None:
        metadata["output_tokens_details"] = usage.output_tokens_details.model_dump()

    return ChatUsage(
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        metadata=metadata,
    )


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
