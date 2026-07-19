import asyncio
import json
import logging
import re
import sys
from collections.abc import Callable
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    suppress,
)
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, TextIO
from urllib.parse import urlparse

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolResult,
    ServerNotification,
    TextContent,
    Tool as McpTool,
    ToolListChangedNotification,
)

from EvernightAI.core.error.tool import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolStateError,
)
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolRegisterProtocol,
    ToolRegistration,
    ToolSourceProtocol,
)
from EvernightAI.core.schema.tool import (
    ToolApprovalMode,
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


LOGGER = logging.getLogger("EvernightAI.infra.tool.mcp")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_TOOL_NAME_LENGTH = 64

McpReadStream = MemoryObjectReceiveStream[SessionMessage | Exception]
McpWriteStream = MemoryObjectSendStream[SessionMessage]
McpTransportContext = AbstractAsyncContextManager[tuple[McpReadStream, McpWriteStream]]
McpTransportFactory = Callable[[], McpTransportContext]
ToolListChangedHandler = Callable[[], None]
McpFailureHandler = Callable[[Exception], None]


class McpClientProtocol(Protocol):
    async def connect(self) -> None: ...

    async def list_tools(self) -> list[McpTool]: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult: ...

    @property
    def transport_name(self) -> str: ...

    @property
    def supports_tool_list_changes(self) -> bool: ...

    def set_tool_list_changed_handler(
        self,
        handler: ToolListChangedHandler | None,
    ) -> None: ...

    def set_failure_handler(self, handler: McpFailureHandler | None) -> None: ...

    async def close(self) -> None: ...


class _McpSessionClient(McpClientProtocol):
    def __init__(
        self,
        *,
        transport_factory: McpTransportFactory,
        transport_name: str,
        timeout_seconds: float,
    ) -> None:
        self._transport_factory = transport_factory
        self._transport_name = transport_name
        self._timeout_seconds = timeout_seconds
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._supports_tool_list_changes = False
        self._tool_list_changed_handler: ToolListChangedHandler | None = None
        self._failure_handler: McpFailureHandler | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        try:
            read_stream, write_stream = await stack.enter_async_context(
                self._transport_factory()
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                    message_handler=self._handle_message,
                )
            )
            initialization = await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

        tools_capability = initialization.capabilities.tools
        self._supports_tool_list_changes = bool(
            tools_capability is not None and tools_capability.listChanged
        )
        self._stack = stack
        self._session = session

    async def list_tools(self) -> list[McpTool]:
        session = self._require_session()
        tools: list[McpTool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            result = await session.list_tools(cursor=cursor)
            tools.extend(result.tools)
            cursor = result.nextCursor
            if cursor is None:
                return tools
            if cursor in seen_cursors:
                raise ToolConfigurationError(
                    "The MCP server returned a repeated tools cursor"
                )
            seen_cursors.add(cursor)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult:
        return await self._require_session().call_tool(
            name,
            arguments,
            read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
        )

    @property
    def transport_name(self) -> str:
        return self._transport_name

    @property
    def supports_tool_list_changes(self) -> bool:
        return self._supports_tool_list_changes

    def set_tool_list_changed_handler(
        self,
        handler: ToolListChangedHandler | None,
    ) -> None:
        self._tool_list_changed_handler = handler

    def set_failure_handler(self, handler: McpFailureHandler | None) -> None:
        self._failure_handler = handler

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        self._supports_tool_list_changes = False
        if stack is not None:
            await stack.aclose()

    async def _handle_message(
        self,
        message: object,
    ) -> None:
        if isinstance(message, ServerNotification) and isinstance(
            message.root,
            ToolListChangedNotification,
        ):
            handler = self._tool_list_changed_handler
            if handler is not None:
                handler()
        elif isinstance(message, Exception):
            LOGGER.warning(
                "MCP transport reported an error",
                extra={"error_type": message.__class__.__name__},
            )
            handler = self._failure_handler
            if handler is not None:
                handler(message)

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise ToolStateError("The MCP client is not connected")
        return self._session


class McpStreamableHttpClient(_McpSessionClient):
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        _validate_url(url)
        if http_client is not None and headers:
            raise ToolConfigurationError(
                "MCP headers must be configured on the supplied HTTP client"
            )
        super().__init__(
            transport_factory=lambda: _streamable_http_transport(
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
                http_client=http_client,
            ),
            transport_name="streamable_http",
            timeout_seconds=timeout_seconds,
        )


class McpSseClient(_McpSessionClient):
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        sse_read_timeout_seconds: float = 300.0,
        httpx_client_factory: McpHttpClientFactory | None = None,
    ) -> None:
        _validate_url(url)
        super().__init__(
            transport_factory=lambda: _sse_transport(
                url=url,
                headers=headers,
                timeout_seconds=timeout_seconds,
                sse_read_timeout_seconds=sse_read_timeout_seconds,
                httpx_client_factory=(
                    httpx_client_factory or _create_no_redirect_http_client
                ),
            ),
            transport_name="sse",
            timeout_seconds=timeout_seconds,
        )


