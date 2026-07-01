from pathlib import PurePosixPath

from EvernightAI.core.protocol.sandbox import SandboxPolicyProtocol
from EvernightAI.core.schema.sandbox import (
    SandboxExecutionRequest,
    SandboxPolicyDecision,
)


class BasicSandboxPolicy(SandboxPolicyProtocol):
    def authorize(self, request: SandboxExecutionRequest) -> SandboxPolicyDecision:
        """授权沙盒执行请求"""
        command = request.command.command
        executable = command[0]
        policy = request.policy

        if executable not in policy.command_allowlist:
            return SandboxPolicyDecision(
                allowed=False,
                reason=f"The command {executable} is not allowed",
            )

        cwd = request.command.cwd
        if cwd is not None and not self._is_allowed_cwd(
            cwd,
            [mount.mount_path for mount in policy.filesystem_mounts],
        ):
            return SandboxPolicyDecision(
                allowed=False,
                reason="The working directory is outside the configured mounts",
            )

        if policy.allowed_env_keys is not None:
            allowed_env_keys = set(policy.allowed_env_keys)
            blocked_env_keys = sorted(
                key for key in request.command.env if key not in allowed_env_keys
            )
            if blocked_env_keys:
                return SandboxPolicyDecision(
                    allowed=False,
                    reason=(
                        "Blocked environment variables: "
                        + ", ".join(blocked_env_keys)
                    ),
                )

        timeout_seconds = request.command.timeout_seconds
        if (
            timeout_seconds is not None
            and timeout_seconds > policy.resource_limits.timeout_seconds
        ):
            return SandboxPolicyDecision(
                allowed=False,
                reason="The requested timeout exceeds the sandbox limit",
            )

        return SandboxPolicyDecision(
            allowed=True,
            metadata={
                "policy": self.__class__.__name__,
                "executable": executable,
            },
        )

    def _is_allowed_cwd(self, cwd: str, mount_paths: list[str]) -> bool:
        if not mount_paths:
            return False

        cwd_path = self._normalize_path(cwd)
        for mount_path in mount_paths:
            mount = self._normalize_path(mount_path)
            if cwd_path == mount or mount in cwd_path.parents:
                return True
        return False

    def _normalize_path(self, value: str) -> PurePosixPath:
        path = PurePosixPath(value)
        if not path.is_absolute():
            path = PurePosixPath("/") / path
        return path
