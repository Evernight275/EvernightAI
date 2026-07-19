from EvernightAI.infra.adapters.tool.mcp import (
    McpStreamableHttpClient,
    McpToolSource,
)


def create_mcp_tool_source(
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
) -> McpToolSource:
    headers = (
        {"Authorization": f"Bearer {bearer_token}"}
        if bearer_token is not None
        else None
    )
    client = McpStreamableHttpClient(
        url=url,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
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
    )
