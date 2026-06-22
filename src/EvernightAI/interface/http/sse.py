from collections.abc import AsyncIterable, AsyncIterator

from EvernightAI.core.schema.stream import SSEEvent


def sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    return _iter_sse_response_body(events)


async def _iter_sse_response_body(events: AsyncIterable[SSEEvent]) -> AsyncIterator[str]:
    async for event in events:
        yield format_sse_event(event)


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
