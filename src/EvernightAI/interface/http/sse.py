from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
import json
from typing import Protocol, runtime_checkable

from fastapi.responses import StreamingResponse
from starlette.types import Send

from EvernightAI.core.error.base import EvernightAIError
from EvernightAI.core.schema.stream import (
    ChatStreamEvent,
    ChatStreamEventType,
    SSEEvent,
)


SSE_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


@runtime_checkable
class _AsyncClosable(Protocol):
    async def aclose(self) -> None: ...


class SSEStreamingResponse(StreamingResponse):
    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            await _close_async_iterable(self.body_iterator)


def sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    return _iter_sse_response_body(events)


def chat_stream_response_body(
    events: AsyncIterable[ChatStreamEvent],
) -> AsyncIterator[str]:
    return _iter_chat_stream_response_body(events)


def chat_stream_response_body_from(
    stream_factory: Callable[[], Awaitable[AsyncIterable[ChatStreamEvent]]],
) -> AsyncIterator[str]:
    return _iter_chat_stream_response_body_from(stream_factory)


async def _iter_sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield format_sse_event(event)
    except EvernightAIError as error:
        yield format_sse_event(error_to_sse_event(error))
    finally:
        await _close_async_iterable(events)


async def _iter_chat_stream_response_body(
    events: AsyncIterable[ChatStreamEvent],
) -> AsyncIterator[str]:
    try:
        async for event in events:
            yield format_sse_event(chat_stream_event_to_sse_event(event))
    except EvernightAIError as error:
        yield format_sse_event(chat_stream_event_to_sse_event(error_to_chat_stream_event(error)))
    finally:
        await _close_async_iterable(events)


async def _iter_chat_stream_response_body_from(
    stream_factory: Callable[[], Awaitable[AsyncIterable[ChatStreamEvent]]],
) -> AsyncIterator[str]:
    stream: AsyncIterable[ChatStreamEvent] | None = None
    try:
        stream = await stream_factory()
        async for event in stream:
            yield format_sse_event(chat_stream_event_to_sse_event(event))
    except EvernightAIError as error:
        yield format_sse_event(chat_stream_event_to_sse_event(error_to_chat_stream_event(error)))
    finally:
        if stream is not None:
            await _close_async_iterable(stream)


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
        data=event.model_dump_json(exclude_none=True),
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
        lines.append(f"event: {_single_line_field(event.event)}")
    if event.event_id is not None:
        lines.append(f"id: {_single_line_field(event.event_id)}")
    if event.retry is not None:
        lines.append(f"retry: {event.retry}")

    data_lines = event.data.splitlines() or [""]
    lines.extend(f"data: {line}" for line in data_lines)
    return "\n".join(lines) + "\n\n"


def _single_line_field(value: str) -> str:
    return value.replace("\r", "").replace("\n", "")


async def _close_async_iterable(events: AsyncIterable[object]) -> None:
    if isinstance(events, _AsyncClosable):
        await events.aclose()
