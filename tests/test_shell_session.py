import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from EvernightAI.core.domain.shell import ShellSessionStore
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.core.protocol.sandbox import SandboxExecuteProtocol
from EvernightAI.core.protocol.shell import ShellSessionStoreProtocol
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.sandbox.bubblewrap import BubblewrapSandboxExecutor
from EvernightAI.infra.adapters.tool.sqlite import SQLiteShellSessionStore
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell sessions")

SESSION = {"owner_id": "user-1", "session_id": "chat-1"}


def manager_for(
    root: Path,
    store: ShellSessionStoreProtocol | None = None,
    *,
    relaxed: bool = True,
    allowed: set[str] | None = None,
    env_keys: set[str] | None = None,
    sandbox: SandboxExecuteProtocol | None = None,
) -> ToolManager:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands=allowed or set(),
        working_directory=root,
        requires_approval=False,
        approval_level="workspace_write" if relaxed else "read_only",
        allowed_env_keys=env_keys,
        sandbox=sandbox,
        session_store=store or ShellSessionStore(),
    )
    return ToolManager(register)


async def shell(
    manager: ToolManager,
    command: str | list[str],
    metadata: dict[str, Any] | None = SESSION,
    *,
    approved: bool = False,
    **arguments: object,
) -> dict[str, Any]:
    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {"command": command, **arguments},
            },
            metadata={**(metadata or {}), **({"approved": True} if approved else {})},
        )
    )
    return result.tool_call_result


@pytest.mark.asyncio
async def test_directory_and_exports_carry_over_like_one_terminal(tmp_path) -> None:
    manager = manager_for(tmp_path)

    first = await shell(manager, "mkdir -p app/src && cd app && export STAGE=dev")
    second = await shell(manager, "pwd; echo $STAGE; cd src; exit 3", approved=True)
    third = await shell(manager, ["pwd"])

    assert first["session"] == {"cwd": "app", "env_keys": ["STAGE"], "ignored": []}
    assert first["command"][-1] == "mkdir -p app/src && cd app && export STAGE=dev"
    assert second["stdout"].splitlines() == [str(tmp_path / "app"), "dev"]
    # A failing script still leaves the terminal where it ended.
    assert second["returncode"] == 3
    assert second["session"]["cwd"] == "app/src"
    assert third["stdout"].strip() == str(tmp_path / "app" / "src")
    assert third["cwd"] == str(tmp_path / "app" / "src")


@pytest.mark.asyncio
async def test_state_is_scoped_to_its_owner_and_session(tmp_path) -> None:
    manager = manager_for(tmp_path)
    await shell(manager, "mkdir app && cd app && export STAGE=dev")

    other_session = await shell(
        manager, "pwd; echo ${STAGE:-unset}", {**SESSION, "session_id": "chat-2"}
    )
    other_owner = await shell(
        manager, "pwd; echo ${STAGE:-unset}", {**SESSION, "owner_id": "user-2"}
    )
    run_only = await shell(
        manager, "pwd; echo ${STAGE:-unset}", {"owner_id": "user-1", "run_id": "r1"}
    )
    no_context = await shell(manager, "cd app; echo ${STAGE:-unset}", None)
    still_root = await shell(manager, "pwd", None)

    for result in (other_session, other_owner, run_only):
        assert result["stdout"].splitlines() == [str(tmp_path), "unset"]
    assert "session" not in no_context
    assert still_root["stdout"].strip() == str(tmp_path)


@pytest.mark.asyncio
async def test_state_cannot_leave_the_root_or_hijack_later_commands(tmp_path) -> None:
    manager = manager_for(tmp_path, env_keys={"STAGE", "PATH"})

    with pytest.raises(ToolPolicyError):
        await shell(manager, "export OTHER=1", approved=True)
    result = await shell(manager, "export STAGE=dev; cd /", approved=True)
    assert result["session"]["env_keys"] == ["STAGE"]
    assert result["session"]["cwd"] == "."


@pytest.mark.asyncio
async def test_forged_state_records_are_validated_like_real_ones(tmp_path) -> None:
    manager = manager_for(tmp_path)

    result = await shell(
        manager,
        r"printf 'S\000E\000/etc\000LD_PRELOAD=/tmp/x.so\000' "
        '>"/dev/fd/$EVERNIGHT_SIDE_CHANNEL_FD"',
        approved=True,
    )

    assert result["returncode"] == 0
    assert result["session"]["cwd"] == "."
    assert result["session"]["env_keys"] == []


