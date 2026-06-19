from collections.abc import AsyncIterator

import pytest

from EvernightAI.core.protocol.stream import SSEProtocol
from EvernightAI.core.schema.stream import SSEEvent


def test_sse_event_supports_wire_id_alias() -> None:
    event = SSEEvent(data='{"delta": "hello"}', id="evt-1", event="message")

    assert event.event_id == "evt-1"
    assert event.model_dump(by_alias=True) == {
        "data": '{"delta": "hello"}',
        "event": "message",
        "id": "evt-1",
        "retry": None,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_sse_protocol_is_async_iterable_of_events() -> None:
    stream: SSEProtocol = FakeSSEStream(
        [
            SSEEvent(data='{"delta": "hello"}', event="message"),
            SSEEvent(data="[DONE]", event="done"),
        ]
    )

    events = [event async for event in stream]

    assert events == [
        SSEEvent(data='{"delta": "hello"}', event="message"),
        SSEEvent(data="[DONE]", event="done"),
    ]


class FakeSSEStream:
    def __init__(self, events: list[SSEEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        for event in self._events:
            yield event
