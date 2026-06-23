from collections.abc import AsyncIterable, AsyncIterator
import json

from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.schema.stream import (
    ChatStreamEvent,
    ChatStreamEventType,
    SSEEvent,
)


def sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    return _iter_sse_response_body(events)


def chat_stream_response_body(
    events: AsyncIterable[ChatStreamEvent],
) -> AsyncIterator[str]:
    return _iter_chat_stream_response_body(events)


async def _iter_sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield format_sse_event(event)
    except EvernightAIError as error:
        yield format_sse_event(error_to_sse_event(error))


async def _iter_chat_stream_response_body(
    events: AsyncIterable[ChatStreamEvent],
) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield format_sse_event(chat_stream_event_to_sse_event(event))
    except EvernightAIError as error:
        yield format_sse_event(chat_stream_event_to_sse_event(error_to_chat_stream_event(error)))


def chat_stream_event_to_sse_event(event: ChatStreamEvent) -> SSEEvent:
    if event.event_type is ChatStreamEventType.DONE:
        return SSEEvent(data="[DONE]", event="done")

    if event.event_type is ChatStreamEventType.RAW:
        return SSEEvent(
            data=json.dumps(
                event.raw_data or {},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            event=event.raw_event or "provider.raw",
            id=event.response_id,
        )

    return SSEEvent(
        data=event.model_dump_json(),
        event=f"chat.{event.event_type.value}",
        id=event.response_id,
    )


def error_to_chat_stream_event(error: EvernightAIError) -> ChatStreamEvent:
    return ChatStreamEvent(
        event_type=ChatStreamEventType.ERROR,
        error_type=error.error_type,
        error_message=str(error),
        metadata={
            "detail": error.detail,
        },
    )


def error_to_sse_event(error: EvernightAIError) -> SSEEvent:
    return SSEEvent(
        event="error",
        data=json.dumps(
            {
                "error": {
                    "type": error.error_type,
                    "message": str(error),
                    "detail": error.detail,
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def format_sse_event(event: SSEEvent) -> str:
    lines: list[str] = []
    if event.event is not None:
        lines.append(f"event: {event.event}")
    if event.event_id is not None:
        lines.append(f"id: {event.event_id}")
    if event.retry is not None:
        lines.append(f"retry: {event.retry}")

    data_lines = event.data.splitlines() or [""]
    lines.extend(f"data: {line}" for line in data_lines)
    return "\n".join(lines) + "\n\n"
