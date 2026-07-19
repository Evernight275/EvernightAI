import json
import logging
import re
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent, Tool as McpTool

from EvernightAI.core.error.tool import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolStateError,
)
from EvernightAI.core.protocol.tool import (
    ToolExecutorProtocol,
    ToolRegisterProtocol,
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


class McpClientProtocol(Protocol):
    async def connect(self) -> None: ...

    async def list_tools(self) -> list[McpTool]: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult: ...

    async def close(self) -> None: ...


class McpStreamableHttpClient(McpClientProtocol):
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
        self._url = url
        self._headers = dict(headers or {})
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        try:
            http_client = self._http_client
            if http_client is None:
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=self._headers,
                        timeout=httpx.Timeout(
                            self._timeout_seconds,
                            read=max(self._timeout_seconds, 300.0),
                        ),
                        follow_redirects=False,
                    )
                )
            read_stream, write_stream, _ = await stack.enter_async_context(
                streamable_http_client(
                    self._url,
                    http_client=http_client,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                )
            )
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

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

    async def close(self) -> None:
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            await stack.aclose()

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise ToolStateError("The MCP client is not connected")
        return self._session


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
    ) -> None:
        _validate_name(namespace, label="MCP namespace")
        if max_output_chars < 1:
            raise ToolConfigurationError("MCP max_output_chars must be positive")
        if max_tools < 1:
            raise ToolConfigurationError("MCP max_tools must be positive")
        if max_definition_chars < 1:
            raise ToolConfigurationError("MCP max_definition_chars must be positive")

        self._server_id = server_id
        self._namespace = namespace
        self._client = client
        self._allowed_tools = allowed_tools
        self._blocked_tools = blocked_tools or set()
        self._max_tools = max_tools
        self._max_definition_chars = max_definition_chars
        self._requires_approval = requires_approval
        self._max_output_chars = max_output_chars
        self._register: ToolRegisterProtocol | None = None
        self._registered_names: list[str] = []
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

        try:
            await self._client.connect()
            remote_tools = await self._client.list_tools()
            selected_tools = self._select_tools(remote_tools)
            definitions = [self._definition(tool) for tool in selected_tools]
            self._validate_registrations(register, definitions)
            for remote_tool, definition in zip(
                selected_tools, definitions, strict=True
            ):
                register.register(definition, self._executor(remote_tool.name))
                self._registered_names.append(definition.name)
        except BaseException as exc:
            self._rollback_registration(register)
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

        self._register = register
        self._ready = True
        LOGGER.info(
            "MCP tool source loaded",
            extra={
                "mcp_server_id": self._server_id,
                "mcp_tool_count": len(self._registered_names),
            },
        )

    def is_ready(self) -> bool:
        return self._ready

    async def close(self) -> None:
        if self._register is not None:
            self._rollback_registration(self._register)
        self._register = None
        self._ready = False
        await self._client.close()

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
            },
        )

    def _validate_registrations(
        self,
        register: ToolRegisterProtocol,
        definitions: list[ToolDefinition],
    ) -> None:
        names = [definition.name for definition in definitions]
        if len(names) != len(set(names)):
            raise ToolConfigurationError(
                f"The MCP server {self._server_id} produced duplicate local tool names"
            )
        conflicts = [name for name in names if register.has(name)]
        if conflicts:
            raise ToolConfigurationError(
                "MCP tool names conflict with registered tools",
                detail=", ".join(sorted(conflicts)),
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

    def _rollback_registration(self, register: ToolRegisterProtocol) -> None:
        for name in reversed(self._registered_names):
            if register.has(name):
                register.unregister(name)
        self._registered_names.clear()


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
