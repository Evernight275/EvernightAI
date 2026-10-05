import asyncio
import os
import sys

import pytest

from EvernightAI.core.error.sandbox import SandboxExecutionError, SandboxPolicyError
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


@pytest.mark.asyncio
async def test_subprocess_sandbox_drains_long_output_in_bounded_chunks(tmp_path):
    (tmp_path / "nested").mkdir()
    request = make_request(
        host_path=str(tmp_path),
        command=[
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('汉' * 100000); sys.stderr.write('字' * 100000)",
        ],
    )
    request.policy.resource_limits.max_output_chars = 1000
    result = await SubprocessSandboxExecutor().execute(request)
    assert result.returncode == 0
    assert result.stdout == "汉" * 1000
    assert result.stderr == "字" * 1000
    assert result.truncated
    assert sum(len(event.text) for event in result.events) <= 1000


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_subprocess_stop_terminates_descendants(tmp_path, stop):
    (tmp_path / "nested").mkdir()
    child_script = (
        "import pathlib,time; pathlib.Path('ready').write_text('yes'); "
        "time.sleep(0.8); pathlib.Path('leaked').write_text('yes')"
    )
    request = make_request(
        host_path=str(tmp_path),
        command=[
            sys.executable,
            "-c",
            f"import subprocess,time; subprocess.Popen([{sys.executable!r}, '-c', {child_script!r}]); time.sleep(10)",
        ],
    )
    request.command.timeout_seconds = 0.5
    task = asyncio.create_task(SubprocessSandboxExecutor().execute(request))

    async def wait_ready():
        while not (tmp_path / "nested" / "ready").exists():
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(wait_ready(), timeout=2)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(SandboxExecutionError, match="timed out"):
                await task
        await asyncio.sleep(0.9)
        assert not (tmp_path / "nested" / "leaked").exists()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
