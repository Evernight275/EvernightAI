from pydantic import ValidationError

from EvernightAI.core.domain.sandbox import BasicSandboxPolicy
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxPolicy,
    SandboxResourceLimits,
)


def make_request(
    *,
    command: list[str] | None = None,
    cwd: str | None = "/workspace",
    env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        request_id="sandbox-call-1",
        command=SandboxCommand(
            command=command or ["python", "-c", "print('hello')"],
            cwd=cwd,
            env=env or {},
            timeout_seconds=timeout_seconds,
        ),
        policy=SandboxPolicy(
            command_allowlist=["python"],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path="/project",
                    mount_path="/workspace",
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            allowed_env_keys=["EVERNIGHT_TEST_VALUE"],
            resource_limits=SandboxResourceLimits(timeout_seconds=10),
        ),
    )


def test_basic_sandbox_policy_allows_request_inside_policy() -> None:
    decision = BasicSandboxPolicy().authorize(
        make_request(env={"EVERNIGHT_TEST_VALUE": "ok"}, timeout_seconds=5)
    )

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.metadata["policy"] == "BasicSandboxPolicy"
    assert decision.metadata["executable"] == "python"


def test_basic_sandbox_policy_rejects_unlisted_command() -> None:
    decision = BasicSandboxPolicy().authorize(make_request(command=["bash"]))

    assert decision.allowed is False
    assert decision.reason == "The command bash is not allowed"


def test_basic_sandbox_policy_rejects_cwd_outside_mounts() -> None:
    decision = BasicSandboxPolicy().authorize(make_request(cwd="/tmp"))

    assert decision.allowed is False
    assert decision.reason == "The working directory is outside the configured mounts"


def test_basic_sandbox_policy_rejects_unlisted_env_key() -> None:
    decision = BasicSandboxPolicy().authorize(make_request(env={"SECRET": "value"}))

    assert decision.allowed is False
    assert decision.reason == "Blocked environment variables: SECRET"


def test_basic_sandbox_policy_rejects_timeout_above_limit() -> None:
    decision = BasicSandboxPolicy().authorize(make_request(timeout_seconds=30))

    assert decision.allowed is False
    assert decision.reason == "The requested timeout exceeds the sandbox limit"


def test_sandbox_command_requires_non_empty_command() -> None:
    try:
        SandboxCommand(command=[])
    except ValidationError as exc:
        assert "List should have at least 1 item" in str(exc)
    else:
        raise AssertionError("SandboxCommand accepted an empty command")
