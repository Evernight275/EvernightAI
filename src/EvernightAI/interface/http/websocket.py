import asyncio
import base64
import binascii
from collections import defaultdict
from collections.abc import Callable, Coroutine, Iterable
from contextlib import suppress
from time import monotonic
from typing import Final
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from EvernightAI.core.protocol.stream import WebSocketProtocol
from EvernightAI.core.schema.stream import (
    WebSocketHeartbeat,
    WebSocketMessage,
    WebSocketMessageType,
)


WEBSOCKET_SEND_QUEUE_SIZE: Final = 100
WEBSOCKET_HEARTBEAT_INTERVAL_SECONDS: Final = 30.0
WEBSOCKET_HEARTBEAT_TIMEOUT_SECONDS: Final = 90.0
WEBSOCKET_HEARTBEAT_TIMEOUT_CLOSE_CODE: Final = 4000
WEBSOCKET_SUBPROTOCOL: Final = "evernight.realtime"
WEBSOCKET_API_KEY_SUBPROTOCOL_PREFIX: Final = "evernight.api_key."
WEBSOCKET_ACCESS_TOKEN_SUBPROTOCOL_PREFIX: Final = "evernight.access_token."


class ManagedWebSocketConnection(WebSocketProtocol):
    def __init__(
        self,
        connection_id: str,
        websocket: WebSocket,
        manager: "WebSocketConnectionManager",
        *,
        send_queue_size: int = WEBSOCKET_SEND_QUEUE_SIZE,
        heartbeat_interval_seconds: float = WEBSOCKET_HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_timeout_seconds: float = WEBSOCKET_HEARTBEAT_TIMEOUT_SECONDS,
    ) -> None:
        self.connection_id = connection_id
        self.manager = manager
        self._websocket = websocket
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._last_received_at = monotonic()
        self._heartbeat_sequence = 0
        self._send_queue: asyncio.Queue[WebSocketMessage | None] = asyncio.Queue(
            maxsize=send_queue_size
        )
        self._sender_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    async def start(self) -> None:
        self._sender_task = asyncio.create_task(self._send_loop())
        self.spawn(self._heartbeat_loop())

    async def receive(self) -> WebSocketMessage:
        raw_message = await self._websocket.receive_json()
        self.mark_received()
        return WebSocketMessage.model_validate(raw_message)

    async def send(self, message: WebSocketMessage) -> None:
        if self._closed:
            raise WebSocketDisconnect()

        await self._send_queue.put(message)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        if self._closed:
            return

        self._closed = True
        current_task = asyncio.current_task()
        for task in list(self._tasks):
            if task is current_task:
                continue
            task.cancel()
        await self._send_queue.put(None)
        if self._sender_task is not None:
            with suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                await self._sender_task
        for task in list(self._tasks):
            if task is current_task:
                continue
            with suppress(asyncio.CancelledError):
                await task
        with suppress(RuntimeError, WebSocketDisconnect):
            await self._websocket.close(code=code, reason=reason)

    def spawn(
        self,
        awaitable: Coroutine[object, object, None],
    ) -> asyncio.Task[None] | None:
        if self._closed:
            return None

        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def mark_received(self) -> None:
        self._last_received_at = monotonic()

    async def _send_loop(self) -> None:
        while True:
            message = await self._send_queue.get()
            if message is None:
                return

            await self._websocket.send_json(
                message.model_dump(mode="json", exclude_none=True)
            )

    async def _heartbeat_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            if self._closed:
                return

            age_seconds = monotonic() - self._last_received_at
            if age_seconds > self._heartbeat_timeout_seconds:
                await self.close(
                    code=WEBSOCKET_HEARTBEAT_TIMEOUT_CLOSE_CODE,
                    reason="heartbeat_timeout",
                )
                return

            self._heartbeat_sequence += 1
            await self.send(
                WebSocketMessage(
                    message_type=WebSocketMessageType.HEARTBEAT,
                    message_id=uuid4().hex,
                    heartbeat=WebSocketHeartbeat(sequence=self._heartbeat_sequence),
                )
            )


