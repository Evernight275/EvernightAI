import asyncio
from collections.abc import Callable
from pathlib import Path
import socket
import sys
from typing import Any

import httpx
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool as McpTool

from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import (
    ToolApprovalMode,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.tool.mcp import (
    McpSseClient,
    McpStreamableHttpClient,
    McpStdioClient,
    McpToolSource,
)


class FakeMcpClient:
    def __init__(
        self,
        tools: list[McpTool],
        *,
        results: dict[str, CallToolResult] | None = None,
        connect_error: Exception | None = None,
        supports_tool_list_changes: bool = True,
    ) -> None:
        self.tools = tools
        self.results = results or {}
        self.connect_error = connect_error
        self.supports_tool_list_changes = supports_tool_list_changes
        self.connected = False
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tool_list_changed_handler: Callable[[], None] | None = None
        self.failure_handler: Callable[[Exception], None] | None = None

    @property
    def transport_name(self) -> str:
        return "fake"

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def list_tools(self) -> list[McpTool]:
        return self.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> CallToolResult:
        self.calls.append((name, arguments))
        return self.results.get(name, _text_result(f"called {name}"))

    def set_tool_list_changed_handler(
        self,
        handler: Callable[[], None] | None,
    ) -> None:
        self.tool_list_changed_handler = handler

    def notify_tool_list_changed(self) -> None:
        if self.tool_list_changed_handler is not None:
            self.tool_list_changed_handler()

    def set_failure_handler(
        self,
        handler: Callable[[Exception], None] | None,
    ) -> None:
        self.failure_handler = handler

    def notify_failure(self, error: Exception) -> None:
        if self.failure_handler is not None:
            self.failure_handler(error)

    async def close(self) -> None:
        self.connected = False
        self.closed = True


def _tool(name: str, description: str | None = None) -> McpTool:
    return McpTool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )


def _text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


@pytest.mark.asyncio
async def test_mcp_source_registers_namespaced_tools_with_local_safety() -> None:
    client = FakeMcpClient(
        [_tool("search", "Search remote code"), _tool("delete_repository")],
        results={"search": _text_result("found")},
    )
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
        blocked_tools={"delete_repository"},
    )
    register = ToolRegister()
    manager = ToolManager(register)

    await source.load(register)

    assert source.is_ready() is True
    assert [tool.name for tool in manager.list_tools()] == ["github__search"]
    definition = register.get("github__search")
    assert definition.description == "Search remote code"
    assert definition.permissions == [
        ToolPermission.NETWORK,
        ToolPermission.EXTERNAL_API,
    ]
    assert definition.safety_level is ToolSafetyLevel.SENSITIVE
    assert definition.approval_mode is ToolApprovalMode.REQUIRED
    assert definition.metadata == {
        "source": "mcp",
        "remote": True,
        "mcp_server_id": "github",
        "mcp_tool_name": "search",
        "mcp_transport": "fake",
    }

    with pytest.raises(ToolPolicyError, match="rejected by policy"):
        await manager.execute(
            ToolCall(
                tool_call_id="call-unapproved",
                tool_call={"name": "github__search", "arguments": {}},
            )
        )
    assert client.calls == []

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "github__search",
                "arguments": {"query": "runtime"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result == {
        "content": [{"type": "text", "text": "found"}],
        "isError": False,
    }
    assert client.calls == [("search", {"query": "runtime"})]

    await source.close()

    assert source.is_ready() is False
    assert register.list_tools() == []
    assert client.closed is True


@pytest.mark.asyncio
async def test_mcp_source_can_explicitly_disable_approval() -> None:
    client = FakeMcpClient([_tool("status")])
    source = McpToolSource(
        server_id="ops",
        namespace="ops",
        client=client,
        requires_approval=False,
    )
    register = ToolRegister()
    manager = ToolManager(register)
    await source.load(register)

    definition = register.get("ops__status")
    assert definition.approval_mode is ToolApprovalMode.NEVER
    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "ops__status", "arguments": {}},
        )
    )

    assert result.tool_call_result["isError"] is False
    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_rejects_conflicting_tool_names_and_closes_client() -> None:
    async def local_tool(_arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
    )
    register = ToolRegister()
    register_tool = ToolDefinition(
        name="github__search",
        description="Existing local tool",
    )
    register.register(
        register_tool,
        local_tool,
    )

    with pytest.raises(ToolConfigurationError, match="conflict"):
        await source.load(register)

    assert register.list_tools() == [register_tool]
    assert client.closed is True
    assert source.is_ready() is False


