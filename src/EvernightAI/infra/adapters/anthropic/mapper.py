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
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall


class AnthropicStreamNormalizer:
    def __init__(self) -> None:
        self._response_id: str | None = None
        self._model_id: str | None = None
        self._tool_calls: dict[int, dict[str, Any]] = {}

    def map_event(self, event: str | None, data: dict[str, Any]) -> list[ChatStreamEvent]:
        raw_event = event or data.get("type") or "anthropic.message.chunk"
        if raw_event == "message_start":
            return self._map_message_start(raw_event, data)
        if raw_event == "content_block_start":
            return self._map_content_block_start(raw_event, data)
        if raw_event == "content_block_delta":
            return self._map_content_block_delta(raw_event, data)
        if raw_event == "content_block_stop":
            return self._map_content_block_stop(raw_event, data)
        if raw_event == "message_delta":
            return self._map_message_delta(raw_event, data)

        return [from_anthropic_stream_event(event, data)]

    def _map_message_start(
        self,
        raw_event: str,
        data: dict[str, Any],
    ) -> list[ChatStreamEvent]:
        message = data.get("message")
        if not isinstance(message, dict):
            return [from_anthropic_stream_event(raw_event, data)]

        response_id = message.get("id")
        model_id = message.get("model")
        self._response_id = response_id if isinstance(response_id, str) else None
        self._model_id = model_id if isinstance(model_id, str) else None

        events = [
            ChatStreamEvent(
                event_type=ChatStreamEventType.MESSAGE_START,
                response_id=self._response_id,
                model_id=self._model_id,
                role=MessageRole.ASSISTANT,
                raw_event=raw_event,
                raw_data=data,
            )
        ]
        usage = _usage_from_anthropic(message)
        if usage is not None:
            events.append(
                ChatStreamEvent(
                    event_type=ChatStreamEventType.USAGE,
                    response_id=self._response_id,
                    model_id=self._model_id,
                    usage=usage,
                    raw_event=raw_event,
                    raw_data=data,
                )
            )

        return events

    def _map_content_block_start(
        self,
        raw_event: str,
        data: dict[str, Any],
    ) -> list[ChatStreamEvent]:
        index = data.get("index")
        content_block = data.get("content_block")
        if not isinstance(index, int) or not isinstance(content_block, dict):
            return [from_anthropic_stream_event(raw_event, data)]
        if content_block.get("type") != "tool_use":
            return []

        tool_call_id = content_block.get("id")
        tool_name = content_block.get("name")
        if not isinstance(tool_call_id, str) or not isinstance(tool_name, str):
            return [from_anthropic_stream_event(raw_event, data)]

        self._tool_calls[index] = {
            "id": tool_call_id,
            "name": tool_name,
            "arguments": "",
        }
        initial_input = content_block.get("input")
        if isinstance(initial_input, dict) and initial_input:
            self._tool_calls[index]["arguments"] = json.dumps(
                initial_input,
                ensure_ascii=False,
            )

        return [
            ChatStreamEvent(
                event_type=ChatStreamEventType.TOOL_CALL_START,
                response_id=self._response_id,
                model_id=self._model_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                raw_event=raw_event,
                raw_data=data,
                metadata={"content_block_index": index},
            )
        ]

    def _map_content_block_delta(
        self,
        raw_event: str,
        data: dict[str, Any],
    ) -> list[ChatStreamEvent]:
        delta = data.get("delta")
        index = data.get("index")
        if not isinstance(delta, dict):
            return [from_anthropic_stream_event(raw_event, data)]

        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text")
            if not isinstance(text, str) or not text:
                return []
            return [
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_DELTA,
                    response_id=self._response_id,
                    model_id=self._model_id,
                    role=MessageRole.ASSISTANT,
                    text_delta=text,
                    content_part=ContentPart(type=ContentPartType.TEXT, text=text),
                    raw_event=raw_event,
                    raw_data=data,
                    metadata=_without_none({"content_block_index": index}),
                )
            ]

        if delta_type == "input_json_delta":
            partial_json = delta.get("partial_json")
            if not isinstance(index, int) or not isinstance(partial_json, str):
                return []
            call_state = self._tool_calls.get(index)
            if call_state is None:
                return [from_anthropic_stream_event(raw_event, data)]
            call_state["arguments"] = str(call_state.get("arguments", "")) + partial_json
            return [
                ChatStreamEvent(
                    event_type=ChatStreamEventType.TOOL_CALL_DELTA,
                    response_id=self._response_id,
                    model_id=self._model_id,
                    tool_call_id=call_state.get("id"),
                    tool_name=call_state.get("name"),
                    arguments_delta=partial_json,
                    raw_event=raw_event,
                    raw_data=data,
                    metadata={"content_block_index": index},
                )
            ]

        return [from_anthropic_stream_event(raw_event, data)]

    def _map_content_block_stop(
        self,
        raw_event: str,
        data: dict[str, Any],
    ) -> list[ChatStreamEvent]:
        index = data.get("index")
        if not isinstance(index, int):
            return [from_anthropic_stream_event(raw_event, data)]

        call_state = self._tool_calls.pop(index, None)
        if call_state is None:
            return []

        tool_call = _tool_call_from_anthropic_state(call_state)
        if tool_call is None:
            return []

        return [
            ChatStreamEvent(
                event_type=ChatStreamEventType.TOOL_CALL_COMPLETED,
                response_id=self._response_id,
                model_id=self._model_id,
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_call.get("name"),
                tool_call=tool_call,
                raw_event=raw_event,
                raw_data=data,
                metadata={"content_block_index": index},
            )
        ]

    def _map_message_delta(
        self,
        raw_event: str,
        data: dict[str, Any],
    ) -> list[ChatStreamEvent]:
        events: list[ChatStreamEvent] = []
        usage = _usage_from_anthropic(data)
        if usage is not None:
            events.append(
                ChatStreamEvent(
                    event_type=ChatStreamEventType.USAGE,
                    response_id=self._response_id,
                    model_id=self._model_id,
                    usage=usage,
                    raw_event=raw_event,
                    raw_data=data,
                )
            )

        delta = data.get("delta")
        finish_reason = delta.get("stop_reason") if isinstance(delta, dict) else None
        if isinstance(finish_reason, str) and finish_reason:
            events.append(
                ChatStreamEvent(
                    event_type=ChatStreamEventType.MESSAGE_COMPLETED,
                    response_id=self._response_id,
                    model_id=self._model_id,
                    finish_reason=finish_reason,
                    raw_event=raw_event,
                    raw_data=data,
                )
            )

        return events or [from_anthropic_stream_event(raw_event, data)]


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


def from_anthropic_stream_event(
    event: str | None, data: dict[str, Any]
) -> ChatStreamEvent:
    response_id = data.get("id")
    raw_event = event or data.get("type") or "anthropic.message.chunk"
    return ChatStreamEvent(
        event_type=ChatStreamEventType.RAW,
        response_id=response_id if isinstance(response_id, str) else None,
        raw_event=raw_event if isinstance(raw_event, str) else None,
        raw_data=data,
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


def _tool_call_from_anthropic_state(call_state: dict[str, Any]) -> ToolCall | None:
    call_id = call_state.get("id")
    name = call_state.get("name")
    arguments = call_state.get("arguments", "")
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, str):
        arguments = ""

    try:
        parsed_arguments = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed_arguments, dict):
        return None

    return ToolCall(
        tool_call_id=call_id,
        tool_call={
            "name": name,
            "arguments": parsed_arguments,
        },
    )


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
