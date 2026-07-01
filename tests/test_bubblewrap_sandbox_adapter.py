import shutil

import pytest

from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxNetworkMode,
    SandboxPolicy,
    SandboxResourceLimits,
)
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor


def make_request(
    *,
    command: list[str],
    host_path: str,
    access: SandboxFilesystemAccess = SandboxFilesystemAccess.READ_WRITE,
    network_mode: SandboxNetworkMode = SandboxNetworkMode.UNRESTRICTED,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        request_id="bubblewrap-call-1",
        command=SandboxCommand(
            command=command,
            cwd="/workspace",
            timeout_seconds=5,
        ),
        policy=SandboxPolicy(
            command_allowlist=[command[0]],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=host_path,
                    mount_path="/workspace",
                    access=access,
                )
            ],
            network_mode=network_mode,
            resource_limits=SandboxResourceLimits(timeout_seconds=10),
        ),
    )


def bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


@pytest.mark.asyncio
async def test_bubblewrap_sandbox_runs_inside_mapped_mount(tmp_path) -> None:
    if not bwrap_available():
        pytest.skip("bwrap is not available")

    executor = BubblewrapSandboxExecutor()

    result = await executor.execute(
        make_request(
            command=["/bin/sh", "-c", "pwd; echo hello > note.txt; cat note.txt"],
            host_path=str(tmp_path),
        )
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["/workspace", "hello"]
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.metadata["sandbox_backend"] == "bubblewrap"


@pytest.mark.asyncio
async def test_bubblewrap_sandbox_enforces_read_only_mount(tmp_path) -> None:
    if not bwrap_available():
        pytest.skip("bwrap is not available")

    executor = BubblewrapSandboxExecutor()

    result = await executor.execute(
        make_request(
            command=["/bin/sh", "-c", "echo hello > note.txt"],
            host_path=str(tmp_path),
            access=SandboxFilesystemAccess.READ_ONLY,
        )
    )

    assert result.returncode != 0
    assert not (tmp_path / "note.txt").exists()


@pytest.mark.asyncio
async def test_bubblewrap_sandbox_disables_network_when_supported(tmp_path) -> None:
    if not bwrap_available():
        pytest.skip("bwrap is not available")

    executor = BubblewrapSandboxExecutor()

    result = await executor.execute(
        make_request(
            command=["/bin/sh", "-c", "echo ok"],
            host_path=str(tmp_path),
            network_mode=SandboxNetworkMode.DISABLED,
        )
    )

    if result.returncode != 0 and "Operation not permitted" in result.stderr:
        pytest.skip("bwrap network namespace is not permitted in this environment")

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["ok"]
