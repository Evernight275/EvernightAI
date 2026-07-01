import sys

import pytest

from EvernightAI.core.error.sandbox import SandboxPolicyError
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxPolicy,
    SandboxResourceLimits,
)
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor


def make_request(
    *,
    command: list[str] | None = None,
    host_path: str,
    env: dict[str, str] | None = None,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        request_id="sandbox-call-1",
        command=SandboxCommand(
            command=command
            or [
                sys.executable,
                "-c",
                (
                    "import os, pathlib; "
                    "print(pathlib.Path.cwd().name); "
                    "print(os.environ['EVERNIGHT_TEST_VALUE'])"
                ),
            ],
            cwd="/workspace/nested",
            env=env or {"EVERNIGHT_TEST_VALUE": "ok"},
            timeout_seconds=5,
        ),
        policy=SandboxPolicy(
            command_allowlist=[sys.executable],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=host_path,
                    mount_path="/workspace",
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            allowed_env_keys=["EVERNIGHT_TEST_VALUE"],
            resource_limits=SandboxResourceLimits(timeout_seconds=10),
        ),
    )


@pytest.mark.asyncio
async def test_subprocess_sandbox_runs_inside_mapped_mount(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    executor = SubprocessSandboxExecutor()

    result = await executor.execute(make_request(host_path=str(tmp_path)))

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["nested", "ok"]
    assert result.stderr == ""
    assert result.events[0].stream == "stdout"
    assert result.truncated is False


@pytest.mark.asyncio
async def test_subprocess_sandbox_rejects_policy_violation(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    executor = SubprocessSandboxExecutor()

    with pytest.raises(SandboxPolicyError) as exc_info:
        await executor.execute(
            make_request(
                command=["not-allowed"],
                host_path=str(tmp_path),
            )
        )

    assert exc_info.value.detail == "The command not-allowed is not allowed"