@pytest.mark.asyncio
async def test_mcp_source_rejects_missing_allowed_tools() -> None:
    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
        allowed_tools={"search", "get_file"},
    )

    with pytest.raises(ToolConfigurationError, match="did not provide") as exc_info:
        await source.load(ToolRegister())

    assert exc_info.value.detail == "get_file"
    assert client.closed is True


@pytest.mark.asyncio
async def test_mcp_source_rejects_oversized_discovery() -> None:
    too_many_client = FakeMcpClient([_tool("one"), _tool("two")])
    too_many_source = McpToolSource(
        server_id="data",
        namespace="data",
        client=too_many_client,
        max_tools=1,
    )

    with pytest.raises(ToolConfigurationError, match="too many tools"):
        await too_many_source.load(ToolRegister())

    large_definition_client = FakeMcpClient([_tool("large", "x" * 100)])
    large_definition_source = McpToolSource(
        server_id="data",
        namespace="data",
        client=large_definition_client,
        max_definition_chars=20,
    )

    with pytest.raises(ToolConfigurationError, match="definition is too large"):
        await large_definition_source.load(ToolRegister())

    assert too_many_client.closed is True
    assert large_definition_client.closed is True


@pytest.mark.asyncio
async def test_mcp_source_preserves_remote_error_as_execution_cause() -> None:
    client = FakeMcpClient(
        [_tool("search")],
        results={"search": _text_result("remote unavailable", is_error=True)},
    )
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
        requires_approval=False,
    )
    register = ToolRegister()
    manager = ToolManager(register)
    await source.load(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={"name": "github__search", "arguments": {}},
            )
        )

    assert isinstance(exc_info.value.cause, ToolExecutionError)
    assert exc_info.value.cause.detail == "remote unavailable"
    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_truncates_oversized_results() -> None:
    client = FakeMcpClient(
        [_tool("large")],
        results={"large": _text_result("x" * 200)},
    )
    source = McpToolSource(
        server_id="data",
        namespace="data",
        client=client,
        requires_approval=False,
        max_output_chars=40,
    )
    register = ToolRegister()
    manager = ToolManager(register)
    await source.load(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "data__large", "arguments": {}},
        )
    )

    assert result.tool_call_result["truncated"] is True
    assert len(result.tool_call_result["content"]) == 40
    assert result.tool_call_result["original_chars"] > 40
    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_hot_refreshes_tools_from_notification() -> None:
    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
    )
    register = ToolRegister()
    await source.load(register)

    client.tools = [_tool("get_file")]
    client.notify_tool_list_changed()
    await _wait_for_tool_names(register, ["github__get_file"])

    assert source.is_ready() is True
    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_polls_when_change_notifications_are_unavailable() -> None:
    client = FakeMcpClient(
        [_tool("search")],
        supports_tool_list_changes=False,
    )
    source = McpToolSource(
        server_id="legacy",
        namespace="legacy",
        client=client,
        watch_tool_changes=False,
        refresh_interval_seconds=0.01,
    )
    register = ToolRegister()
    await source.load(register)

    client.tools = [_tool("get_file")]
    await _wait_for_tool_names(register, ["legacy__get_file"])

    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_marks_readiness_degraded_on_transport_failure() -> None:
    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
        watch_tool_changes=False,
    )
    await source.load(ToolRegister())

    client.notify_failure(RuntimeError("connection lost"))

    assert source.is_ready() is False
    await source.close()


@pytest.mark.asyncio
async def test_mcp_source_keeps_last_snapshot_when_refresh_fails() -> None:
    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
        max_tools=1,
    )
    register = ToolRegister()
    await source.load(register)

    client.tools = [_tool("one"), _tool("two")]
    with pytest.raises(ToolConfigurationError, match="too many tools"):
        await source.refresh()

    assert [tool.name for tool in register.list_tools()] == ["github__search"]
    assert source.is_ready() is False

    client.tools = [_tool("get_file")]
    await source.refresh()

    assert [tool.name for tool in register.list_tools()] == ["github__get_file"]
    assert source.is_ready() is True
    await source.close()


@pytest.mark.asyncio
async def test_runtime_loads_and_closes_mcp_tool_sources(tmp_path) -> None:
    client = FakeMcpClient([_tool("search")])
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
    )
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=False,
        tool_sources=[source],
    )

    assert runtime.tools.list_tools() == []
    assert runtime.is_ready is False

    await runtime.initialize()

    assert [tool.name for tool in runtime.tools.list_tools()] == ["github__search"]
    assert runtime.is_ready is True

    await runtime.close()

    assert runtime.tools.list_tools() == []
    assert client.closed is True


