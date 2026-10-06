from collections.abc import Iterable
from copy import deepcopy
from typing import Any
from uuid import uuid4

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
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition
from EvernightAI.infra.adapters.provider_usage import token_count
from EvernightAI.infra.adapters.providers.image_input import (
    inline_image,
    validate_image_source,
)


class GeminiStreamNormalizer:
    def __init__(self) -> None:
        self._parts: list[dict[str, Any]] = []
        self._response_id = f"gemini-{uuid4().hex}"
        self._model_id: str | None = None
        self._call_ids: set[str] = set()
        self._calls: list[ToolCall] = []
        self._final_candidate: dict[str, Any] | None = None
        self._final_data: dict[str, Any] | None = None
        self.is_complete = False

    def map_chunk(self, chunk: dict[str, Any]) -> list[ChatStreamEvent]:
        if isinstance(chunk.get("responseId"), str):
            self._response_id = chunk["responseId"]
        if isinstance(chunk.get("modelVersion"), str):
            self._model_id = chunk["modelVersion"]
        normalized = {**chunk, "responseId": self._response_id}
        candidates = chunk.get("candidates")
        if isinstance(candidates, list) and candidates:
            normalized["candidates"] = candidates[:1]
        offset = len(self._parts)
        events = from_gemini_stream_chunk(normalized, part_offset=offset)
        for event in events:
            if event.event_type is ChatStreamEventType.TOOL_CALL_COMPLETED:
                if event.tool_call_id in self._call_ids:
                    raise ProviderResponseError(
                        "Gemini returned a duplicate tool call id"
                    )
                if event.tool_call_id is not None:
                    self._call_ids.add(event.tool_call_id)
                if event.tool_call is not None:
                    self._calls.append(event.tool_call)
        if (
            isinstance(candidates, list)
            and candidates
            and isinstance(candidates[0], dict)
        ):
            content = candidates[0].get("content", {})
            if isinstance(content, dict) and isinstance(content.get("parts"), list):
                self._parts.extend(deepcopy(content["parts"]))
            for event in events:
                if event.event_type is ChatStreamEventType.MESSAGE_COMPLETED:
                    self._final_candidate = deepcopy(candidates[0])
                    self._final_data = deepcopy(chunk)
                    self.is_complete = True
        return [
            event
            for event in events
            if event.event_type is not ChatStreamEventType.MESSAGE_COMPLETED
        ]

    def completed_event(self) -> ChatStreamEvent:
        if self._final_candidate is None:
            raise ProviderResponseError("Gemini stream ended without finishReason")
        response = from_gemini_response(
            {
                "responseId": self._response_id,
                "modelVersion": self._model_id,
                "candidates": [
                    {**self._final_candidate, "content": {"parts": self._parts}}
                ],
            },
            self._model_id or "gemini",
        )
        response.message.tool_calls = self._calls or None
        return ChatStreamEvent(
            event_type=ChatStreamEventType.MESSAGE_COMPLETED,
            response_id=self._response_id,
            model_id=self._model_id,
            finish_reason=response.finish_reason,
            message=response.message,
            raw_event="gemini.generate_content.chunk",
            raw_data=self._final_data,
        )


