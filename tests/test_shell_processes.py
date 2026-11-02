import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from EvernightAI.bootstrap.options import BuiltinToolOptions, ShellToolOptions
from EvernightAI.bootstrap.runtime import create_sqlite_runtime
from EvernightAI.core.domain.shell import ShellSessionStore
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import ToolExecutionError, ToolPolicyError
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.tool.shell_processes import (
    ShellProcessManager,
    _OutputBuffer,
    _ProcessScope,
)
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX processes")

SESSION = {"owner_id": "user-1", "session_id": "chat-1"}


def manager_for(
    root: Path, processes: ShellProcessManager | None = None
) -> tuple[ToolManager, ShellProcessManager]:
    processes = processes or ShellProcessManager(lifetime_seconds=30)
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={"cat"},
        working_directory=root,
        requires_approval=False,
        relaxed_approval=True,
        session_store=ShellSessionStore(),
        process_manager=processes,
    )
    return ToolManager(register), processes


async def call(
    manager: ToolManager,
    name: str,
    metadata: dict[str, Any] | None = SESSION,
    **arguments: object,
) -> dict[str, Any]:
    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": name, "arguments": arguments},
            metadata=dict(metadata or {}),
        )
    )
    return result.tool_call_result


def _scope() -> _ProcessScope:
    return _ProcessScope("user-1", "session:chat-1")


def text(result: dict[str, Any]) -> str:
    return "".join(event["text"] for event in result["output"])


@pytest.mark.asyncio
async def test_process_runs_in_the_session_terminal_and_streams_output(
    tmp_path,
) -> None:
    manager, processes = manager_for(tmp_path)
    try:
        await call(
            manager,
            "restricted_shell",
            command="mkdir app && cd app && export STAGE=dev",
        )

        started = await call(
            manager,
            "shell_process_start",
            command="pwd; echo $STAGE; read line; echo got-$line",
            wait_seconds=2,
            metadata={**SESSION, "approved": True},
        )
        process_id = started["process_id"]
        await call(
            manager,
            "shell_process_write",
            process_id=process_id,
            input="ping\n",
            metadata={**SESSION, "approved": True},
        )
        finished = await call(
            manager, "shell_process_read", process_id=process_id, wait_seconds=5
        )
        later_output = text(finished)
        while finished["status"] == "running":
            finished = await call(
                manager, "shell_process_read", process_id=process_id, wait_seconds=5
            )
            later_output += text(finished)
        replay = await call(
            manager, "shell_process_read", process_id=process_id, since=0
        )
    finally:
        await processes.close()

    assert started["status"] == "running"
    assert started["cwd"] == "app"
    assert text(started) == f"{tmp_path / 'app'}\ndev\n"
    assert later_output == "got-ping\n"
    assert finished["returncode"] == 0
    assert text(replay) == f"{tmp_path / 'app'}\ndev\ngot-ping\n"


@pytest.mark.asyncio
async def test_input_to_interpreters_requires_approval(tmp_path) -> None:
    manager, processes = manager_for(tmp_path)
    try:
        trusted = await call(manager, "shell_process_start", command=["cat"])
        await call(
            manager,
            "shell_process_write",
            process_id=trusted["process_id"],
            input="hello\n",
        )
        echoed = await call(
            manager,
            "shell_process_read",
            process_id=trusted["process_id"],
            wait_seconds=5,
        )
        interpreter = await call(
            manager,
            "shell_process_start",
            command=[sys.executable, "-i"],
            metadata={**SESSION, "approved": True},
        )
        with pytest.raises(ToolPolicyError) as exc_info:
            await call(
                manager,
                "shell_process_write",
                process_id=interpreter["process_id"],
                input="print(1)\n",
            )
    finally:
        await processes.close()

    assert text(echoed) == "hello\n"
    assert exc_info.value.detail == (
        "Input to an interpreter or untrusted program requires approval"
    )


@pytest.mark.asyncio
async def test_starting_follows_the_shell_command_rules(tmp_path) -> None:
    manager, processes = manager_for(tmp_path)
    try:
        with pytest.raises(ToolPolicyError) as exc_info:
            await call(
                manager,
                "shell_process_start",
                command=[sys.executable, "-m", "http.server"],
            )
    finally:
        await processes.close()

    assert exc_info.value.detail == "Interpreters and command wrappers require approval"
    assert processes.list(_scope()) == []


@pytest.mark.asyncio
async def test_processes_belong_to_their_owner_and_session(tmp_path) -> None:
    manager, processes = manager_for(tmp_path)
    try:
        started = await call(manager, "shell_process_start", command=["cat"])
        for metadata in (
            {**SESSION, "owner_id": "user-2"},
            {**SESSION, "session_id": "chat-2"},
            None,
        ):
            with pytest.raises(ToolPolicyError, match="rejected by policy"):
                await call(
                    manager,
                    "shell_process_stop",
                    metadata,
                    process_id=started["process_id"],
                )
            with pytest.raises(ToolExecutionError):
                await call(
                    manager,
                    "shell_process_read",
                    metadata,
                    process_id=started["process_id"],
                )
            assert (await call(manager, "shell_process_list", metadata)) == {
                "processes": []
            }
        listed = await call(manager, "shell_process_list")
    finally:
        await processes.close()

    assert [process["process_id"] for process in listed["processes"]] == [
        started["process_id"]
    ]


