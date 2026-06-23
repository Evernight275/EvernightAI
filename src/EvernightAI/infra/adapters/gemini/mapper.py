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
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall


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


def from_gemini_stream_chunk(chunk: dict[str, Any]) -> list[ChatStreamEvent]:
    response_id = chunk.get("responseId")
    model_id = chunk.get("modelVersion")
    response_id = response_id if isinstance(response_id, str) else None
    model_id = model_id if isinstance(model_id, str) else None
    events: list[ChatStreamEvent] = []

    usage = _usage_from_gemini(chunk)
    if usage is not None:
        events.append(
            ChatStreamEvent(
                event_type=ChatStreamEventType.USAGE,
                response_id=response_id,
                model_id=model_id,
                usage=usage,
                raw_event="gemini.generate_content.chunk",
                raw_data=chunk,
            )
        )

    candidates = chunk.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                events.extend(
                    _gemini_candidate_stream_events(
                        candidate,
                        response_id=response_id,
                        model_id=model_id,
                        raw_data=chunk,
                    )
                )

    return events or [_raw_gemini_stream_event(chunk, response_id, model_id)]


def _gemini_candidate_stream_events(
    candidate: dict[str, Any],
    *,
    response_id: str | None,
    model_id: str | None,
    raw_data: dict[str, Any],
) -> list[ChatStreamEvent]:
    events: list[ChatStreamEvent] = []
    candidate_index = candidate.get("index", 0)
    metadata = {"candidate_index": candidate_index}
    content = candidate.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue
                part_metadata = {
                    **metadata,
                    "part_index": part_index,
                }
                if isinstance(part.get("text"), str) and part["text"]:
                    events.append(
                        ChatStreamEvent(
                            event_type=ChatStreamEventType.MESSAGE_DELTA,
                            response_id=response_id,
                            model_id=model_id,
                            role=MessageRole.ASSISTANT,
                            text_delta=part["text"],
                            content_part=ContentPart(
                                type=ContentPartType.TEXT,
                                text=part["text"],
                            ),
                            raw_event="gemini.generate_content.chunk",
                            raw_data=raw_data,
                            metadata=part_metadata,
                        )
                    )
                function_call = part.get("functionCall")
                if isinstance(function_call, dict):
                    tool_event = _gemini_function_call_event(
                        function_call,
                        response_id=response_id,
                        model_id=model_id,
                        raw_data=raw_data,
                        metadata=part_metadata,
                    )
                    if tool_event is not None:
                        events.append(tool_event)

    finish_reason = candidate.get("finishReason")
    if isinstance(finish_reason, str) and finish_reason:
        events.append(
            ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_COMPLETED,
                response_id=response_id,
                model_id=model_id,
                finish_reason=finish_reason,
                raw_event="gemini.generate_content.chunk",
                raw_data=raw_data,
                metadata=metadata,
            )
        )

    return events


def _gemini_function_call_event(
    function_call: dict[str, Any],
    *,
    response_id: str | None,
    model_id: str | None,
    raw_data: dict[str, Any],
    metadata: dict[str, Any],
) -> ChatStreamEvent | None:
    name = function_call.get("name")
    args = function_call.get("args")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(args, dict):
        return None

    tool_call_id = _gemini_tool_call_id(response_id, metadata)
    tool_call = ToolCall(
        tool_call_id=tool_call_id,
        tool_call={
            "name": name,
            "arguments": args,
        },
    )
    return ChatStreamEvent(
        event_type=ChatStreamEventType.TOOL_CALL_COMPLETED,
        response_id=response_id,
        model_id=model_id,
        tool_call_id=tool_call_id,
        tool_name=name,
        tool_call=tool_call,
        raw_event="gemini.generate_content.chunk",
        raw_data=raw_data,
        metadata=metadata,
    )


def _gemini_tool_call_id(
    response_id: str | None,
    metadata: dict[str, Any],
) -> str:
    return (
        f"{response_id or 'gemini'}:"
        f"tool:{metadata['candidate_index']}:{metadata['part_index']}"
    )


def _raw_gemini_stream_event(
    chunk: dict[str, Any],
    response_id: str | None,
    model_id: str | None,
) -> ChatStreamEvent:
    return ChatStreamEvent(
        event_type=ChatStreamEventType.RAW,
        response_id=response_id,
        model_id=model_id,
        raw_event="gemini.generate_content.chunk",
        raw_data=chunk,
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
