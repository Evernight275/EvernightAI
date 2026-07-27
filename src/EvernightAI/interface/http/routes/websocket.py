from typing import cast
from uuid import uuid4

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from EvernightAI.core.error.base import (
    AuthorizationError,
    EvernightAIError,
    PermissionDeniedError,
)
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.protocol.stream import AgentTraceStreamProtocol, WebSocketProtocol
from EvernightAI.core.schema.agent import AgentRunRequest
from EvernightAI.core.schema.stream import (
    WebSocketAgentControl,
    WebSocketAgentControlAction,
    WebSocketClientEvent,
    WebSocketError,
    WebSocketHeartbeat,
    WebSocketHello,
    WebSocketMessage,
    WebSocketMessageType,
)
from EvernightAI.core.schema.tool import ToolApprovalDecision
from EvernightAI.interface.http.protocol import (
    AuthorizedHttpInterfaceFactoryProtocol,
    HttpAuthDeviceProtocol,
)
from EvernightAI.interface.http.websocket import (
    ManagedWebSocketConnection,
    WebSocketConnectionManager,
    websocket_accept_subprotocol,
    websocket_query_token,
    websocket_subprotocol_token,
)


router = APIRouter(tags=["websocket"])

WEBSOCKET_CAPABILITIES = [
    WebSocketMessageType.HEARTBEAT,
    WebSocketMessageType.HEARTBEAT_ACK,
    WebSocketMessageType.AGENT_TRACE,
    WebSocketMessageType.TOOL_APPROVAL,
    WebSocketMessageType.CLIENT_EVENT,
    WebSocketMessageType.ERROR,
]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    connection_id = uuid4().hex
    manager = _websocket_manager(websocket)
    connection = await manager.connect(
        websocket,
        connection_id=connection_id,
        subprotocol=websocket_accept_subprotocol(websocket),
    )
    close_code = 1000
    close_reason: str | None = None
    try:
        interface = _websocket_interface(websocket)
        await _send_hello(connection, connection_id=connection.connection_id)
        await _websocket_loop(interface, connection)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        close_code = _close_code_for_error(exc)
        close_reason = _error_type(exc)
        await _send_error(connection, exc)
    finally:
        await manager.disconnect(
            connection,
            code=close_code,
            reason=close_reason,
        )


async def _websocket_loop(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
) -> None:
    while True:
        try:
            message = await connection.receive()
        except ValidationError as exc:
            await _send_error(connection, exc)
            continue

        await _handle_message(interface, connection, message)


async def _handle_message(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
) -> None:
    if message.message_type is WebSocketMessageType.HEARTBEAT:
        await connection.send(
            WebSocketMessage(
                message_type=WebSocketMessageType.HEARTBEAT_ACK,
                correlation_id=message.message_id,
                heartbeat=message.heartbeat or WebSocketHeartbeat(),
            )
        )
        return

    if message.message_type is WebSocketMessageType.HEARTBEAT_ACK:
        return

    if message.message_type is WebSocketMessageType.CLIENT_EVENT:
        await _handle_client_event(interface, connection, message)
        return

    if message.message_type is WebSocketMessageType.TOOL_APPROVAL:
        await _handle_tool_approval(interface, connection, message)
        return

    if message.message_type is WebSocketMessageType.AGENT_CONTROL:
        await _handle_agent_control(interface, connection, message)
        return

    await _send_error(
        connection,
        ValueError(f"Unsupported WebSocket message type: {message.message_type}"),
        correlation_id=message.message_id,
    )


async def _handle_client_event(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
) -> None:
    client_event = message.client_event
    if client_event is None:
        await _send_error(
            connection,
            ValueError("Client event payload is required"),
            correlation_id=message.message_id,
        )
        return

    if client_event.event_name == "agent_run.subscribe":
        await _handle_agent_run_subscribe(
            interface,
            connection,
            message,
            client_event,
        )
        return

    if client_event.event_name == "agent_run.unsubscribe":
        await _handle_agent_run_unsubscribe(connection, message, client_event)
        return

    if client_event.event_name != "agent_run.start":
        await _send_error(
            connection,
            ValueError(
                f"Unsupported client event: {client_event.event_name}"
            ),
            correlation_id=message.message_id,
        )
        return

    try:
        request = AgentRunRequest.model_validate(client_event.payload)
        run_id = _run_id_for_message(message, request)
        task = connection.spawn(
            _start_agent_run_stream(
                interface,
                connection,
                message,
                request,
            )
        )
        if run_id is not None:
            connection.manager.track_run_task(run_id, task)
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _handle_agent_run_subscribe(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    client_event: WebSocketClientEvent,
) -> None:
    payload = client_event.payload
    run_id = payload.get("run_id")
    after_sequence = payload.get("after_sequence", 0)
    if not isinstance(run_id, str) or run_id == "":
        await _send_error(
            connection,
            ValueError("Agent run subscription requires run_id"),
            correlation_id=message.message_id,
        )
        return
    if not isinstance(after_sequence, int) or after_sequence < 0:
        await _send_error(
            connection,
            ValueError("Agent run subscription after_sequence must be >= 0"),
            correlation_id=message.message_id,
        )
        return

    generation = connection.manager.subscription_generation(connection, run_id)
    connection.spawn(
        _subscribe_agent_run(
            interface,
            connection,
            message,
            run_id,
            after_sequence,
            generation,
        )
    )