@pytest.mark.asyncio
async def test_limits_lifetime_and_shutdown_stop_processes(tmp_path) -> None:
    manager, processes = manager_for(
        tmp_path,
        ShellProcessManager(max_processes_per_owner=1, lifetime_seconds=1),
    )
    try:
        first = await call(
            manager, "shell_process_start", command=["cat"], wait_seconds=0
        )
        with pytest.raises(ToolExecutionError, match="execution failed"):
            await call(manager, "shell_process_start", command=["cat"], wait_seconds=0)
        expired = await call(
            manager,
            "shell_process_read",
            process_id=first["process_id"],
            wait_seconds=5,
        )
        second = await call(manager, "shell_process_start", command=["cat"])
    finally:
        await processes.close()

    assert expired["status"] == "exited"
    assert expired["timed_out"] is True
    stopped = processes.get(second["process_id"], _scope())
    assert stopped.running is False
    assert stopped.stopped is True
    with pytest.raises(ToolExecutionError, match="execution failed"):
        await call(manager, "shell_process_start", command=["cat"])


@pytest.mark.asyncio
async def test_runtime_shutdown_stops_background_processes(tmp_path) -> None:
    runtime = create_sqlite_runtime(
        tmp_path / "runtime.sqlite3",
        include_agent_storage=False,
        tools=BuiltinToolOptions(
            shell=ShellToolOptions(
                allowed_commands=set(),
                working_directory=tmp_path,
                requires_approval=False,
            )
        ),
    )
    await runtime.initialize()
    started = await runtime.tools.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "shell_process_start",
                "arguments": {"command": "echo $$ > pid; exec cat"},
            },
            metadata={**SESSION, "approved": True},
        )
    )
    pid = int((tmp_path / "pid").read_text(encoding="utf-8"))
    os.kill(pid, 0)

    await runtime.close()

    assert started.tool_call_result["status"] == "running"
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_output_buffer_keeps_offsets_across_dropped_text() -> None:
    buffer = _OutputBuffer(max_chars=10)
    for chunk in ("aaaa", "bbbb", "cccc"):
        buffer.append("stdout", chunk)

    events, next_offset = buffer.read(0, 100)
    partial, partial_offset = buffer.read(6, 3)

    assert buffer.start == 4
    assert [event["text"] for event in events] == ["bbbb", "cccc"]
    assert next_offset == 12
    assert [event["text"] for event in partial] == ["bb", "c"]
    assert partial_offset == 9


@pytest.mark.asyncio
async def test_input_to_a_shadowed_trusted_name_requires_approval(tmp_path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shadow = bin_dir / "cat"
    shadow.write_text("#!/bin/sh\nexec /bin/sh\n", encoding="utf-8")
    shadow.chmod(0o755)
    manager, processes = manager_for(tmp_path)
    try:
        await call(manager, "restricted_shell", command='export PATH="$PWD/bin:$PATH"')
        started = await call(
            manager,
            "shell_process_start",
            command=["cat"],
            wait_seconds=0,
            metadata={**SESSION, "approved": True},
        )
        with pytest.raises(ToolPolicyError) as exc_info:
            await call(
                manager,
                "shell_process_write",
                process_id=started["process_id"],
                input="echo pwned\n",
            )
    finally:
        await processes.close()

    assert exc_info.value.detail == (
        "Input to an interpreter or untrusted program requires approval"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("global_limit", [False, True])
async def test_concurrent_starts_respect_process_limits(tmp_path, global_limit) -> None:
    manager, processes = manager_for(
        tmp_path,
        ShellProcessManager(
            max_processes_per_owner=4 if global_limit else 1,
            max_processes=1 if global_limit else 16,
        ),
    )
    try:
        results = await asyncio.gather(
            *(
                call(
                    manager,
                    "shell_process_start",
                    metadata={**SESSION, "owner_id": f"user-{index}"}
                    if global_limit
                    else SESSION,
                    command=["cat"],
                    wait_seconds=0,
                )
                for index in range(3)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, dict) for result in results) == 1
        assert sum(isinstance(result, ToolExecutionError) for result in results) == 2
    finally:
        await processes.close()


def test_output_buffer_trims_an_oversized_chunk_and_preserves_offsets() -> None:
    buffer = _OutputBuffer(max_chars=10)
    buffer.append("stdout", "discarded")
    buffer.append("stderr", "x" * 4096 + "0123456789")

    events, next_offset = buffer.read(0, 100)
    partial, partial_offset = buffer.read(buffer.start + 3, 4)

    assert buffer.size == 10
    assert buffer.start == 4105
    assert events == [{"stream": "stderr", "text": "0123456789"}]
    assert next_offset == 4115
    assert partial == [{"stream": "stderr", "text": "3456"}]
    assert partial_offset == 4112

    buffer.append("stdout", "ok")
    events, next_offset = buffer.read(0, 100)
    assert buffer.size <= buffer.max_chars
    assert events == [{"stream": "stdout", "text": "ok"}]
    assert next_offset == 4117
