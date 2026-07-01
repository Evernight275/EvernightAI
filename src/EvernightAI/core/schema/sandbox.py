from enum import StrEnum
from typing import Any

from pydantic import Field

from EvernightAI.core.schema.base import EvernightAISchema


class SandboxFilesystemAccess(StrEnum):
    """沙盒文件系统访问级别"""

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class SandboxNetworkMode(StrEnum):
    """沙盒网络模式"""

    DISABLED = "disabled"
    ALLOWLIST = "allowlist"
    UNRESTRICTED = "unrestricted"


class SandboxOutputStream(StrEnum):
    """沙盒输出流"""

    STDOUT = "stdout"
    STDERR = "stderr"


class SandboxFilesystemMount(EvernightAISchema):
    """沙盒文件系统挂载"""

    host_path: str
    mount_path: str
    access: SandboxFilesystemAccess = SandboxFilesystemAccess.READ_ONLY
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxNetworkRule(EvernightAISchema):
    """沙盒网络放行规则"""

    host: str
    port: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxResourceLimits(EvernightAISchema):
    """沙盒资源限制"""

    timeout_seconds: float = 30.0
    max_output_chars: int = 12000
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxPolicy(EvernightAISchema):
    """沙盒策略"""

    command_allowlist: list[str] = Field(default_factory=list)
    filesystem_mounts: list[SandboxFilesystemMount] = Field(default_factory=list)
    network_mode: SandboxNetworkMode = SandboxNetworkMode.DISABLED
    network_allowlist: list[SandboxNetworkRule] = Field(default_factory=list)
    allowed_env_keys: list[str] | None = None
    resource_limits: SandboxResourceLimits = Field(
        default_factory=SandboxResourceLimits
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxCommand(EvernightAISchema):
    """沙盒命令"""

    command: list[str] = Field(min_length=1)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    stdin: str | None = None
    timeout_seconds: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxExecutionRequest(EvernightAISchema):
    """沙盒执行请求"""

    request_id: str
    command: SandboxCommand
    policy: SandboxPolicy
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxPolicyDecision(EvernightAISchema):
    """沙盒策略决策"""

    allowed: bool
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxOutputEvent(EvernightAISchema):
    """沙盒输出事件"""

    stream: SandboxOutputStream
    text: str
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SandboxExecutionResult(EvernightAISchema):
    """沙盒执行结果"""

    request_id: str
    command: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    events: list[SandboxOutputEvent] = Field(default_factory=list)
    timed_out: bool = False
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