def to_gemini_request(
    messages: Iterable[Content],
    tools: Iterable[ToolDefinition] | None = None,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    system_parts: list[dict[str, Any]] = []
    calls_by_id: dict[str, dict[str, Any]] = {}
    previous_was_tool = False

    for message in messages:
        if message.role is MessageRole.SYSTEM:
            system_parts.extend(_message_parts(message))
            previous_was_tool = False
            continue

        parts = _message_parts(message)
        if message.role is MessageRole.ASSISTANT:
            function_calls = [
                part["functionCall"]
                for part in parts
                if isinstance(part.get("functionCall"), dict)
                and isinstance(part["functionCall"].get("name"), str)
                and part["functionCall"]["name"]
            ]
            for tool_call, function_call in zip(
                message.tool_calls or [], function_calls
            ):
                calls_by_id[tool_call.tool_call_id] = function_call
        if message.role is MessageRole.TOOL and message.tool_call_id in calls_by_id:
            call = calls_by_id[message.tool_call_id]
            parts[0]["functionResponse"]["name"] = call["name"]
            if isinstance(call.get("id"), str) and call["id"]:
                parts[0]["functionResponse"]["id"] = call["id"]
        if message.role is MessageRole.TOOL and previous_was_tool:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": _gemini_role(message), "parts": parts})
        previous_was_tool = message.role is MessageRole.TOOL

    request: dict[str, Any] = {"contents": contents}
    if system_parts:
        request["systemInstruction"] = {"parts": system_parts}
    if tools:
        request["tools"] = to_gemini_tools(tools)

    return request


def to_gemini_tools(tools: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    return [{"functionDeclarations": [to_gemini_tool(tool) for tool in tools]}]


def to_gemini_tool(tool: ToolDefinition) -> dict[str, Any]:
    return _without_none(
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters_schema or _empty_object_schema(),
        }
    )


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
        if isinstance(part, dict)
        and isinstance(part.get("text"), str)
        and part.get("thought") is not True
    )
    tool_calls = [
        tool_call
        for part_index, part in enumerate(parts)
        if isinstance(part, dict)
        for tool_call in [
            _tool_call_from_gemini_part(part, response.get("responseId"), part_index)
        ]
        if tool_call is not None
    ]
    if len({call.tool_call_id for call in tool_calls}) != len(tool_calls):
        raise ProviderResponseError("Gemini returned a duplicate tool call id")
    message_content = (
        [ContentPart(type=ContentPartType.TEXT, text=text)] if text else None
    )

    return ChatResponse(
        response_id=response.get("responseId"),
        model_id=response.get("modelVersion") or model_id,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=message_content,
            tool_calls=tool_calls or None,
            metadata={"gemini_parts": deepcopy(parts)},
        ),
        finish_reason=candidate.get("finishReason"),
        usage=_usage_from_gemini(response),
        metadata={
            "candidate_index": candidate.get("index", 0),
        },
    )


def from_gemini_stream_chunk(
    chunk: dict[str, Any], *, part_offset: int = 0
) -> list[ChatStreamEvent]:
    response_id = chunk.get("responseId")
    model_id = chunk.get("modelVersion")
    response_id = response_id if isinstance(response_id, str) else None
    model_id = model_id if isinstance(model_id, str) else None
    events: list[ChatStreamEvent] = []
    error = chunk.get("error")
    feedback = chunk.get("promptFeedback")
    if isinstance(error, dict) or (
        isinstance(feedback, dict) and feedback.get("blockReason")
    ):
        error = error if isinstance(error, dict) else (feedback or {})
        return [
            ChatStreamEvent(
                event_type=ChatStreamEventType.ERROR,
                error_type=str(
                    error.get("status") or error.get("blockReason") or "gemini_error"
                ),
                error_message=str(error.get("message") or "Gemini blocked the prompt"),
                raw_data=chunk,
            )
        ]

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
                        part_offset=part_offset,
                    )
                )

    return events or [_raw_gemini_stream_event(chunk, response_id, model_id)]


def _gemini_candidate_stream_events(
    candidate: dict[str, Any],
    *,
    response_id: str | None,
    model_id: str | None,
    raw_data: dict[str, Any],
    part_offset: int = 0,
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
                    "part_index": part_index + part_offset,
                }
                if (
                    isinstance(part.get("text"), str)
                    and part["text"]
                    and part.get("thought") is not True
                ):
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
    args = function_call.get("args", {})
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(args, dict):
        return None

    native_id = function_call.get("id")
    tool_call_id = (
        native_id
        if isinstance(native_id, str) and native_id
        else _gemini_tool_call_id(response_id, metadata)
    )
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
    if message.role is MessageRole.TOOL:
        return [_function_response_part(message)]

    native_parts = message.metadata.get("gemini_parts")
    if message.role is MessageRole.ASSISTANT and isinstance(native_parts, list):
        _validate_preserved_parts(message, native_parts)
        return deepcopy(native_parts)

    parts = message.content or []
    message_parts = [_content_part(part) for part in parts]
    message_parts.extend(
        _function_call_part(tool_call) for tool_call in message.tool_calls or []
    )
    if not message_parts:
        return [{"text": ""}]

    return message_parts


