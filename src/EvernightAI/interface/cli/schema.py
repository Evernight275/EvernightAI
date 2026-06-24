from typing import Any

from EvernightAI.core.schema.auth import PrincipalType
from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.provider import ProviderConfig
from pydantic import Field


class RuntimeConfig(EvernightAISchema):
    database_path: str = ".evernight/runtime.sqlite3"


class HttpConfig(EvernightAISchema):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


class FilesystemToolConfig(EvernightAISchema):
    enabled: bool = False
    root: str = "."
    max_read_chars: int = 12000
    max_directory_entries: int = 100
    allow_write: bool = False


class ShellToolConfig(EvernightAISchema):
    enabled: bool = False
    allowed_commands: list[str] = Field(default_factory=list)
    working_directory: str | None = None
    timeout_seconds: float = 10.0
    max_output_chars: int = 12000


class ToolConfig(EvernightAISchema):
    filesystem: FilesystemToolConfig = Field(default_factory=FilesystemToolConfig)
    shell: ShellToolConfig = Field(default_factory=ShellToolConfig)


class AuthPrincipalConfig(EvernightAISchema):
    principal_id: str
    principal_type: PrincipalType = PrincipalType.USER
    api_key: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthConfig(EvernightAISchema):
    enabled: bool = False
    principals: list[AuthPrincipalConfig] = Field(default_factory=list)


class EvernightConfig(EvernightAISchema):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