class McpStdioClient(_McpSessionClient):
    def __init__(
        self,
        *,
        command: str,
        args: list[str] | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        errlog: TextIO | None = None,
    ) -> None:
        if not command:
            raise ToolConfigurationError("MCP stdio command must not be empty")
        parameters = StdioServerParameters(
            command=command,
            args=list(args or []),
            cwd=cwd,
            env=dict(env) if env is not None else None,
        )
        super().__init__(
            transport_factory=lambda: _stdio_transport(
                parameters,
                errlog=errlog or sys.stderr,
            ),
            transport_name="stdio",
            timeout_seconds=timeout_seconds,
        )


class McpToolSource(ToolSourceProtocol):
    def __init__(
        self,
        *,
        server_id: str,
        namespace: str,
        client: McpClientProtocol,
        allowed_tools: set[str] | None = None,
        blocked_tools: set[str] | None = None,
        max_tools: int = 100,
        max_definition_chars: int = 12000,
        requires_approval: bool = True,
        max_output_chars: int = 20000,
        watch_tool_changes: bool = True,
        refresh_interval_seconds: float | None = None,
        refresh_retry_seconds: float = 5.0,
    ) -> None:
        _validate_name(namespace, label="MCP namespace")
        if max_output_chars < 1:
            raise ToolConfigurationError("MCP max_output_chars must be positive")
        if max_tools < 1:
            raise ToolConfigurationError("MCP max_tools must be positive")
        if max_definition_chars < 1:
            raise ToolConfigurationError("MCP max_definition_chars must be positive")
        if refresh_interval_seconds is not None and refresh_interval_seconds <= 0:
            raise ToolConfigurationError(
                "MCP refresh_interval_seconds must be positive"
            )
        if refresh_retry_seconds <= 0:
            raise ToolConfigurationError("MCP refresh_retry_seconds must be positive")

        self._server_id = server_id
        self._source_id = f"mcp:{server_id}"
        self._namespace = namespace
        self._client = client
        self._allowed_tools = allowed_tools
        self._blocked_tools = blocked_tools or set()
        self._max_tools = max_tools
        self._max_definition_chars = max_definition_chars
        self._requires_approval = requires_approval
        self._max_output_chars = max_output_chars
        self._watch_tool_changes = watch_tool_changes
        self._refresh_interval_seconds = refresh_interval_seconds
        self._refresh_retry_seconds = refresh_retry_seconds
        self._register: ToolRegisterProtocol | None = None
        self._registered_names: list[str] = []
        self._refresh_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._ready = False

    async def load(self, register: ToolRegisterProtocol) -> None:
        if self._ready:
            return

        overlap = (self._allowed_tools or set()) & self._blocked_tools
        if overlap:
            raise ToolConfigurationError(
                "MCP tools cannot be both allowed and blocked",
                detail=", ".join(sorted(overlap)),
            )

        self._register = register
        self._client.set_tool_list_changed_handler(self._request_refresh)
        self._client.set_failure_handler(self._handle_client_failure)
        try:
            await self._client.connect()
            await self.refresh()
        except BaseException as exc:
            register.replace_source(self._source_id, [])
            self._register = None
            self._client.set_tool_list_changed_handler(None)
            self._client.set_failure_handler(None)
            await self._client.close()
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, ToolConfigurationError):
                raise
            raise ToolConfigurationError(
                f"Could not load MCP tools from {self._server_id}",
                detail=str(exc),
                cause=exc,
            ) from exc

        self._ready = True
        self._start_refresh_task()
        if self._watch_tool_changes and not self._client.supports_tool_list_changes:
            LOGGER.info(
                "MCP server does not advertise tool list change notifications",
                extra={
                    "mcp_server_id": self._server_id,
                    "mcp_transport": self._client.transport_name,
                },
            )
        LOGGER.info(
            "MCP tool source loaded",
            extra={
                "mcp_server_id": self._server_id,
                "mcp_transport": self._client.transport_name,
                "mcp_tool_count": len(self._registered_names),
            },
        )

    async def refresh(self) -> None:
        register = self._register
        if register is None:
            raise ToolStateError(f"The MCP source {self._server_id} is not loaded")

        async with self._refresh_lock:
            try:
                remote_tools = await self._client.list_tools()
                selected_tools = self._select_tools(remote_tools)
                registrations = [
                    ToolRegistration(
                        tool=self._definition(tool),
                        executor=self._executor(tool.name),
                    )
                    for tool in selected_tools
                ]
                register.replace_source(self._source_id, registrations)
            except ToolStateError as exc:
                self._ready = False
                raise ToolConfigurationError(
                    str(exc),
                    detail=exc.detail or str(exc),
                    cause=exc,
                ) from exc
            except Exception:
                self._ready = False
                raise
            self._registered_names = [
                registration.tool.name for registration in registrations
            ]
            self._ready = True
            LOGGER.info(
                "MCP tool source refreshed",
                extra={
                    "mcp_server_id": self._server_id,
                    "mcp_transport": self._client.transport_name,
                    "mcp_tool_count": len(self._registered_names),
                },
            )

    def is_ready(self) -> bool:
        return self._ready

    async def close(self) -> None:
        task = self._refresh_task
        self._refresh_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._client.set_tool_list_changed_handler(None)
        self._client.set_failure_handler(None)
        if self._register is not None:
            self._register.replace_source(self._source_id, [])
        self._register = None
        self._registered_names.clear()
        self._ready = False
        await self._client.close()

    def _start_refresh_task(self) -> None:
        if not self._watch_tool_changes and self._refresh_interval_seconds is None:
            return
        if self._refresh_task is None:
            self._refresh_task = asyncio.create_task(
                self._refresh_loop(),
                name=f"mcp-tool-refresh:{self._server_id}",
            )

    def _request_refresh(self) -> None:
        if self._watch_tool_changes:
            self._refresh_event.set()

    def _handle_client_failure(self, _error: Exception) -> None:
        self._ready = False
        if self._refresh_task is not None:
            self._refresh_event.set()

    async def _refresh_loop(self) -> None:
        while True:
            interval = self._refresh_interval_seconds
            if interval is None:
                await self._refresh_event.wait()
            else:
                try:
                    await asyncio.wait_for(self._refresh_event.wait(), timeout=interval)
                except TimeoutError:
                    pass
            self._refresh_event.clear()
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ready = False
                LOGGER.error(
                    "MCP tool source refresh failed",
                    extra={
                        "mcp_server_id": self._server_id,
                        "mcp_transport": self._client.transport_name,
                        "error_type": exc.__class__.__name__,
                    },
                    exc_info=exc,
                )
                await asyncio.sleep(self._refresh_retry_seconds)
                self._refresh_event.set()

    def _select_tools(self, tools: list[McpTool]) -> list[McpTool]:
        if len(tools) > self._max_tools:
            raise ToolConfigurationError(
                f"The MCP server {self._server_id} returned too many tools",
                detail=f"maximum {self._max_tools}, received {len(tools)}",
            )
        remote_names = [tool.name for tool in tools]
        if len(remote_names) != len(set(remote_names)):
            raise ToolConfigurationError(
                f"The MCP server {self._server_id} returned duplicate tool names"
            )

        if self._allowed_tools is not None:
            missing = self._allowed_tools - set(remote_names)
            if missing:
                raise ToolConfigurationError(
                    f"The MCP server {self._server_id} did not provide allowed tools",
                    detail=", ".join(sorted(missing)),
                )

        return [
            tool
            for tool in tools
            if tool.name not in self._blocked_tools
            and (self._allowed_tools is None or tool.name in self._allowed_tools)
        ]

    def _definition(self, tool: McpTool) -> ToolDefinition:
        _validate_name(tool.name, label="MCP tool name")
        definition_chars = len(tool.description or "") + len(
            json.dumps(tool.inputSchema, ensure_ascii=False, separators=(",", ":"))
        )
        if definition_chars > self._max_definition_chars:
            raise ToolConfigurationError(
                f"The MCP tool {tool.name} definition is too large",
                detail=(
                    f"maximum {self._max_definition_chars}, received {definition_chars}"
                ),
            )
        local_name = f"{self._namespace}__{tool.name}"
        _validate_name(local_name, label="Namespaced MCP tool name")
        return ToolDefinition(
            name=local_name,
            description=tool.description or f"Remote MCP tool {tool.name}",
            parameters_schema=tool.inputSchema,
            permissions=[ToolPermission.NETWORK, ToolPermission.EXTERNAL_API],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=self._requires_approval,
            approval_mode=(
                ToolApprovalMode.REQUIRED
                if self._requires_approval
                else ToolApprovalMode.NEVER
            ),
            metadata={
                "source": "mcp",
                "remote": True,
                "mcp_server_id": self._server_id,
                "mcp_tool_name": tool.name,
                "mcp_transport": self._client.transport_name,
            },
        )

    def _executor(self, remote_name: str) -> ToolExecutorProtocol:
        async def execute(arguments: dict[str, Any]) -> dict[str, Any]:
            result = await self._client.call_tool(remote_name, arguments)
            if result.isError:
                raise ToolExecutionError(
                    f"Remote MCP tool {remote_name} reported an error",
                    detail=_result_detail(result, self._max_output_chars),
                )
            return _result_payload(result, self._max_output_chars)

        return execute


