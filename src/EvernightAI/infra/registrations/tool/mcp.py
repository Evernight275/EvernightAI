from pathlib import Path

from EvernightAI.infra.adapters.tool.mcp import (
    McpClientProtocol,
    McpSseClient,
    McpStdioClient,
    McpStreamableHttpClient,
    McpToolSource,
)


def create_mcp_streamable_http_tool_source(
    *,
    server_id: str,
    url: str,
    namespace: str | None = None,
    bearer_token: str | None = None,
    allowed_tools: set[str] | None = None,
    blocked_tools: set[str] | None = None,
    max_tools: int = 100,
    max_definition_chars: int = 12000,
    timeout_seconds: float = 30.0,
    max_output_chars: int = 20000,
    requires_approval: bool = True,
    watch_tool_changes: bool = True,
    refresh_interval_seconds: float | None = None,
    refresh_retry_seconds: float = 5.0,
) -> McpToolSource:
    return _create_source(
        server_id=server_id,
        namespace=namespace,
        client=McpStreamableHttpClient(
            url=url,
            headers=_bearer_headers(bearer_token),
            timeout_seconds=timeout_seconds,
        ),
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        max_tools=max_tools,
        max_definition_chars=max_definition_chars,
        max_output_chars=max_output_chars,
        requires_approval=requires_approval,
        watch_tool_changes=watch_tool_changes,
        refresh_interval_seconds=refresh_interval_seconds,
        refresh_retry_seconds=refresh_retry_seconds,
    )


def create_mcp_sse_tool_source(
    *,
    server_id: str,
    url: str,
    namespace: str | None = None,
    bearer_token: str | None = None,
    allowed_tools: set[str] | None = None,
    blocked_tools: set[str] | None = None,
    max_tools: int = 100,
    max_definition_chars: int = 12000,
    timeout_seconds: float = 30.0,
    sse_read_timeout_seconds: float = 300.0,
    max_output_chars: int = 20000,
    requires_approval: bool = True,
    watch_tool_changes: bool = True,
    refresh_interval_seconds: float | None = None,
    refresh_retry_seconds: float = 5.0,
) -> McpToolSource:
    return _create_source(
        server_id=server_id,
        namespace=namespace,
        client=McpSseClient(
            url=url,
            headers=_bearer_headers(bearer_token),
            timeout_seconds=timeout_seconds,
            sse_read_timeout_seconds=sse_read_timeout_seconds,
        ),
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        max_tools=max_tools,
        max_definition_chars=max_definition_chars,
        max_output_chars=max_output_chars,
        requires_approval=requires_approval,
        watch_tool_changes=watch_tool_changes,
        refresh_interval_seconds=refresh_interval_seconds,
        refresh_retry_seconds=refresh_retry_seconds,
    )


def create_mcp_stdio_tool_source(
    *,
    server_id: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    namespace: str | None = None,
    allowed_tools: set[str] | None = None,
    blocked_tools: set[str] | None = None,
    max_tools: int = 100,
    max_definition_chars: int = 12000,
    timeout_seconds: float = 30.0,
    max_output_chars: int = 20000,
    requires_approval: bool = True,
    watch_tool_changes: bool = True,
    refresh_interval_seconds: float | None = None,
    refresh_retry_seconds: float = 5.0,
) -> McpToolSource:
    return _create_source(
        server_id=server_id,
        namespace=namespace,
        client=McpStdioClient(
            command=command,
            args=args,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
        ),
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        max_tools=max_tools,
        max_definition_chars=max_definition_chars,
        max_output_chars=max_output_chars,
        requires_approval=requires_approval,
        watch_tool_changes=watch_tool_changes,
        refresh_interval_seconds=refresh_interval_seconds,
        refresh_retry_seconds=refresh_retry_seconds,
    )


def _create_source(
    *,
    server_id: str,
    namespace: str | None,
    client: McpClientProtocol,
    allowed_tools: set[str] | None,
    blocked_tools: set[str] | None,
    max_tools: int,
    max_definition_chars: int,
    max_output_chars: int,
    requires_approval: bool,
    watch_tool_changes: bool,
    refresh_interval_seconds: float | None,
    refresh_retry_seconds: float,
) -> McpToolSource:
    return McpToolSource(
        server_id=server_id,
        namespace=namespace or server_id,
        client=client,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        max_tools=max_tools,
        max_definition_chars=max_definition_chars,
        requires_approval=requires_approval,
        max_output_chars=max_output_chars,
        watch_tool_changes=watch_tool_changes,
        refresh_interval_seconds=refresh_interval_seconds,
        refresh_retry_seconds=refresh_retry_seconds,
    )


def _bearer_headers(token: str | None) -> dict[str, str] | None:
    if token is None:
        return None
    return {"Authorization": f"Bearer {token}"}