@pytest.mark.asyncio
async def test_runtime_fails_closed_when_mcp_source_cannot_connect(tmp_path) -> None:
    client = FakeMcpClient(
        [_tool("search")],
        connect_error=RuntimeError("connection refused"),
    )
    source = McpToolSource(
        server_id="github",
        namespace="github",
        client=client,
    )
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=False,
        tool_sources=[source],
    )

    with pytest.raises(ToolConfigurationError, match="Could not load MCP tools"):
        await runtime.initialize()

    assert runtime.is_ready is False
    assert runtime.tools.list_tools() == []
    assert client.closed is True
    await runtime.close()


@pytest.mark.asyncio
async def test_streamable_http_client_discovers_and_calls_real_mcp_server() -> None:
    server = FastMCP(
        "test",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["localhost"],
        ),
    )

    @server.tool()
    def add(left: int, right: int) -> dict[str, int]:
        """Add two integers."""
        return {"result": left + right}

    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://localhost",
        ) as http_client:
            client = McpStreamableHttpClient(
                url="http://localhost/mcp",
                http_client=http_client,
            )
            source = McpToolSource(
                server_id="math",
                namespace="math",
                client=client,
                requires_approval=False,
            )
            register = ToolRegister()
            manager = ToolManager(register)
            await source.load(register)

            result = await asyncio.create_task(
                manager.execute(
                    ToolCall(
                        tool_call_id="call-1",
                        tool_call={
                            "name": "math__add",
                            "arguments": {"left": 2, "right": 3},
                        },
                    )
                )
            )

            assert result.tool_call_result["structuredContent"] == {"result": 5}
            await source.close()


@pytest.mark.asyncio
async def test_stdio_client_discovers_and_calls_real_mcp_process() -> None:
    client = McpStdioClient(
        command=sys.executable,
        args=[str(Path(__file__).parent / "fakes" / "mcp_stdio_server.py")],
        timeout_seconds=10,
    )
    source = McpToolSource(
        server_id="math_stdio",
        namespace="math_stdio",
        client=client,
        requires_approval=False,
        watch_tool_changes=False,
    )
    register = ToolRegister()
    manager = ToolManager(register)
    await source.load(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-stdio",
            tool_call={
                "name": "math_stdio__multiply",
                "arguments": {"left": 6, "right": 7},
            },
        )
    )

    assert result.tool_call_result["structuredContent"] == {"result": 42}
    await source.close()


@pytest.mark.asyncio
async def test_sse_client_discovers_and_calls_real_legacy_mcp_server() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = FastMCP(
        "sse-test",
        transport_security=TransportSecuritySettings(
            allowed_hosts=[f"127.0.0.1:{port}"],
        ),
    )

    @server.tool()
    def subtract(left: int, right: int) -> dict[str, int]:
        """Subtract two integers."""
        return {"result": left - right}

    http_server = uvicorn.Server(
        uvicorn.Config(
            server.sse_app(),
            log_level="critical",
            lifespan="on",
            ws="none",
        )
    )
    server_task = asyncio.create_task(http_server.serve(sockets=[listener]))
    await _wait_for_server_start(http_server)
    source = McpToolSource(
        server_id="legacy",
        namespace="legacy",
        client=McpSseClient(url=f"http://127.0.0.1:{port}/sse"),
        requires_approval=False,
        watch_tool_changes=False,
    )
    register = ToolRegister()
    manager = ToolManager(register)
    try:
        await source.load(register)
        result = await manager.execute(
            ToolCall(
                tool_call_id="call-sse",
                tool_call={
                    "name": "legacy__subtract",
                    "arguments": {"left": 9, "right": 4},
                },
            )
        )
        assert result.tool_call_result["structuredContent"] == {"result": 5}
    finally:
        await source.close()
        http_server.should_exit = True
        await server_task
        listener.close()


async def _wait_for_tool_names(
    register: ToolRegister,
    expected: list[str],
) -> None:
    for _ in range(100):
        if [tool.name for tool in register.list_tools()] == expected:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"Tool names did not become {expected}")


async def _wait_for_server_start(server: uvicorn.Server) -> None:
    for _ in range(1000):
        if server.started:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Test MCP server did not start")
