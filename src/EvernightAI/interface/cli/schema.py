from typing import Any
from enum import StrEnum

from EvernightAI.core.schema.auth import PrincipalType
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.data_analysis import (
    DataFieldDefinition,
    DataMetricDefinition,
)
from EvernightAI.core.schema.provider import ProviderConfig
from pydantic import Field, model_validator


class SandboxBackend(StrEnum):
    """沙盒后端"""

    SUBPROCESS = "subprocess"
    BUBBLEWRAP = "bubblewrap"


class RuntimeConfig(EvernightAISchema):
    database_path: str = ".evernight/runtime.sqlite3"
    sandbox_backend: SandboxBackend = SandboxBackend.SUBPROCESS


class ContextStrategyConfig(EvernightAISchema):
    max_messages: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    enable_summary: bool = False
    summarize_after_messages: int = Field(default=100, ge=1)
    keep_recent_messages: int = Field(default=20, ge=1)


class HttpConfig(EvernightAISchema):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    server_header: str | None = "EvernightAI"
    static_files_path: str | None = None


class FilesystemToolConfig(EvernightAISchema):
    enabled: bool = False
    root: str = "."
    max_read_chars: int = 12000
    max_directory_entries: int = 100
    max_search_results: int = 100
    allow_write: bool = False


class ShellToolConfig(EvernightAISchema):
    enabled: bool = False
    allowed_commands: list[str] = Field(default_factory=list)
    blocked_commands: list[str] = Field(default_factory=list)
    working_directory: str | None = None
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000
    is_need_approval: bool = True
    allowed_env_keys: list[str] | None = None


class WebToolConfig(EvernightAISchema):
    enabled: bool = False
    allowed_hosts: list[str] | None = None
    download_directory: str | None = None
    timeout_seconds: float = 10.0
    max_response_chars: int = 12000
    max_download_bytes: int = 10_000_000


class GitToolConfig(EvernightAISchema):
    enabled: bool = False
    repository_directory: str = "."
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000


class ProjectToolConfig(EvernightAISchema):
    enabled: bool = False
    working_directory: str = "."
    commands: dict[str, list[str]] = Field(default_factory=dict)
    projects: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    project_directories: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 120.0
    max_output_chars: int = 20000


class RuntimeDataToolConfig(EvernightAISchema):
    enabled: bool = False


class McpTransport(StrEnum):
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"
    STDIO = "stdio"


class McpServerConfig(EvernightAISchema):
    enabled: bool = True
    transport: McpTransport = McpTransport.STREAMABLE_HTTP
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env_from: dict[str, str] = Field(default_factory=dict)
    namespace: str | None = None
    token_env: str | None = None
    allowed_tools: list[str] | None = None
    blocked_tools: list[str] = Field(default_factory=list)
    max_tools: int = Field(default=100, ge=1)
    max_definition_chars: int = Field(default=12000, ge=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    sse_read_timeout_seconds: float = Field(default=300.0, gt=0)
    max_output_chars: int = Field(default=20000, ge=1)
    is_need_approval: bool = True
    watch_tool_changes: bool = True
    refresh_interval_seconds: float | None = Field(default=None, gt=0)
    refresh_retry_seconds: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def validate_transport_fields(self) -> "McpServerConfig":
        if self.transport is McpTransport.STDIO:
            if not self.command:
                raise ValueError("MCP stdio transport requires command")
            if self.url is not None:
                raise ValueError("MCP stdio transport does not accept url")
            if self.token_env is not None:
                raise ValueError("MCP stdio credentials must use env_from")
            for target_name, source_name in self.env_from.items():
                if not target_name or "=" in target_name or not source_name:
                    raise ValueError("MCP stdio env_from contains an invalid mapping")
            return self

        if not self.url:
            raise ValueError(f"MCP {self.transport.value} transport requires url")
        if self.command is not None or self.args or self.cwd is not None or self.env_from:
            raise ValueError(
                f"MCP {self.transport.value} transport does not accept stdio fields"
            )
        return self


class McpToolConfig(EvernightAISchema):
    server: dict[str, McpServerConfig] = Field(default_factory=dict)


class ToolConfig(EvernightAISchema):
    filesystem: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    web: WebToolConfig = Field(default_factory=WebToolConfig)
    git: GitToolConfig = Field(default_factory=GitToolConfig)
    project: ProjectToolConfig = Field(default_factory=ProjectToolConfig)
    runtime_data: RuntimeDataToolConfig = Field(default_factory=RuntimeDataToolConfig)
    mcp: McpToolConfig = Field(default_factory=McpToolConfig)


class AuthPrincipalConfig(EvernightAISchema):
    principal_id: str
    principal_type: PrincipalType = PrincipalType.USER
    api_key: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OAuthTokenPrincipalConfig(EvernightAISchema):
    principal_id: str
    principal_type: PrincipalType = PrincipalType.USER
    access_token: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OAuthJwtConfig(EvernightAISchema):
    issuer: str | None = None
    audience: list[str] = Field(default_factory=list)
    jwks_url: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    leeway_seconds: int = 60
    principal_id_claim: str = "sub"
    principal_type: PrincipalType = PrincipalType.USER
    roles_claim: str = "roles"
    scope_claim: str = "scope"
    permissions_claim: str = "permissions"
    default_permissions: list[str] = Field(default_factory=list)
    role_permission_map: dict[str, list[str]] = Field(default_factory=dict)
    scope_permission_map: dict[str, list[str]] = Field(default_factory=dict)


class OAuthConfig(EvernightAISchema):
    tokens: list[OAuthTokenPrincipalConfig] = Field(default_factory=list)
    jwt: OAuthJwtConfig | None = None


class AuthConfig(EvernightAISchema):
    enabled: bool = False
    principals: list[AuthPrincipalConfig] = Field(default_factory=list)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)


class SQLiteDataSourceConfig(EvernightAISchema):
    source_id: str
    name: str
    table: str
    description: str | None = None
    fields: list[DataFieldDefinition] = Field(default_factory=list)
    metrics: list[DataMetricDefinition] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataAnalysisConfig(EvernightAISchema):
    sqlite_sources: list[SQLiteDataSourceConfig] = Field(default_factory=list)


class EvernightConfig(EvernightAISchema):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    context_strategy: ContextStrategyConfig = Field(
        default_factory=ContextStrategyConfig
    )
    http: HttpConfig = Field(default_factory=HttpConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    data_analysis: DataAnalysisConfig = Field(default_factory=DataAnalysisConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
