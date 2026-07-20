import os
from typing import Any

from EvernightAI.bootstrap.interface import create_authorized_interface, create_interface
from EvernightAI.bootstrap.runtime import (
    create_bubblewrap_sandbox_executor,
    create_sandbox_executor,
    create_sqlite_runtime,
)
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.error.tool import ToolConfigurationError
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.tool import ToolSourceProtocol
from EvernightAI.core.schema.data_analysis import DataSourceDefinition
from EvernightAI.infra.registrations.data_analysis.sqlite import (
    register_sqlite_data_source,
)
from EvernightAI.infra.registrations.tool.mcp import (
    create_mcp_sse_tool_source,
    create_mcp_stdio_tool_source,
    create_mcp_streamable_http_tool_source,
)
from EvernightAI.interface.cli.auth import ConfigCliAuthDevice
from EvernightAI.interface.cli.schema import (
    EvernightConfig,
    McpServerConfig,
    McpTransport,
    SandboxBackend,
    SQLiteDataSourceConfig,
)


def create_runtime_from_config(config: EvernightConfig) -> RuntimeKernel:
    runtime = create_sqlite_runtime(
        config.runtime.database_path,
        sandbox=create_sandbox_from_config(config),
        **_runtime_tool_options(config),
        **_runtime_context_options(config),
        prompt_cache_mode=config.prompt_cache.mode,
        prompt_cache_scope=config.prompt_cache.scope,
    )
    register_configured_data_sources(runtime, config)
    return runtime


def register_configured_data_sources(
    runtime: RuntimeKernel,
    config: EvernightConfig,
) -> None:
    for source in config.data_analysis.sqlite_sources:
        register_sqlite_data_source(
            runtime.data_analysis_register,
            database_path=config.runtime.database_path,
            source=_sqlite_data_source_definition(source),
            table_name=source.table,
        )


def create_sandbox_from_config(config: EvernightConfig) -> SandboxExecuteProtocol:
    if config.runtime.sandbox_backend is SandboxBackend.BUBBLEWRAP:
        return create_bubblewrap_sandbox_executor()
    return create_sandbox_executor()


def create_interface_from_config(
    config: EvernightConfig,
) -> EvernightInterfaceProtocol:
    interface = create_unsecured_interface_from_config(config)
    if not config.auth.enabled:
        return interface

    return create_authorized_interface(
        interface,
        Authorizer(PermissionAuthPolicy()),
        ConfigCliAuthDevice().principal_for_config(config),
    )


def create_unsecured_interface_from_config(
    config: EvernightConfig,
) -> EvernightInterfaceProtocol:
    runtime = create_runtime_from_config(config)
    return create_interface(runtime)


def _runtime_tool_options(config: EvernightConfig) -> dict[str, Any]:
    filesystem = config.tools.filesystem
    shell = config.tools.shell
    web = config.tools.web
    git = config.tools.git
    project = config.tools.project
    runtime_data = config.tools.runtime_data
    return {
        "filesystem_root": filesystem.root if filesystem.enabled else None,
        "max_read_chars": filesystem.max_read_chars,
        "max_directory_entries": filesystem.max_directory_entries,
        "max_search_results": filesystem.max_search_results,
        "allow_file_overwrite": filesystem.allow_write,
        "shell_allowed_commands": (
            set(shell.allowed_commands) if shell.enabled else None
        ),
        "shell_blocked_commands": (
            set(shell.blocked_commands) if shell.enabled else None
        ),
        "shell_working_directory": shell.working_directory,
        "shell_timeout_seconds": shell.timeout_seconds,
        "shell_max_output_chars": shell.max_output_chars,
        "shell_requires_approval": shell.is_need_approval,
        "shell_allowed_env_keys": (
            set(shell.allowed_env_keys)
            if shell.enabled and shell.allowed_env_keys is not None
            else None
        ),
        "web_enabled": web.enabled,
        "web_allowed_hosts": (
            set(web.allowed_hosts) if web.allowed_hosts is not None else None
        ),
        "web_download_directory": web.download_directory,
        "web_timeout_seconds": web.timeout_seconds,
        "web_max_response_chars": web.max_response_chars,
        "web_max_download_bytes": web.max_download_bytes,
        "git_repository_directory": git.repository_directory if git.enabled else None,
        "git_timeout_seconds": git.timeout_seconds,
        "git_max_output_chars": git.max_output_chars,
        "project_working_directory": (
            project.working_directory if project.enabled else None
        ),
        "project_commands": project.commands if project.enabled else None,
        "project_command_overrides": project.projects if project.enabled else None,
        "project_directories": project.project_directories,
        "project_timeout_seconds": project.timeout_seconds,
        "project_max_output_chars": project.max_output_chars,
        "runtime_data_tools_enabled": runtime_data.enabled,
        "tool_sources": _configured_mcp_tool_sources(config),
    }


