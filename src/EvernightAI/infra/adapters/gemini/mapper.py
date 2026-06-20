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


def to_gemini_request(messages: Iterable[Content]) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, Any]] = []

    for message in messages:
        if message.role is MessageRole.SYSTEM:
            system_parts.extend(_message_parts(message))
            continue

        contents.append(
            {
                "role": _gemini_role(message),
                "parts": _message_parts(message),
            }
        )

    request: dict[str, Any] = {"contents": contents}
    if system_parts:
        request["systemInstruction"] = {"parts": system_parts}

    return request


def from_gemini_response(response: dict[str, Any], model_id: str) -> ChatResponse:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderResponseError("Gemini response did not include candidates")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ProviderResponseError("Gemini response candidate is invalid")

    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ProviderResponseError("Gemini response candidate did not include content")

    parts = content.get("parts", [])
    if not isinstance(parts, list):
        raise ProviderResponseError("Gemini response content parts are invalid")

    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )
    message_content = (
        [ContentPart(type=ContentPartType.TEXT, text=text)]
        if text
        else None
    )

    return ChatResponse(
        response_id=response.get("responseId"),
        model_id=response.get("modelVersion") or model_id,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=message_content,
        ),
        finish_reason=candidate.get("finishReason"),
        usage=_usage_from_gemini(response),
        metadata={
            "candidate_index": candidate.get("index", 0),
        },
    )


def from_gemini_stream_chunk(chunk: dict[str, Any]) -> SSEEvent:
    return SSEEvent(
        data=json.dumps(chunk, ensure_ascii=False),
        event="gemini.generate_content.chunk",
        id=chunk.get("responseId"),
    )


def _gemini_role(message: Content) -> str:
    if message.role is MessageRole.USER:
        return "user"
    if message.role is MessageRole.ASSISTANT:
        return "model"
    if message.role is MessageRole.TOOL:
        return "user"

    raise ChatInputError(f"Unsupported Gemini message role: {message.role}")


def _message_parts(message: Content) -> list[dict[str, Any]]:
    parts = message.content or []
    if not parts:
        return [{"text": ""}]

    return [_content_part(part) for part in parts]


def _content_part(part: ContentPart) -> dict[str, Any]:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"text": part.text}

    raise ChatInputError(f"Unsupported Gemini content part type: {part.type}")


def _usage_from_gemini(response: dict[str, Any]) -> ChatUsage | None:
    usage = response.get("usageMetadata")
    if not isinstance(usage, dict):
        return None

    prompt_tokens = usage.get("promptTokenCount")
    completion_tokens = usage.get("candidatesTokenCount")
    total_tokens = usage.get("totalTokenCount")

    return ChatUsage(
        prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
        completion_tokens=(
            completion_tokens if isinstance(completion_tokens, int) else None
        ),
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        metadata={
            key: value
            for key, value in usage.items()
            if key
            not in {
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
            }
        },
    )
