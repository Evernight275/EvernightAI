from collections.abc import Iterable
import json
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
from EvernightAI.core.schema.stream import ChatStreamEvent, ChatStreamEventType
from EvernightAI.core.schema.tool import ToolCall, ToolDefinition


def to_openai_response_input(messages: Iterable[Content]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        items.extend(to_openai_response_input_items(message))
    return items


def to_openai_response_input_item(message: Content) -> dict[str, Any]:
    items = to_openai_response_input_items(message)
    if len(items) != 1:
        raise ChatInputError("Message maps to multiple OpenAI response input items")

    return items[0]


def to_openai_response_input_items(message: Content) -> list[dict[str, Any]]:
    if message.role is MessageRole.SYSTEM:
        return [{
            "role": "system",
            "content": _input_content(message),
        }]
    if message.role is MessageRole.USER:
        return [{
            "role": "user",
            "content": _input_content(message),
        }]
    if message.role is MessageRole.ASSISTANT:
        items: list[dict[str, Any]] = []
        if message.content:
            items.append(
                {
                    "role": "assistant",
                    "content": _assistant_content(message),
                }
            )
        for tool_call in message.tool_calls or []:
            items.append(to_openai_response_function_call(tool_call))
        if items:
            return items

        return [{"role": "assistant", "content": _assistant_content(message)}]
    if message.role is MessageRole.TOOL:
        if not message.tool_call_id:
            raise ChatInputError("Tool message requires tool_call_id")

        return [{
            "type": "function_call_output",
            "call_id": message.tool_call_id,
            "output": _text_content(message),
        }]

    raise ChatInputError(f"Unsupported message role: {message.role}")


def to_openai_response_function_call(tool_call: ToolCall) -> dict[str, Any]:
    call = tool_call.tool_call
    name = call.get("name")
    if not isinstance(name, str) or not name:
        raise ChatInputError("Tool call requires a function name")

    arguments = call.get("arguments", {})
    return {
        "type": "function_call",
        "call_id": tool_call.tool_call_id,
        "name": name,
        "arguments": _json_arguments(arguments),
    }


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
    text = _output_text(output) or _output_refusal(output)
    tool_calls = _output_tool_calls(output)
    if not text and not tool_calls and response.error is not None:
        raise ProviderResponseError(
            "OpenAI response failed before producing output",
            detail=json.dumps(response.error.model_dump(), ensure_ascii=False),
        )

    return ChatResponse(
        response_id=response.id,
        model_id=response.model,
        message=Content(
            role=MessageRole.ASSISTANT,
            content=(
                [ContentPart(type=ContentPartType.TEXT, text=text)]
                if text
                else None
            ),
            tool_calls=tool_calls or None,
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


def from_openai_response_stream_event(event: ResponseStreamEvent) -> ChatStreamEvent:
    return OpenAIResponsesStreamNormalizer().map_event(event)


class OpenAIResponsesStreamNormalizer:
    def __init__(self) -> None:
        self._function_calls: dict[str, dict[str, Any]] = {}
        self._completed_item_ids: set[str] = set()

    def map_event(self, event: ResponseStreamEvent) -> ChatStreamEvent:
        return self._map_payload(event.model_dump(mode="json", exclude_none=True))

    def _map_payload(self, payload: dict[str, Any]) -> ChatStreamEvent:
        event_type = payload.get("type")
        if event_type == "response.output_item.added":
            mapped = self._map_output_item_added(payload)
            if mapped is not None:
                return mapped

        if event_type == "response.output_text.delta":
            mapped = self._map_output_text_delta(payload)
            if mapped is not None:
                return mapped

        if event_type == "response.function_call_arguments.delta":
            mapped = self._map_function_arguments_delta(payload)
            if mapped is not None:
                return mapped

        if event_type == "response.function_call_arguments.done":
            mapped = self._map_function_arguments_done(payload)
            if mapped is not None:
                return mapped

        if event_type == "response.output_item.done":
            mapped = self._map_output_item_done(payload)
            if mapped is not None:
                return mapped

        if event_type == "response.completed":
            mapped = self._map_response_completed(payload)
            if mapped is not None:
                return mapped

        response_id = payload.get("id")
        raw_event = event_type or "response.event"
        return ChatStreamEvent(
            event_type=ChatStreamEventType.RAW,
            response_id=response_id if isinstance(response_id, str) else None,
            raw_event=raw_event if isinstance(raw_event, str) else None,
            raw_data=payload,
        )

    def _map_output_item_added(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        event_type = payload.get("type")
        item = payload.get("item")
        if not isinstance(item, dict) or item.get("type") != "function_call":
            return None

        item_id = _string_value(item.get("id"))
        call_id = _string_value(item.get("call_id"))
        name = _string_value(item.get("name"))
        if item_id is not None:
            self._function_calls[item_id] = _without_none(
                {
                    "call_id": call_id,
                    "name": name,
                    "arguments": item.get("arguments") or "",
                }
            )

        return ChatStreamEvent(
            event_type=ChatStreamEventType.TOOL_CALL_START,
            response_id=_string_value(payload.get("response_id")),
            tool_call_id=call_id,
            tool_name=name,
            raw_event=_string_value(event_type),
            raw_data=payload,
            metadata=_without_none(
                {
                    "item_id": item_id,
                    "output_index": payload.get("output_index"),
                }
            ),
        )

    def _map_output_text_delta(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        delta = payload.get("delta")
        if not isinstance(delta, str) or not delta:
            return None

        return ChatStreamEvent(
            event_type=ChatStreamEventType.MESSAGE_DELTA,
            response_id=_string_value(payload.get("response_id")),
            text_delta=delta,
            content_part=ContentPart(type=ContentPartType.TEXT, text=delta),
            raw_event=_string_value(payload.get("type")),
            raw_data=payload,
            metadata=_without_none(
                {
                    "item_id": payload.get("item_id"),
                    "output_index": payload.get("output_index"),
                    "content_index": payload.get("content_index"),
                }
            ),
        )

    def _map_function_arguments_delta(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        delta = payload.get("delta")
        if not isinstance(delta, str) or not delta:
            return None

        item_id = _string_value(payload.get("item_id"))
        call_state = self._function_calls.get(item_id or "", {})
        if item_id is not None:
            current_arguments = str(call_state.get("arguments", ""))
            call_state["arguments"] = current_arguments + delta
            self._function_calls[item_id] = call_state

        return ChatStreamEvent(
            event_type=ChatStreamEventType.TOOL_CALL_DELTA,
            response_id=_string_value(payload.get("response_id")),
            tool_call_id=_string_value(call_state.get("call_id")),
            tool_name=_string_value(call_state.get("name")),
            arguments_delta=delta,
            raw_event=_string_value(payload.get("type")),
            raw_data=payload,
            metadata=_without_none(
                {
                    "item_id": item_id,
                    "output_index": payload.get("output_index"),
                }
            ),
        )

    def _map_function_arguments_done(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        item_id = _string_value(payload.get("item_id"))
        if item_id is None:
            return None

        call_state = self._function_calls.get(item_id, {})
        call_state["arguments"] = payload.get("arguments") or call_state.get(
            "arguments",
            "",
        )
        name = _string_value(payload.get("name"))
        if name is not None:
            call_state["name"] = name
        self._function_calls[item_id] = call_state

        tool_call = self._tool_call_from_state(item_id, call_state)
        if tool_call is None:
            return None

        self._completed_item_ids.add(item_id)
        return ChatStreamEvent(
            event_type=ChatStreamEventType.TOOL_CALL_COMPLETED,
            response_id=_string_value(payload.get("response_id")),
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_call.get("name"),
            tool_call=tool_call,
            raw_event=_string_value(payload.get("type")),
            raw_data=payload,
            metadata=_without_none(
                {
                    "item_id": item_id,
                    "output_index": payload.get("output_index"),
                }
            ),
        )

    def _map_output_item_done(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        item = payload.get("item")
        if not isinstance(item, dict) or item.get("type") != "function_call":
            return None

        item_id = _string_value(item.get("id"))
        if item_id is not None and item_id in self._completed_item_ids:
            return None

        tool_call = _tool_call_from_response_mapping(item)
        if tool_call is None:
            return None

        if item_id is not None:
            self._completed_item_ids.add(item_id)
        return ChatStreamEvent(
            event_type=ChatStreamEventType.TOOL_CALL_COMPLETED,
            response_id=_string_value(payload.get("response_id")),
            tool_call_id=tool_call.tool_call_id,
            tool_name=tool_call.tool_call.get("name"),
            tool_call=tool_call,
            raw_event=_string_value(payload.get("type")),
            raw_data=payload,
            metadata=_without_none(
                {
                    "item_id": item_id,
                    "output_index": payload.get("output_index"),
                }
            ),
        )

    def _map_response_completed(
        self,
        payload: dict[str, Any],
    ) -> ChatStreamEvent | None:
        response = payload.get("response")
        if not isinstance(response, dict):
            return None

        return ChatStreamEvent(
            event_type=ChatStreamEventType.MESSAGE_COMPLETED,
            response_id=_string_value(response.get("id")),
            model_id=_string_value(response.get("model")),
            finish_reason=_string_value(response.get("status")),
            usage=_usage_from_openai_response_mapping(response),
            raw_event=_string_value(payload.get("type")),
            raw_data=payload,
        )

    def _tool_call_from_state(
        self,
        item_id: str,
        call_state: dict[str, Any],
    ) -> ToolCall | None:
        call_id = _string_value(call_state.get("call_id")) or item_id
        name = _string_value(call_state.get("name"))
        arguments = call_state.get("arguments")
        if name is None:
            return None
        if not isinstance(arguments, str):
            arguments = "{}"

        return ToolCall(
            tool_call_id=call_id,
            tool_call={
                "name": name,
                "arguments": _parse_json_arguments(arguments),
            },
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


def _assistant_content(message: Content) -> list[dict[str, Any]]:
    parts = message.content or []
    if not parts:
        return [{"type": "output_text", "text": ""}]

    return [_assistant_content_part(part) for part in parts]


def _assistant_content_part(part: ContentPart) -> dict[str, Any]:
    if part.type is ContentPartType.TEXT:
        if part.text is None:
            raise ChatInputError("Text content part requires text")

        return {"type": "output_text", "text": part.text}

    raise ChatInputError(f"Unsupported assistant content part type: {part.type}")


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


def _output_refusal(output: Any) -> str:
    refusals: list[str] = []
    for item in output:
        item_type = getattr(item, "type", None)
        if item_type != "message":
            continue

        for content_part in getattr(item, "content", []):
            if getattr(content_part, "type", None) == "refusal":
                refusal = getattr(content_part, "refusal", None)
                if isinstance(refusal, str):
                    refusals.append(refusal)

    return "".join(refusals)


def _output_tool_calls(output: Any) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for item in output:
        if getattr(item, "type", None) != "function_call":
            continue

        tool_call = _tool_call_from_response_item(item)
        if tool_call is not None:
            tool_calls.append(tool_call)

    return tool_calls


def _tool_call_from_response_item(item: Any) -> ToolCall | None:
    call_id = getattr(item, "call_id", None)
    name = getattr(item, "name", None)
    arguments = getattr(item, "arguments", None)
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, str):
        arguments = "{}"

    return ToolCall(
        tool_call_id=call_id,
        tool_call={
            "name": name,
            "arguments": _parse_json_arguments(arguments),
        },
    )


def _tool_call_from_response_mapping(item: dict[str, Any]) -> ToolCall | None:
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        item_id = item.get("item_id")
        call_id = item_id if isinstance(item_id, str) else None
    name = item.get("name")
    arguments = item.get("arguments")
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(arguments, str):
        arguments = "{}"

    return ToolCall(
        tool_call_id=call_id,
        tool_call={
            "name": name,
            "arguments": _parse_json_arguments(arguments),
        },
    )


def _parse_json_arguments(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def _json_arguments(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments

    return json.dumps(arguments, ensure_ascii=False)


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


def _usage_from_openai_response_mapping(response: dict[str, Any]) -> ChatUsage | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")

    return ChatUsage(
        prompt_tokens=input_tokens if isinstance(input_tokens, int) else None,
        completion_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        metadata={
            key: value
            for key, value in usage.items()
            if key not in {"input_tokens", "output_tokens", "total_tokens"}
        },
    )


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