def _configured_mcp_tool_sources(config: EvernightConfig) -> list[ToolSourceProtocol]:
    sources: list[ToolSourceProtocol] = []
    for server_id, server in config.tools.mcp.server.items():
        if not server.enabled:
            continue
        sources.append(_configured_mcp_tool_source(server_id, server))
    return sources


def _configured_mcp_tool_source(
    server_id: str,
    server: McpServerConfig,
) -> ToolSourceProtocol:
    common_options: dict[str, Any] = {
        "server_id": server_id,
        "namespace": server.namespace,
        "allowed_tools": (
            set(server.allowed_tools) if server.allowed_tools is not None else None
        ),
        "blocked_tools": set(server.blocked_tools),
        "max_tools": server.max_tools,
        "max_definition_chars": server.max_definition_chars,
        "timeout_seconds": server.timeout_seconds,
        "max_output_chars": server.max_output_chars,
        "requires_approval": server.is_need_approval,
        "watch_tool_changes": server.watch_tool_changes,
        "refresh_interval_seconds": server.refresh_interval_seconds,
        "refresh_retry_seconds": server.refresh_retry_seconds,
    }
    if server.transport is McpTransport.STDIO:
        if server.command is None:
            raise ToolConfigurationError("MCP stdio command is required")
        return create_mcp_stdio_tool_source(
            command=server.command,
            args=server.args,
            cwd=server.cwd,
            env=_configured_mcp_stdio_env(server),
            **common_options,
        )

    if server.url is None:
        raise ToolConfigurationError(f"MCP {server.transport.value} URL is required")
    bearer_token = _configured_secret(server.token_env, label="MCP token")
    if server.transport is McpTransport.SSE:
        return create_mcp_sse_tool_source(
            url=server.url,
            bearer_token=bearer_token,
            sse_read_timeout_seconds=server.sse_read_timeout_seconds,
            **common_options,
        )
    return create_mcp_streamable_http_tool_source(
        url=server.url,
        bearer_token=bearer_token,
        **common_options,
    )


def _configured_mcp_stdio_env(server: McpServerConfig) -> dict[str, str] | None:
    if not server.env_from:
        return None
    resolved: dict[str, str] = {}
    for target_name, source_name in server.env_from.items():
        value = _configured_secret(source_name, label="MCP stdio environment")
        if value is None:
            raise ToolConfigurationError(
                f"MCP stdio environment variable is not set: {source_name}"
            )
        resolved[target_name] = value
    return resolved


def _configured_secret(name: str | None, *, label: str) -> str | None:
    if name is None:
        return None
    value = os.getenv(name)
    if value is None or value == "":
        raise ToolConfigurationError(f"{label} variable is not set: {name}")
    return value


def _runtime_context_options(config: EvernightConfig) -> dict[str, Any]:
    context_strategy = config.context_strategy
    return {
        "context_max_messages": context_strategy.max_messages,
        "context_max_tokens": context_strategy.max_tokens,
        "context_enable_summary": context_strategy.enable_summary,
        "context_summarize_after_messages": (
            context_strategy.summarize_after_messages
        ),
        "context_keep_recent_messages": context_strategy.keep_recent_messages,
    }


def _sqlite_data_source_definition(
    source: SQLiteDataSourceConfig,
) -> DataSourceDefinition:
    return DataSourceDefinition(
        source_id=source.source_id,
        name=source.name,
        description=source.description,
        fields=source.fields,
        metrics=source.metrics,
        metadata={
            **source.metadata,
            "sqlite_table": source.table,
        },
    )