@asynccontextmanager
async def _streamable_http_transport(
    *,
    url: str,
    headers: dict[str, str] | None,
    timeout_seconds: float,
    http_client: httpx.AsyncClient | None,
):
    async with AsyncExitStack() as stack:
        client = http_client
        if client is None:
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=headers,
                    timeout=httpx.Timeout(
                        timeout_seconds,
                        read=max(timeout_seconds, 300.0),
                    ),
                    follow_redirects=False,
                )
            )
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamable_http_client(url, http_client=client)
        )
        yield read_stream, write_stream


@asynccontextmanager
async def _sse_transport(
    *,
    url: str,
    headers: dict[str, str] | None,
    timeout_seconds: float,
    sse_read_timeout_seconds: float,
    httpx_client_factory: McpHttpClientFactory,
):
    async with sse_client(
        url,
        headers=headers,
        timeout=timeout_seconds,
        sse_read_timeout=sse_read_timeout_seconds,
        httpx_client_factory=httpx_client_factory,
    ) as streams:
        yield streams


@asynccontextmanager
async def _stdio_transport(
    parameters: StdioServerParameters,
    *,
    errlog: TextIO,
):
    async with stdio_client(parameters, errlog=errlog) as streams:
        yield streams


def _create_no_redirect_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
    )


def _result_payload(result: CallToolResult, max_chars: int) -> dict[str, Any]:
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= max_chars:
        return payload
    return {
        "content": serialized[:max_chars],
        "truncated": True,
        "original_chars": len(serialized),
    }


def _result_detail(result: CallToolResult, max_chars: int) -> str:
    text = "\n".join(
        item.text for item in result.content if isinstance(item, TextContent)
    )
    if not text:
        text = json.dumps(
            result.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
        )
    return text[:max_chars]


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolConfigurationError("MCP URL must be an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ToolConfigurationError("MCP URL must not contain credentials")


def _validate_name(name: str, *, label: str) -> None:
    if not name or _TOOL_NAME_PATTERN.fullmatch(name) is None:
        raise ToolConfigurationError(
            f"{label} may contain only letters, numbers, underscores, and hyphens"
        )
    if len(name) > _MAX_TOOL_NAME_LENGTH:
        raise ToolConfigurationError(
            f"{label} must not exceed {_MAX_TOOL_NAME_LENGTH} characters"
        )