def _validate_preserved_parts(message: Content, parts: list[Any]) -> None:
    if any(not isinstance(part, dict) for part in parts):
        raise ChatInputError("Preserved Gemini content must contain objects")
    text = "".join(
        part["text"]
        for part in parts
        if isinstance(part.get("text"), str) and part.get("thought") is not True
    )
    function_calls = [
        call
        for part in parts
        if isinstance(call := part.get("functionCall"), dict)
        and isinstance(call.get("name"), str)
        and call["name"]
    ]
    calls = [
        {
            "name": call["name"],
            "arguments": call.get("args", {})
            if isinstance(call.get("args", {}), dict)
            else {},
        }
        for call in function_calls
    ]
    native_ids_match = all(
        not isinstance(native.get("id"), str)
        or not native["id"]
        or native["id"] == call.tool_call_id
        for native, call in zip(function_calls, message.tool_calls or [])
    )
    if (
        text != _text_content(message)
        or calls != [call.tool_call for call in message.tool_calls or []]
        or not native_ids_match
    ):
        raise ChatInputError(
            "Preserved Gemini content does not match the assistant message"
        )


def _content_part(part: ContentPart) -> dict[str, Any]:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"text": part.text}

    if part.type is ContentPartType.IMAGE:
        validate_image_source(part)
        if part.url:
            raise ChatInputError(
                "Gemini image content requires inline data; remote URLs are not supported"
            )
        mime_type, data = inline_image(part)
        return {"inlineData": {"mimeType": mime_type, "data": data}}

    raise ChatInputError(f"Unsupported Gemini content part type: {part.type}")


def _function_call_part(tool_call: ToolCall) -> dict[str, Any]:
    call = tool_call.tool_call
    name = call.get("name")
    arguments = call.get("arguments", {})
    if not isinstance(name, str) or not name:
        raise ChatInputError("Tool call requires a function name")
    if not isinstance(arguments, dict):
        arguments = {}

    return {"functionCall": {"name": name, "args": arguments}}


def _function_response_part(message: Content) -> dict[str, Any]:
    name = message.name
    if not name:
        name = str(message.metadata.get("tool_name", "tool_result"))

    return {
        "functionResponse": {
            "name": name,
            "response": {"content": _text_content(message)},
        }
    }


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


def _usage_from_gemini(response: dict[str, Any]) -> ChatUsage | None:
    usage = response.get("usageMetadata")
    if not isinstance(usage, dict):
        return None

    prompt_tokens = usage.get("promptTokenCount")
    completion_tokens = usage.get("candidatesTokenCount")
    total_tokens = usage.get("totalTokenCount")
    cached_prompt_tokens = usage.get("cachedContentTokenCount")

    return ChatUsage(
        prompt_tokens=token_count(prompt_tokens),
        completion_tokens=token_count(completion_tokens),
        total_tokens=token_count(total_tokens),
        cached_prompt_tokens=token_count(cached_prompt_tokens),
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


def _tool_call_from_gemini_part(
    part: dict[str, Any],
    response_id: object,
    part_index: int = 0,
) -> ToolCall | None:
    function_call = part.get("functionCall")
    if not isinstance(function_call, dict):
        return None

    name = function_call.get("name")
    arguments = function_call.get("args", {})
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, dict):
        arguments = {}

    call_id_prefix = (
        response_id
        if isinstance(response_id, str) and response_id
        else f"gemini-{uuid4().hex}"
    )
    native_id = function_call.get("id")
    return ToolCall(
        tool_call_id=native_id
        if isinstance(native_id, str) and native_id
        else f"{call_id_prefix}:tool:0:{part_index}",
        tool_call={
            "name": name,
            "arguments": arguments,
        },
    )


def _empty_object_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
