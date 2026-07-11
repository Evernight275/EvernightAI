import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message

from EvernightAI.core.error.provider import ProviderUnavailableError
from EvernightAI.core.schema.stream import (
    ChatStreamEvent,
    ChatStreamEventType,
    SSEEvent,
)
from EvernightAI.interface.http.sse import (
    SSE_RESPONSE_HEADERS,
    SSEStreamingResponse,
    chat_stream_response_body,
    format_sse_event,
    sse_response_body,
)


def test_format_sse_event_encodes_all_fields_and_multiline_data() -> None:
    event = SSEEvent(
        data="你好\nsecond line",
        event="message",
        id="event-1",
        retry=1500,
    )

    assert format_sse_event(event) == (
        "event: message\n"
        "id: event-1\n"
        "retry: 1500\n"
        "data: 你好\n"
        "data: second line\n\n"
    )


def test_format_sse_event_encodes_empty_data() -> None:
    assert format_sse_event(SSEEvent(data="")) == "data: \n\n"


def test_format_sse_event_prevents_field_line_injection() -> None:
    event = SSEEvent(
        data="payload",
        event="message\nevent: injected",
        id="event-1\nid: injected",
    )

    assert format_sse_event(event) == (
        "event: messageevent: injected\n"
        "id: event-1id: injected\n"
        "data: payload\n\n"
    )


@pytest.mark.asyncio
async def test_chat_stream_preserves_events_before_an_error() -> None:
    async def events() -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(
            event_type=ChatStreamEventType.MESSAGE_DELTA,
            text_delta="partial",
        )
        raise ProviderUnavailableError("provider stream failed")

    chunks = [chunk async for chunk in chat_stream_response_body(events())]

    assert [chunk.splitlines()[0] for chunk in chunks] == [
        "event: chat.message_delta",
        "event: chat.error",
    ]
    assert all("event: done" not in chunk for chunk in chunks)


@pytest.mark.asyncio
async def test_sse_streaming_response_sends_before_source_completes() -> None:
    release = asyncio.Event()
    first_body_sent = asyncio.Event()
    source_completed = False
    body_chunks: list[bytes] = []

    async def events() -> AsyncIterator[SSEEvent]:
        nonlocal source_completed
        yield SSEEvent(data="first", event="message")
        await release.wait()
        source_completed = True
        yield SSEEvent(data="second", event="message")

    async def send(message: Message) -> None:
        if message["type"] != "http.response.body":
            return
        body = message.get("body", b"")
        if isinstance(body, bytes) and body:
            body_chunks.append(body)
            first_body_sent.set()

    async def receive() -> Message:
        return await asyncio.Future()

    response = SSEStreamingResponse(
        sse_response_body(events()),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )
    response_task = asyncio.create_task(
        response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )
    )

    await asyncio.wait_for(first_body_sent.wait(), timeout=1)
    assert not source_completed
    assert not response_task.done()

    release.set()
    await asyncio.wait_for(response_task, timeout=1)

    assert b"".join(body_chunks) == (
        b"event: message\ndata: first\n\nevent: message\ndata: second\n\n"
    )


@pytest.mark.asyncio
async def test_sse_streaming_response_closes_source_on_disconnect() -> None:
    source_closed = asyncio.Event()

    async def events() -> AsyncIterator[SSEEvent]:
        try:
            yield SSEEvent(data="first", event="message")
            await asyncio.Future()
        finally:
            source_closed.set()

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            raise OSError("client disconnected")

    async def receive() -> Message:
        return await asyncio.Future()

    response = SSEStreamingResponse(
        sse_response_body(events()),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )

    with pytest.raises(ClientDisconnect):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    await asyncio.wait_for(source_closed.wait(), timeout=1)
