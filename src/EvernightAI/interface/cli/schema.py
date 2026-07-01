from typing import Any
from enum import StrEnum

from EvernightAI.core.schema.auth import PrincipalType
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.provider import ProviderConfig
from pydantic import Field


class SandboxBackend(StrEnum):
    """沙盒后端"""

    SUBPROCESS = "subprocess"
    BUBBLEWRAP = "bubblewrap"


class RuntimeConfig(EvernightAISchema):
    database_path: str = ".evernight/runtime.sqlite3"
    sandbox_backend: SandboxBackend = SandboxBackend.SUBPROCESS


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
    working_directory: str | None = None
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000
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
    timeout_seconds: float = 120.0
    max_output_chars: int = 20000


class RuntimeDataToolConfig(EvernightAISchema):
    enabled: bool = False


class ToolConfig(EvernightAISchema):
    filesystem: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)
    web: WebToolConfig = Field(default_factory=WebToolConfig)
    git: GitToolConfig = Field(default_factory=GitToolConfig)
    project: ProjectToolConfig = Field(default_factory=ProjectToolConfig)
    runtime_data: RuntimeDataToolConfig = Field(default_factory=RuntimeDataToolConfig)


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


class EvernightConfig(EvernightAISchema):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