class WebSocketConnectionManager:
    def __init__(
        self,
        *,
        heartbeat_interval_seconds: float = WEBSOCKET_HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_timeout_seconds: float = WEBSOCKET_HEARTBEAT_TIMEOUT_SECONDS,
    ) -> None:
        self._connections: dict[str, ManagedWebSocketConnection] = {}
        self._subscriptions_by_run: dict[str, set[str]] = defaultdict(set)
        self._runs_by_connection: dict[str, set[str]] = defaultdict(set)
        self._subscription_sequences: dict[tuple[str, str], int] = {}
        self._subscription_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._subscription_generations: dict[tuple[str, str], int] = {}
        self._tasks_by_run: dict[str, set[asyncio.Task[None]]] = defaultdict(set)
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._heartbeat_timeout_seconds = heartbeat_timeout_seconds

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(
        self,
        websocket: WebSocket,
        *,
        connection_id: str,
        subprotocol: str | None = None,
    ) -> ManagedWebSocketConnection:
        await websocket.accept(subprotocol=subprotocol)
        connection = ManagedWebSocketConnection(
            connection_id,
            websocket,
            self,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
            heartbeat_timeout_seconds=self._heartbeat_timeout_seconds,
        )
        self._connections[connection.connection_id] = connection
        await connection.start()
        return connection

    async def disconnect(
        self,
        connection: ManagedWebSocketConnection,
        *,
        code: int = 1000,
        reason: str | None = None,
    ) -> None:
        self.unsubscribe_all(connection)
        self._connections.pop(connection.connection_id, None)
        try:
            await connection.close(code=code, reason=reason)
        finally:
            self._discard_connection_subscription_state(connection.connection_id)

    def subscribe(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> None:
        self._subscriptions_by_run[run_id].add(connection.connection_id)
        self._runs_by_connection[connection.connection_id].add(run_id)
        key = (connection.connection_id, run_id)
        self._subscription_sequences[key] = max(
            self._subscription_sequences.get(key, 0),
            after_sequence,
        )

    def unsubscribe(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
    ) -> None:
        key = (connection.connection_id, run_id)
        self._subscription_generations[key] = (
            self._subscription_generations.get(key, 0) + 1
        )
        connection_ids = self._subscriptions_by_run.get(run_id)
        if connection_ids is not None:
            connection_ids.discard(connection.connection_id)
            if not connection_ids:
                self._subscriptions_by_run.pop(run_id, None)

        run_ids = self._runs_by_connection.get(connection.connection_id)
        if run_ids is not None:
            run_ids.discard(run_id)
            if not run_ids:
                self._runs_by_connection.pop(connection.connection_id, None)

        self._subscription_sequences.pop(key, None)
        self._discard_subscription_lock_if_unused(key)

    def unsubscribe_all(self, connection: ManagedWebSocketConnection) -> None:
        run_ids = list(self._runs_by_connection.get(connection.connection_id, set()))
        for run_id in run_ids:
            self.unsubscribe(connection, run_id)

    async def unsubscribe_run(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
    ) -> None:
        key = (connection.connection_id, run_id)
        lock = self._subscription_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                self.unsubscribe(connection, run_id)
        finally:
            self._discard_subscription_lock_if_unused(key)

    async def replay_run(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
        load_messages: Callable[[int], Iterable[WebSocketMessage]],
        *,
        after_sequence: int = 0,
        generation: int | None = None,
    ) -> None:
        key = (connection.connection_id, run_id)
        lock = self._subscription_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                if generation is not None and generation != (
                    self._subscription_generations.get(key, 0)
                ):
                    return
                self.subscribe(
                    connection,
                    run_id,
                    after_sequence=after_sequence,
                )
                cursor = self._subscription_sequences[key]
                for message in load_messages(cursor):
                    await self._send_subscription_message(
                        connection,
                        run_id,
                        message,
                    )
        finally:
            self._discard_subscription_lock_if_unused(key)

    async def broadcast_run(
        self,
        run_id: str,
        message: WebSocketMessage,
    ) -> None:
        connection_ids = list(self._subscriptions_by_run.get(run_id, set()))
        for connection_id in connection_ids:
            connection = self._connections.get(connection_id)
            if connection is None:
                continue

            key = (connection_id, run_id)
            lock = self._subscription_locks.setdefault(key, asyncio.Lock())
            try:
                async with lock:
                    if not self._is_subscribed(connection_id, run_id):
                        continue
                    await self._send_subscription_message(
                        connection,
                        run_id,
                        message,
                    )
            finally:
                self._discard_subscription_lock_if_unused(key)

    def track_run_task(
        self,
        run_id: str,
        task: asyncio.Task[None] | None,
    ) -> None:
        if task is None:
            return

        self._tasks_by_run[run_id].add(task)
        task.add_done_callback(lambda done: self._discard_run_task(run_id, done))

    async def cancel_run_tasks(self, run_id: str) -> None:
        tasks = list(self._tasks_by_run.pop(run_id, set()))
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    def _discard_run_task(
        self,
        run_id: str,
        task: asyncio.Task[None],
    ) -> None:
        tasks = self._tasks_by_run.get(run_id)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._tasks_by_run.pop(run_id, None)

    def subscription_generation(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
    ) -> int:
        return self._subscription_generations.get((connection.connection_id, run_id), 0)

    async def _send_subscription_message(
        self,
        connection: ManagedWebSocketConnection,
        run_id: str,
        message: WebSocketMessage,
    ) -> None:
        key = (connection.connection_id, run_id)
        sequence = _trace_message_sequence(message)
        if sequence is not None:
            cursor = self._subscription_sequences.get(key, 0)
            if sequence <= cursor:
                return

        await connection.send(message)
        if sequence is not None and self._is_subscribed(connection.connection_id, run_id):
            self._subscription_sequences[key] = sequence

    def _is_subscribed(self, connection_id: str, run_id: str) -> bool:
        return connection_id in self._subscriptions_by_run.get(run_id, set())

    def _discard_subscription_lock_if_unused(
        self,
        key: tuple[str, str],
    ) -> None:
        lock = self._subscription_locks.get(key)
        if (
            lock is not None
            and not lock.locked()
            and not self._is_subscribed(key[0], key[1])
        ):
            self._subscription_locks.pop(key, None)

    def _discard_connection_subscription_state(self, connection_id: str) -> None:
        for mapping in (
            self._subscription_sequences,
            self._subscription_locks,
            self._subscription_generations,
        ):
            for key in [key for key in mapping if key[0] == connection_id]:
                mapping.pop(key, None)


def websocket_query_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("access_token")
    if token:
        return token

    api_key = websocket.query_params.get("api_key")
    if api_key:
        return api_key

    return None


def _trace_message_sequence(message: WebSocketMessage) -> int | None:
    if message.message_type is not WebSocketMessageType.AGENT_TRACE:
        return None
    if message.trace_event is not None and message.trace_event.sequence is not None:
        return message.trace_event.sequence

    sequence = message.payload.get("sequence")
    if isinstance(sequence, int) and sequence > 0:
        return sequence

    return None


def websocket_accept_subprotocol(websocket: WebSocket) -> str | None:
    if WEBSOCKET_SUBPROTOCOL in _websocket_subprotocols(websocket):
        return WEBSOCKET_SUBPROTOCOL

    return None


def websocket_subprotocol_token(websocket: WebSocket) -> str | None:
    for protocol in _websocket_subprotocols(websocket):
        for prefix in (
            WEBSOCKET_API_KEY_SUBPROTOCOL_PREFIX,
            WEBSOCKET_ACCESS_TOKEN_SUBPROTOCOL_PREFIX,
        ):
            if protocol.startswith(prefix):
                return _decode_websocket_auth_value(protocol.removeprefix(prefix))

    return None


def _websocket_subprotocols(websocket: WebSocket) -> list[str]:
    header = websocket.headers.get("sec-websocket-protocol")
    if header is None:
        return []

    return [part.strip() for part in header.split(",") if part.strip()]


def _decode_websocket_auth_value(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{value}{padding}")
        return decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""
