import os
import shutil
import sys
from pathlib import Path
from typing import Any

from EvernightAI.bootstrap.interface import create_interface
from EvernightAI.bootstrap.options import (
    BuiltinToolOptions,
    ContextStrategyOptions,
    FilesystemToolOptions,
    GitToolOptions,
    ProjectToolOptions,
    ShellToolOptions,
    WebToolOptions,
)
from EvernightAI.bootstrap.runtime import (
    close_opened_resources,
    create_sqlite_runtime,
    create_memory_strategy,
    create_memory_write_strategy,
    runtime_state_paths,
)
from EvernightAI.core.domain.auth import Authorizer, PermissionAuthPolicy
from EvernightAI.core.domain.authorized_interface import AuthorizedEvernightInterface
from EvernightAI.core.domain.runtime import RuntimeKernel
from EvernightAI.core.error.base import ConfigurationError
from EvernightAI.core.error.tool import ToolConfigurationError
from EvernightAI.core.error.sandbox import SandboxConfigurationError
from EvernightAI.core.schema.sandbox import SandboxResourceLimits
from EvernightAI.core.protocol.interface import EvernightInterfaceProtocol
from EvernightAI.core.protocol.data_analysis import DataAnalysisRegisterProtocol
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.tool import ToolSourceProtocol
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore
from EvernightAI.core.schema.data_analysis import DataSourceDefinition
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.sandbox.bubblewrap_policy import BubblewrapRuntimePolicy
from EvernightAI.infra.adapters.sandbox.project_environment import (
    default_python_runtime_roots,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor
from EvernightAI.infra.registrations.data_analysis.sqlite import (
    register_sqlite_data_source,
)
from EvernightAI.infra.registrations.tool.mcp import (
    create_mcp_sse_tool_source,
    create_mcp_stdio_tool_source,
    create_mcp_streamable_http_tool_source,
)
from EvernightAI.interface.cli.auth import ConfigCliAuthDevice
from EvernightAI.core.domain.api_key import ApiKeyManager, ManagedApiKeyAuthDevice
from EvernightAI.core.schema.auth import Principal
from EvernightAI.infra.adapters.api_key import SQLiteApiKeyRegister
from EvernightAI.interface.cli.schema import (
    AuthUserConfig,
    EvernightConfig,
    McpServerConfig,
    McpTransport,
    SandboxBackend,
    SQLiteDataSourceConfig,
)


def create_runtime_from_config(config: EvernightConfig) -> RuntimeKernel:
    _validate_context_strategy(config)
    tools = _builtin_tool_options(config)
    tool_sources = _configured_mcp_tool_sources(config)
    if config.runtime.sandbox_backend is SandboxBackend.BUBBLEWRAP:
        _validate_sandbox_tool_roots(config)
    sandbox_root = Path(config.runtime.sandbox.workspace_root).resolve()

    async def prepare_workspace() -> None:
        if config.runtime.sandbox_backend is SandboxBackend.BUBBLEWRAP:
            sandbox_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    workspaces = (
        WorkspaceDirectoryStore(
            config.tools.filesystem.root,
            browse_host_directories=True,
            database_path=config.runtime.database_path,
            protected_paths=[
                *_protected_workspace_paths(config),
                Path(sys.prefix),
                Path(sys.base_prefix),
                *config.runtime.sandbox.readonly_paths,
                *config.runtime.sandbox.python_runtime_roots,
                *default_python_runtime_roots(),
            ],
        )
        if config.tools.filesystem.enabled
        else None
    )
    try:
        sandbox = create_sandbox_from_config(config, workspace_directories=workspaces)
        runtime = create_sqlite_runtime(
            config.runtime.database_path,
            startup_handlers=[prepare_workspace],
            sandbox=sandbox,
            memory_strategy=create_memory_strategy(config.memory_strategy.selection),
            memory_write_strategy=create_memory_write_strategy(
                config.memory_strategy.write
            ),
            workspace_directories=workspaces,
            tools=tools,
            context=_context_strategy_options(config),
            runtime_data_tools_enabled=config.tools.runtime_data.enabled,
            tool_sources=tool_sources,
            prompt_cache_mode=config.prompt_cache.mode,
            prompt_cache_scope=config.prompt_cache.scope,
            configure_data_analysis=lambda register: register_configured_data_sources(
                register, config
            ),
        )
    except BaseException:
        close_opened_resources([workspaces])
        raise
    return runtime


def register_configured_data_sources(
    register: DataAnalysisRegisterProtocol,
    config: EvernightConfig,
) -> None:
    for source in config.data_analysis.sqlite_sources:
        register_sqlite_data_source(
            register,
            database_path=config.runtime.database_path,
            source=_sqlite_data_source_definition(source),
            table_name=source.table,
        )


def _protected_workspace_paths(config: EvernightConfig) -> list[Path | str]:
    return [
        *runtime_state_paths(config.runtime.database_path),
        *config.runtime.sandbox.protected_paths,
    ]


def create_sandbox_from_config(
    config: EvernightConfig,
    *,
    workspace_directories: WorkspaceDirectoryProtocol | None = None,
) -> SandboxExecuteProtocol:
    if config.runtime.sandbox_backend is SandboxBackend.BUBBLEWRAP:
        if os.name != "posix" or shutil.which("bwrap") is None:
            raise SandboxConfigurationError(
                "Bubblewrap requires Linux and an installed bwrap executable"
            )
        if shutil.which("prlimit") is None:
            raise SandboxConfigurationError(
                "Bubblewrap resource limits require prlimit"
            )
        settings = config.runtime.sandbox
        policy = BubblewrapRuntimePolicy(
            workspace_root=settings.workspace_root,
            network_mode=settings.network_mode,
            workspace_directories=workspace_directories,
            readonly_paths=settings.readonly_paths,
            python_runtime_roots=settings.python_runtime_roots,
            protected_paths=_protected_workspace_paths(config),
            include_python_environment=settings.include_python_environment,
            include_uv=settings.include_uv,
            include_node=settings.include_node,
            limits=SandboxResourceLimits(
                timeout_seconds=settings.timeout_seconds,
                max_output_chars=settings.max_output_chars,
                memory_bytes=settings.memory_bytes,
                max_processes=settings.max_processes,
                cpu_seconds=settings.cpu_seconds,
                file_size_bytes=settings.file_size_bytes,
                temporary_storage_bytes=settings.temporary_storage_bytes,
            ),
        )
        return BubblewrapSandboxExecutor(runtime_policy=policy)
    return SubprocessSandboxExecutor()


def _validate_sandbox_tool_roots(config: EvernightConfig) -> None:
    root = Path(config.runtime.sandbox.workspace_root).resolve()
    directories = list(config.tools.project.project_directories.values())
    if config.tools.filesystem.enabled:
        directories.append(config.tools.filesystem.root)
    if config.tools.shell.enabled:
        directories.append(config.tools.shell.working_directory or ".")
    if config.tools.git.enabled:
        directories.append(config.tools.git.repository_directory)
    if config.tools.project.enabled:
        directories.append(config.tools.project.working_directory)
    if config.tools.web.enabled and config.tools.web.download_directory is not None:
        directories.append(config.tools.web.download_directory)
    for directory in directories:
        if not Path(directory).resolve().is_relative_to(root):
            raise SandboxConfigurationError(
                "With bubblewrap enabled, filesystem, shell, Git, project and download directories must stay inside runtime.sandbox.workspace_root"
            )


def create_interface_from_config(
    config: EvernightConfig,
) -> EvernightInterfaceProtocol:
    if not config.auth.enabled:
        return create_unsecured_interface_from_config(config)

    principal = _cli_principal(config)
    return AuthorizedEvernightInterface(
        create_unsecured_interface_from_config(config),
        Authorizer(PermissionAuthPolicy()),
        principal,
    )


def principal_for_user(user: AuthUserConfig) -> Principal:
    return Principal(
        principal_id=user.username,
        principal_type=user.principal_type,
        roles=user.roles,
        permissions=user.permissions,
        metadata=user.metadata,
    )


def _cli_principal(config: EvernightConfig) -> Principal:
    if not os.getenv("EVERNIGHTAI_CLI_API_KEY"):
        return ConfigCliAuthDevice().principal_for_config(config)
    register = SQLiteApiKeyRegister(config.runtime.database_path)
    try:
        device = ManagedApiKeyAuthDevice(
            ApiKeyManager(register),
            [principal_for_user(user) for user in config.auth.users],
        )
        return ConfigCliAuthDevice(device).principal_for_config(config)
    finally:
        register.close()


def create_unsecured_interface_from_config(
    config: EvernightConfig,
) -> EvernightInterfaceProtocol:
    runtime = create_runtime_from_config(config)
    return create_interface(runtime)


def _builtin_tool_options(config: EvernightConfig) -> BuiltinToolOptions:
    filesystem = config.tools.filesystem
    shell = config.tools.shell
    web = config.tools.web
    git = config.tools.git
    project = config.tools.project
    return BuiltinToolOptions(
        filesystem=(
            FilesystemToolOptions(
                root=filesystem.root,
                max_read_chars=filesystem.max_read_chars,
                max_directory_entries=filesystem.max_directory_entries,
                max_search_results=filesystem.max_search_results,
                allow_overwrite=filesystem.allow_write,
            )
            if filesystem.enabled
            else None
        ),
        shell=(
            ShellToolOptions(
                allowed_commands=set(shell.allowed_commands),
                blocked_commands=set(shell.blocked_commands),
                working_directory=shell.working_directory,
                timeout_seconds=shell.timeout_seconds,
                max_output_chars=shell.max_output_chars,
                requires_approval=shell.is_need_approval,
                relaxed_approval=shell.relaxed_approval,
                allowed_env_keys=(
                    set(shell.allowed_env_keys)
                    if shell.allowed_env_keys is not None
                    else None
                ),
            )
            if shell.enabled
            else None
        ),
        web=(
            WebToolOptions(
                allowed_hosts=(
                    set(web.allowed_hosts) if web.allowed_hosts is not None else None
                ),
                download_directory=web.download_directory,
                timeout_seconds=web.timeout_seconds,
                max_response_chars=web.max_response_chars,
                max_download_bytes=web.max_download_bytes,
            )
            if web.enabled
            else None
        ),
        git=(
            GitToolOptions(
                repository_directory=git.repository_directory,
                timeout_seconds=git.timeout_seconds,
                max_output_chars=git.max_output_chars,
            )
            if git.enabled
            else None
        ),
        project=(
            ProjectToolOptions(
                working_directory=project.working_directory,
                commands=project.commands,
                command_overrides=project.projects,
                timeout_seconds=project.timeout_seconds,
                max_output_chars=project.max_output_chars,
            )
            if project.enabled
            else None
        ),
        project_directories={**project.project_directories},
    )


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
        resolved[target_name] = _required_secret(
            source_name, label="MCP stdio environment"
        )
    return resolved


def _configured_secret(name: str | None, *, label: str) -> str | None:
    if name is None:
        return None
    return _required_secret(name, label=label)


def _required_secret(name: str, *, label: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise ToolConfigurationError(f"{label} variable is not set: {name}")
    return value


def _validate_context_strategy(config: EvernightConfig) -> None:
    if config.context_strategy.enable_summary:
        raise ConfigurationError(
            "context_strategy.enable_summary requires a context summarizer, "
            "which this runtime assembly does not provide"
        )


def _context_strategy_options(config: EvernightConfig) -> ContextStrategyOptions:
    context_strategy = config.context_strategy
    return ContextStrategyOptions(
        max_messages=context_strategy.max_messages,
        max_tokens=context_strategy.max_tokens,
        enable_summary=context_strategy.enable_summary,
        summarize_after_messages=context_strategy.summarize_after_messages,
        keep_recent_messages=context_strategy.keep_recent_messages,
    )


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
