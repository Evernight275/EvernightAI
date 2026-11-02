import os
import shutil

import pytest

from EvernightAI.core.protocol.sandbox import SandboxSpawnProtocol
from EvernightAI.core.schema.sandbox import (
    SandboxCommand,
    SandboxExecutionRequest,
    SandboxFilesystemAccess,
    SandboxFilesystemMount,
    SandboxPolicy,
    SandboxResourceLimits,
)
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.sandbox.subprocess import SubprocessSandboxExecutor

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX descriptors")


def executors() -> list[object]:
    params: list[object] = [pytest.param(SubprocessSandboxExecutor, id="subprocess")]
    params.append(
        pytest.param(
            BubblewrapSandboxExecutor,
            id="bubblewrap",
            marks=[
                pytest.mark.sandbox,
                pytest.mark.skipif(
                    shutil.which("bwrap") is None, reason="bwrap is not available"
                ),
            ],
        )
    )
    return params


def request(
    host_path: str,
    script: str,
    *,
    side_channel: bool = False,
    timeout: float = 5,
    allowed_env_keys: list[str] | None = None,
) -> SandboxExecutionRequest:
    return SandboxExecutionRequest(
        request_id="side-channel",
        command=SandboxCommand(
            command=["/bin/sh", "-c", script],
            cwd="/workspace",
            timeout_seconds=timeout,
            side_channel=side_channel,
        ),
        policy=SandboxPolicy(
            command_allowlist=["/bin/sh"],
            filesystem_mounts=[
                SandboxFilesystemMount(
                    host_path=host_path,
                    mount_path="/workspace",
                    access=SandboxFilesystemAccess.READ_WRITE,
                )
            ],
            allowed_env_keys=allowed_env_keys,
            resource_limits=SandboxResourceLimits(timeout_seconds=timeout),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_type", executors())
async def test_side_channel_returns_what_the_command_wrote(
    tmp_path, executor_type
) -> None:
    executor = executor_type()
    script = 'printf state >"/dev/fd/$EVERNIGHT_SIDE_CHANNEL_FD"; echo out'

    requested = await executor.execute(
        # The descriptor variable is added by the executor, not by the caller.
        request(str(tmp_path), script, side_channel=True, allowed_env_keys=[])
    )
    unrequested = await executor.execute(request(str(tmp_path), "echo out"))

    assert requested.side_channel == "state"
    assert requested.stdout == "out\n"
    assert unrequested.side_channel is None


@pytest.mark.asyncio
async def test_background_children_do_not_hold_the_result_open(tmp_path) -> None:
    script = (
        'printf state >"/dev/fd/$EVERNIGHT_SIDE_CHANNEL_FD"; sleep 5 >/dev/null 2>&1 &'
    )

    result = await SubprocessSandboxExecutor().execute(
        request(str(tmp_path), script, side_channel=True, timeout=10)
    )

    assert result.side_channel == "state"


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_type", executors())
async def test_spawned_process_streams_and_accepts_input(
    tmp_path, executor_type
) -> None:
    executor = executor_type()
    assert isinstance(executor, SandboxSpawnProtocol)

    process = await executor.spawn(
        request(str(tmp_path), "echo ready; read line; echo got-$line; echo err >&2")
    )
    first = await process.read()
    await process.write_stdin("ping\n")
    await process.close_stdin()
    events = [first]
    while (event := await process.read()) is not None:
        events.append(event)

    assert await process.wait() == 0
    stdout = "".join(e.text for e in events if e and e.stream.value == "stdout")
    stderr = "".join(e.text for e in events if e and e.stream.value == "stderr")
    assert stdout == "ready\ngot-ping\n"
    assert stderr == "err\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("executor_type", executors())
async def test_spawned_process_stops_at_its_lifetime(tmp_path, executor_type) -> None:
    process = await executor_type().spawn(
        request(str(tmp_path), "sleep 30", timeout=0.5)
    )

    returncode = await process.wait()

    assert returncode != 0
    assert getattr(process, "timed_out") is True
