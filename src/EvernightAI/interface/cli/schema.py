from EvernightAI.core.schema.base import EvernightAISchema
from EvernightAI.core.schema.provider import ProviderConfig
from pydantic import Field


class RuntimeConfig(EvernightAISchema):
    database_path: str = ".evernight/runtime.sqlite3"
    filesystem_root: str | None = None


class HttpConfig(EvernightAISchema):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


class ToolConfig(EvernightAISchema):
    allow_file_overwrite: bool = False
    shell_allowed_commands: list[str] = Field(default_factory=list)
    shell_working_directory: str | None = None
    shell_timeout_seconds: float = 10.0
    shell_max_output_chars: int = 12000


class EvernightConfig(EvernightAISchema):
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
