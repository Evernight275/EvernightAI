from collections.abc import AsyncIterator

import pytest

from EvernightAI.core.protocol.stream import (
    AgentTraceStreamProtocol,
    ChatStreamProtocol,
    SSEProtocol,
    WebSocketProtocol,
)
from EvernightAI.core.schema.agent import AgentTraceEvent, AgentTraceEventType
from EvernightAI.core.schema.stream import (
    ChatStreamEvent,
    ChatStreamEventType,
    SSEEvent,
    WebSocketAgentControl,
    WebSocketAgentControlAction,
    WebSocketClientEvent,
    WebSocketError,
    WebSocketHello,
    WebSocketHeartbeat,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketToolApproval,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision, ToolApprovalStatus


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


def test_websocket_message_can_carry_agent_control() -> None:
    message = WebSocketMessage(
        message_type=WebSocketMessageType.AGENT_CONTROL,
        message_id="msg-1",
        run_id="run-1",
        agent_control=WebSocketAgentControl(
            run_id="run-1",
            action=WebSocketAgentControlAction.CANCEL,
            reason="user requested",
        ),
    )

    assert message.model_dump(mode="json", exclude_none=True) == {
        "message_type": "agent_control",
        "message_id": "msg-1",
        "run_id": "run-1",
        "agent_control": {
            "run_id": "run-1",
            "action": "cancel",
            "reason": "user requested",
            "metadata": {},
        },
        "payload": {},
        "metadata": {},
    }


def test_websocket_message_can_carry_hello() -> None:
    message = WebSocketMessage(
        message_type=WebSocketMessageType.HELLO,
        message_id="msg-1",
        hello=WebSocketHello(
            connection_id="conn-1",
            capabilities=[
                WebSocketMessageType.AGENT_TRACE,
                WebSocketMessageType.TOOL_APPROVAL,
            ],
        ),
    )

    assert message.model_dump(mode="json", exclude_none=True) == {
        "message_type": "hello",
        "message_id": "msg-1",
        "hello": {
            "protocol_version": "1",
            "connection_id": "conn-1",
            "capabilities": ["agent_trace", "tool_approval"],
            "metadata": {},
        },
        "payload": {},
        "metadata": {},
    }


def test_websocket_message_can_carry_tool_approval() -> None:
    message = WebSocketMessage(
        message_type=WebSocketMessageType.TOOL_APPROVAL,
        correlation_id="msg-1",
        tool_approval=WebSocketToolApproval(
            run_id="run-1",
            decision=ToolApprovalDecision(
                approval_id="approval-1",
                tool_call_id="tool-1",
                status=ToolApprovalStatus.APPROVED,
            ),
        ),
    )

    assert message.tool_approval is not None
    assert message.tool_approval.decision.status is ToolApprovalStatus.APPROVED
    assert message.model_dump(mode="json", exclude_none=True)["tool_approval"] == {
        "run_id": "run-1",
        "decision": {
            "approval_id": "approval-1",
            "tool_call_id": "tool-1",
            "status": "approved",
            "metadata": {},
        },
        "metadata": {},
    }


def test_websocket_message_can_carry_trace_and_client_events() -> None:
    trace = WebSocketMessage(
        message_type=WebSocketMessageType.AGENT_TRACE,
        run_id="run-1",
        trace_event=AgentTraceEvent(
            event_type=AgentTraceEventType.RUN_STARTED,
            summary="Run started",
        ),
    )
    client_event = WebSocketMessage(
        message_type=WebSocketMessageType.CLIENT_EVENT,
        client_event=WebSocketClientEvent(
            event_name="view_focus",
            payload={"view": "runs"},
        ),
    )

    assert trace.trace_event is not None
    assert trace.trace_event.event_type is AgentTraceEventType.RUN_STARTED
    assert client_event.client_event is not None
    assert client_event.client_event.payload == {"view": "runs"}


def test_websocket_message_can_carry_heartbeat_and_errors() -> None:
    heartbeat = WebSocketMessage(
        message_type=WebSocketMessageType.HEARTBEAT,
        heartbeat=WebSocketHeartbeat(sequence=1, sent_at="2026-07-06T01:00:00Z"),
    )
    error = WebSocketMessage(
        message_type=WebSocketMessageType.ERROR,
        correlation_id="msg-1",
        error=WebSocketError(
            error_type="ControlError",
            error_message="Run is already finished",
        ),
    )

    assert heartbeat.heartbeat is not None
    assert heartbeat.heartbeat.sequence == 1
    assert error.error is not None
    assert error.error.retryable is False


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


@pytest.mark.asyncio
async def test_websocket_protocol_can_send_and_receive_messages() -> None:
    session: WebSocketProtocol = FakeWebSocketSession(
        [
            WebSocketMessage(
                message_type=WebSocketMessageType.AGENT_CONTROL,
                agent_control=WebSocketAgentControl(
                    run_id="run-1",
                    action=WebSocketAgentControlAction.PAUSE,
                ),
            )
        ]
    )

    received = await session.receive()
    await session.send(
        WebSocketMessage(
            message_type=WebSocketMessageType.HEARTBEAT_ACK,
            correlation_id="msg-1",
            heartbeat=WebSocketHeartbeat(sequence=1),
        )
    )
    await session.close(code=1001, reason="client left")

    assert received.agent_control is not None
    assert received.agent_control.action is WebSocketAgentControlAction.PAUSE
    assert isinstance(session, FakeWebSocketSession)
    assert session.sent[0].message_type is WebSocketMessageType.HEARTBEAT_ACK
    assert session.closed == (1001, "client left")


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


class FakeWebSocketSession:
    def __init__(self, received: list[WebSocketMessage]) -> None:
        self._received = received
        self.sent: list[WebSocketMessage] = []
        self.closed: tuple[int, str | None] | None = None

    async def receive(self) -> WebSocketMessage:
        return self._received.pop(0)

    async def send(self, message: WebSocketMessage) -> None:
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason)
