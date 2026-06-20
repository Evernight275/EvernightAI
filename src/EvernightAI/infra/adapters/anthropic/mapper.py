import json
from collections.abc import Iterable
from typing import Any

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


def to_anthropic_request(messages: Iterable[Content], model_id: str) -> dict[str, Any]:
    request_messages: list[dict[str, Any]] = []
    system_texts: list[str] = []

    for message in messages:
        if message.role is MessageRole.SYSTEM:
            system_texts.append(_text_content(message))
            continue

        request_messages.append(
            {
                "role": _anthropic_role(message),
                "content": _message_content(message),
            }
        )

    request: dict[str, Any] = {
        "model": model_id,
        "max_tokens": 1024,
        "messages": request_messages,
    }
    if system_texts:
        request["system"] = "\n".join(system_texts)

    return request


def from_anthropic_response(response: dict[str, Any]) -> ChatResponse:
    content = response.get("content")
    if not isinstance(content, list):
        raise ProviderResponseError("Anthropic response did not include content")

    text = "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    )
    message_content = (
        [ContentPart(type=ContentPartType.TEXT, text=text)]
        if text
        else None
    )

    model_id = response.get("model")
    if not isinstance(model_id, str):
        raise ProviderResponseError("Anthropic response did not include model")

    return ChatResponse(
        response_id=response.get("id"),
        model_id=model_id,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=message_content,
        ),
        finish_reason=response.get("stop_reason"),
        usage=_usage_from_anthropic(response),
        metadata={
            "type": response.get("type"),
            "role": response.get("role"),
            "stop_sequence": response.get("stop_sequence"),
        },
    )


def from_anthropic_stream_event(event: str | None, data: dict[str, Any]) -> SSEEvent:
    return SSEEvent(
        data=json.dumps(data, ensure_ascii=False),
        event=event or data.get("type") or "anthropic.message.chunk",
        id=data.get("id"),
    )


def _anthropic_role(message: Content) -> str:
    if message.role is MessageRole.USER:
        return "user"
    if message.role is MessageRole.ASSISTANT:
        return "assistant"
    if message.role is MessageRole.TOOL:
        return "user"

    raise ChatInputError(f"Unsupported Anthropic message role: {message.role}")


def _message_content(message: Content) -> list[dict[str, Any]]:
    parts = message.content or []
    if not parts:
        return [{"type": "text", "text": ""}]

    return [_content_part(part) for part in parts]


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


def _content_part(part: ContentPart) -> dict[str, Any]:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"type": "text", "text": part.text}

    raise ChatInputError(f"Unsupported Anthropic content part type: {part.type}")


def _usage_from_anthropic(response: dict[str, Any]) -> ChatUsage | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    prompt_tokens = input_tokens if isinstance(input_tokens, int) else None
    completion_tokens = output_tokens if isinstance(output_tokens, int) else None

    total_tokens = None
    if prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        metadata={
            key: value
            for key, value in usage.items()
            if key not in {"input_tokens", "output_tokens"}
        },
    )