@pytest.mark.asyncio
async def test_project_path_entries_persist_but_shadowing_needs_approval(
    tmp_path,
) -> None:
    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("pytest", "ls"):
        script = bin_dir / name
        script.write_text("#!/bin/sh\necho project-$0\n", encoding="utf-8")
        script.chmod(0o755)
    manager = manager_for(tmp_path)

    outside = await shell(manager, 'export PATH="/opt/evil/bin:$PATH"', approved=True)
    inside = await shell(manager, 'export PATH="$PWD/.venv/bin:$PATH"', approved=True)
    with pytest.raises(ToolPolicyError):
        await shell(manager, "pytest")
    routine = await shell(manager, "pytest", approved=True)

    assert outside["session"]["env_keys"] == []
    assert outside["session"]["ignored"] == [
        "PATH: PATH may only add directories inside the project root"
    ]
    assert inside["session"]["env_keys"] == ["PATH"]
    assert routine["stdout"].strip().endswith("project-" + str(bin_dir / "pytest"))
    with pytest.raises(ToolPolicyError) as exc_info:
        await shell(manager, "ls")
    assert "Environment" in (exc_info.value.detail or "")

    # A trusted command name no longer names the trusted program.
    strict = manager_for(tmp_path, relaxed=False, allowed={"pytest"})
    trusted_call = ToolCall(
        tool_call_id="call-1",
        tool_call={"name": "restricted_shell", "arguments": {"command": ["pytest"]}},
        metadata={**SESSION, "session_id": "strict"},
    )
    assert strict.authorize(trusted_call).requires_approval
    await shell(
        strict,
        'export PATH="$PWD/.venv/bin:$PATH"',
        {**SESSION, "session_id": "strict"},
        approved=True,
    )
    with pytest.raises(ToolPolicyError) as strict_info:
        await shell(strict, ["pytest"], {**SESSION, "session_id": "strict"})
    assert strict_info.value.detail is not None
    assert "Shell session changed" in strict_info.value.detail


@pytest.mark.asyncio
async def test_reset_and_missing_directories_return_to_the_root(tmp_path) -> None:
    manager = manager_for(tmp_path)
    await shell(manager, "mkdir app && cd app && export STAGE=dev")

    reset = await shell(manager, "pwd; echo ${STAGE:-unset}", reset_session=True)
    await shell(manager, "mkdir gone && cd gone")
    (tmp_path / "gone").rmdir()
    fallback = await shell(manager, ["pwd"])
    explicit = await shell(manager, ["pwd"], cwd="app")

    assert reset["stdout"].splitlines() == [str(tmp_path), "unset"]
    assert fallback["stdout"].strip() == str(tmp_path)
    # The cwd argument stays relative to the project root.
    assert explicit["stdout"].strip() == str(tmp_path / "app")


@pytest.mark.asyncio
async def test_state_survives_a_runtime_restart(tmp_path) -> None:
    database = tmp_path / "runtime.sqlite3"
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    store = SQLiteShellSessionStore(database)
    try:
        await shell(manager_for(root, store), "cd app && export STAGE=dev")
    finally:
        store.close()

    store = SQLiteShellSessionStore(database)
    try:
        result = await shell(manager_for(root, store), "pwd; echo $STAGE")
    finally:
        store.close()

    assert result["stdout"].splitlines() == [str(root / "app"), "dev"]


@pytest.mark.sandbox
@pytest.mark.asyncio
async def test_state_carries_over_inside_bubblewrap(tmp_path) -> None:
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap is not available")
    manager = manager_for(tmp_path, sandbox=BubblewrapSandboxExecutor())

    first = await shell(manager, "mkdir app && cd app && export STAGE=dev")
    if first["returncode"] != 0 and "bwrap:" in first["stderr"]:
        pytest.skip(
            "bubblewrap cannot start in this environment: " + first["stderr"].strip()
        )
    second = await shell(manager, "pwd; echo $STAGE")

    assert first["session"] == {"cwd": "app", "env_keys": ["STAGE"], "ignored": []}
    assert second["stdout"].splitlines() == ["/workspace/app", "dev"]


@pytest.mark.asyncio
async def test_pending_approval_cannot_follow_a_changed_session(tmp_path) -> None:
    manager = manager_for(tmp_path)
    pending = ToolCall(
        tool_call_id="pending-delete",
        tool_call={"name": "restricted_shell", "arguments": {"command": "rm note.txt"}},
        metadata=SESSION,
    )
    assert manager.authorize(pending).requires_approval
    await shell(manager, "mkdir app && cd app")
    pending.metadata = {**SESSION, "approved": True}
    decision = manager.authorize(pending)
    assert not decision.allowed
    assert not decision.requires_approval
    assert "session changed" in (decision.reason or "")