async def _subscribe_agent_run(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    run_id: str,
    after_sequence: int,
    generation: int,
) -> None:
    try:
        def load_messages(cursor: int) -> list[WebSocketMessage]:
            events = interface.agent_runs.list_trace(
                run_id,
                after_sequence=cursor,
            )
            replay_messages = [
                WebSocketMessage(
                    message_type=WebSocketMessageType.AGENT_TRACE,
                    correlation_id=message.message_id,
                    run_id=run_id,
                    trace_event=event,
                    payload=_trace_payload(event.sequence, replayed=True),
                )
                for event in events
            ]
            subscribed_sequence = (
                events[-1].sequence if events else cursor
            )
            replay_messages.append(
                WebSocketMessage(
                    message_type=WebSocketMessageType.CLIENT_EVENT,
                    correlation_id=message.message_id,
                    run_id=run_id,
                    client_event=WebSocketClientEvent(
                        event_name="agent_run.subscribed",
                        payload={
                            "run_id": run_id,
                            "sequence": subscribed_sequence,
                        },
                    ),
                )
            )
            return replay_messages

        await connection.manager.replay_run(
            connection,
            run_id,
            load_messages,
            after_sequence=after_sequence,
            generation=generation,
        )
    except Exception as exc:
        connection.manager.unsubscribe(connection, run_id)
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _handle_agent_run_unsubscribe(
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    client_event: WebSocketClientEvent,
) -> None:
    run_id = client_event.payload.get("run_id")
    if not isinstance(run_id, str) or run_id == "":
        await _send_error(
            connection,
            ValueError("Agent run unsubscription requires run_id"),
            correlation_id=message.message_id,
        )
        return

    await connection.manager.unsubscribe_run(connection, run_id)
    await connection.send(
        WebSocketMessage(
            message_type=WebSocketMessageType.CLIENT_EVENT,
            correlation_id=message.message_id,
            run_id=run_id,
            client_event=WebSocketClientEvent(
                event_name="agent_run.unsubscribed",
                payload={"run_id": run_id},
            ),
        )
    )


async def _handle_tool_approval(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
) -> None:
    if message.tool_approval is None:
        await _send_error(
            connection,
            ValueError("Tool approval payload is required"),
            correlation_id=message.message_id,
        )
        return

    try:
        task = connection.spawn(
            _resume_agent_run_stream(
                interface,
                connection,
                message,
                message.tool_approval.run_id,
                [message.tool_approval.decision],
            )
        )
        connection.manager.track_run_task(message.tool_approval.run_id, task)
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _handle_agent_control(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
) -> None:
    agent_control = message.agent_control
    if agent_control is None:
        await _send_error(
            connection,
            ValueError("Agent control payload is required"),
            correlation_id=message.message_id,
        )
        return

    if agent_control.action is WebSocketAgentControlAction.PAUSE:
        await _pause_agent_run(interface, connection, message, agent_control)
        return

    if agent_control.action is WebSocketAgentControlAction.CANCEL:
        await _cancel_agent_run(interface, connection, message, agent_control)
        return

    if agent_control.action is WebSocketAgentControlAction.RESUME:
        try:
            task = connection.spawn(
                _resume_agent_run_stream(
                    interface,
                    connection,
                    message,
                    agent_control.run_id,
                    [],
                )
            )
            connection.manager.track_run_task(agent_control.run_id, task)
        except Exception as exc:
            await _send_error(connection, exc, correlation_id=message.message_id)
        return

    await _send_error(
        connection,
        ValueError(
            f"Unsupported agent control action: {agent_control.action}"
        ),
        correlation_id=message.message_id,
    )


async def _pause_agent_run(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    agent_control: WebSocketAgentControl,
) -> None:
    run_id = agent_control.run_id
    try:
        await interface.agent_runs.pause(
            run_id,
            reason=agent_control.reason,
        )
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _cancel_agent_run(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    agent_control: WebSocketAgentControl,
) -> None:
    run_id = agent_control.run_id
    await connection.manager.cancel_run_tasks(run_id)
    try:
        state = await interface.agent_runs.cancel(
            run_id,
            reason=agent_control.reason,
        )
        await _broadcast_control_trace(interface, connection, message, state.run_id)
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _broadcast_control_trace(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    run_id: str,
) -> None:
    state = interface.agent_runs.get_state(run_id)
    if not state.trace:
        return

    connection.manager.subscribe(connection, run_id)
    event = state.trace[-1]
    await connection.manager.broadcast_run(
        run_id,
        WebSocketMessage(
            message_type=WebSocketMessageType.AGENT_TRACE,
            correlation_id=message.message_id,
            run_id=run_id,
            trace_event=event,
            payload=_trace_payload(event.sequence, replayed=False),
        ),
    )


