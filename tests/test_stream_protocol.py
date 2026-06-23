from collections.abc import AsyncIterator

import pytest

from EvernightAI.core.protocol.stream import (
    AgentTraceStreamProtocol,
    ChatStreamProtocol,
    SSEProtocol,
)
from EvernightAI.core.schema.agent import AgentTraceEvent, AgentTraceEventType
from EvernightAI.core.schema.stream import (
    ChatStreamEvent,
    ChatStreamEventType,
    SSEEvent,
)


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


def test_chat_stream_event_can_carry_normalized_text_delta() -> None:
    event = ChatStreamEvent(
        event_type=ChatStreamEventType.MESSAGE_DELTA,
        response_id="resp-1",
        model_id="model-1",
        text_delta="hello",
    )

    assert event.event_type is ChatStreamEventType.MESSAGE_DELTA
    assert event.text_delta == "hello"
    assert event.response_id == "resp-1"


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


@pytest.mark.asyncio
async def test_chat_stream_protocol_is_async_iterable_of_events() -> None:
    stream: ChatStreamProtocol = FakeChatStream(
        [
            ChatStreamEvent(
                event_type=ChatStreamEventType.RAW,
                raw_event="provider.chunk",
                raw_data={"delta": "hello"},
            ),
            ChatStreamEvent(event_type=ChatStreamEventType.DONE),
        ]
    )

    events = [event async for event in stream]

    assert [event.event_type for event in events] == [
        ChatStreamEventType.RAW,
        ChatStreamEventType.DONE,
    ]


@pytest.mark.asyncio
async def test_agent_trace_stream_protocol_is_async_iterable_of_events() -> None:
    stream: AgentTraceStreamProtocol = FakeAgentTraceStream(
        [
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STARTED),
            AgentTraceEvent(event_type=AgentTraceEventType.RUN_STOPPED),
        ]
    )

    events = [event async for event in stream]

    assert [event.event_type for event in events] == [
        AgentTraceEventType.RUN_STARTED,
        AgentTraceEventType.RUN_STOPPED,
    ]


class FakeSSEStream:
    def __init__(self, events: list[SSEEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[SSEEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[SSEEvent]:
        for event in self._events:
            yield event


class FakeChatStream:
    def __init__(self, events: list[ChatStreamEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[ChatStreamEvent]:
        for event in self._events:
            yield event


class FakeAgentTraceStream:
    def __init__(self, events: list[AgentTraceEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[AgentTraceEvent]:
        return self._iter_events()

    async def _iter_events(self) -> AsyncIterator[AgentTraceEvent]:
        for event in self._events:
            yield event