async def _start_agent_run_stream(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    request: AgentRunRequest,
) -> None:
    run_id = _run_id_for_message(message, request)
    if run_id is not None:
        _websocket_manager_for_connection(connection).subscribe(connection, run_id)

    try:
        stream = interface.agent_runs.start_stream(request)
        await _send_trace_stream(
            connection,
            stream,
            correlation_id=message.message_id,
            run_id=run_id,
        )
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _resume_agent_run_stream(
    interface: EvernightInterfaceProtocol,
    connection: ManagedWebSocketConnection,
    message: WebSocketMessage,
    run_id: str,
    approvals: list[ToolApprovalDecision],
) -> None:
    _websocket_manager_for_connection(connection).subscribe(connection, run_id)
    try:
        stream = interface.agent_runs.resume_stream(run_id, approvals)
        await _send_trace_stream(
            connection,
            stream,
            correlation_id=message.message_id,
            run_id=run_id,
        )
    except Exception as exc:
        await _send_error(connection, exc, correlation_id=message.message_id)


async def _send_trace_stream(
    session: WebSocketProtocol,
    stream: AgentTraceStreamProtocol,
    *,
    correlation_id: str | None = None,
    run_id: str | None = None,
) -> None:
    async for event in stream:
        trace_event = (
            event
            if run_id is not None
            else event.model_copy(update={"sequence": None})
        )
        message = WebSocketMessage(
            message_type=WebSocketMessageType.AGENT_TRACE,
            correlation_id=correlation_id,
            run_id=run_id,
            trace_event=trace_event,
            payload=_trace_payload(trace_event.sequence, replayed=False),
        )
        if run_id is not None and isinstance(session, ManagedWebSocketConnection):
            await session.manager.broadcast_run(run_id, message)
        else:
            await session.send(message)


async def _send_hello(
    session: WebSocketProtocol,
    *,
    connection_id: str | None = None,
) -> None:
    await session.send(
        WebSocketMessage(
            message_type=WebSocketMessageType.HELLO,
            message_id=uuid4().hex,
            hello=WebSocketHello(
                connection_id=connection_id or uuid4().hex,
                capabilities=WEBSOCKET_CAPABILITIES,
            ),
        )
    )


async def _send_error(
    session: WebSocketProtocol,
    exc: Exception,
    *,
    correlation_id: str | None = None,
) -> None:
    await session.send(
        WebSocketMessage(
            message_type=WebSocketMessageType.ERROR,
            correlation_id=correlation_id,
            error=WebSocketError(
                error_type=_error_type(exc),
                error_message=str(exc),
                retryable=False,
            ),
        )
    )


def _websocket_interface(websocket: WebSocket) -> EvernightInterfaceProtocol:
    interface = cast(EvernightInterfaceProtocol, websocket.app.state.interface)
    auth_device = cast(
        HttpAuthDeviceProtocol | None,
        getattr(websocket.app.state, "auth_device", None),
    )
    if auth_device is None:
        return interface

    factory = cast(
        AuthorizedHttpInterfaceFactoryProtocol,
        websocket.app.state.authorized_interface_factory,
    )
    token = websocket_subprotocol_token(websocket) or websocket_query_token(websocket)
    if token is not None:
        principal = auth_device.principal(token)
    else:
        principal = auth_device.principal_for_request(cast(Request, websocket))
    return factory(interface, principal)


def _websocket_manager(websocket: WebSocket) -> WebSocketConnectionManager:
    return cast(WebSocketConnectionManager, websocket.app.state.websocket_manager)


def _websocket_manager_for_connection(
    connection: ManagedWebSocketConnection,
) -> WebSocketConnectionManager:
    return connection.manager


def _run_id_for_message(
    message: WebSocketMessage,
    request: AgentRunRequest,
) -> str | None:
    if message.run_id:
        return message.run_id

    run_id = request.metadata.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id

    return None


def _trace_payload(
    sequence: int | None,
    *,
    replayed: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {"replayed": replayed}
    if sequence is not None:
        payload["sequence"] = sequence

    return payload


def _error_type(exc: Exception) -> str:
    if isinstance(exc, EvernightAIError):
        return exc.error_type

    return exc.__class__.__name__


def _close_code_for_error(exc: Exception) -> int:
    if isinstance(exc, (AuthorizationError, PermissionDeniedError)):
        return 1008

    return 1011
