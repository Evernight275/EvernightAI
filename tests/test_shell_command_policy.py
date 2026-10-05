import os
import sys
from pathlib import Path

import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.core.schema.tool import (
    ToolAccessMode,
    ToolApprovalDecision,
    ToolApprovalStatus,
    ToolCall,
)
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)


def manager_for(
    root: Path, *, blocked: set[str] | None = None, env_keys: set[str] | None = None
) -> ToolManager:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={"python", "uv"},
        blocked_commands=blocked,
        working_directory=root,
        requires_approval=False,
        allowed_env_keys=env_keys,
    )
    return ToolManager(register)


def call_for(command: str | list[str], *, approved: bool = False) -> ToolCall:
    return ToolCall(
        tool_call_id="shell-call",
        tool_call={"name": "restricted_shell", "arguments": {"command": command}},
        approval=ToolApprovalDecision(
            approval_id="shell-call:approval",
            tool_call_id="shell-call",
            status=ToolApprovalStatus.APPROVED,
        )
        if approved
        else None,
    )


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf *",
        "echo ok && rm *.png",
        "echo ok\nrm *",
        "echo ok # comment\nrm *",
        r"r\m -rf *",
        "/bin/rm *.png",
        "sudo -u root rm *",
        "env X=1 rm *",
        "find . -name '*.png' -delete",
        "find . -name '*.png' -exec rm '{}' ';'",
        "uv run rm *",
        "echo $(rm *)",
        "sh -c 'rm *'",
        ["bash", "-lc", "rm *.png"],
        ["powershell", "-Command", "Remove-Item *.png"],
    ],
)
def test_wildcard_deletion_cannot_be_approved(tmp_path, command):
    manager = manager_for(tmp_path)
    manager.set_tool_policy("restricted_shell", ToolAccessMode.ALLOW)
    decision = manager.authorize(call_for(command, approved=True))
    assert not decision.allowed
    assert not decision.requires_approval
    assert decision.reason is not None


@pytest.mark.parametrize(
    "command",
    [
        "rm note.txt",
        "echo ok > note.txt",
        "echo ok >> note.txt",
        "sudo ls",
        "curl https://example.com",
        "sort -o note.txt input.txt",
        "sort -ro note.txt input.txt",
        "rg --pre=script query",
        "rg --hostname-bin=script query",
        "uv run python --version",
        [sys.executable, "-c", "print('ok')"],
        ["some-new-command", "--help"],
        "sh -c 'echo ok'",
    ],
)
def test_suspicious_commands_require_approval_even_when_tool_is_allowed(
    tmp_path, command
):
    manager = manager_for(tmp_path)
    manager.set_tool_policy("restricted_shell", ToolAccessMode.ALLOW)
    decision = manager.authorize(call_for(command))
    assert not decision.allowed
    assert decision.requires_approval
    assert decision.approval_request is not None
    assert decision.approval_request.tool_call["arguments"]["command"] == command
    assert decision.approval_request.reason == decision.reason
    assert manager.authorize(call_for(command, approved=True)).allowed


@pytest.mark.parametrize(
    "command",
    [
        "pwd",
        "ls | head -n 1 && echo done",
        "echo '*' | grep '*'",
        ["ls", "-la"],
        ["uv", "--version"],
    ],
)
def test_read_commands_and_wildcards_are_not_globally_blocked(tmp_path, command):
    assert manager_for(tmp_path).authorize(call_for(command)).allowed


@pytest.mark.parametrize(
    "command", ["echo ok && uv publish", ["sh", "-c", "uv publish"]]
)
def test_configured_blocks_apply_inside_scripts(tmp_path, command):
    decision = manager_for(tmp_path, blocked={"uv publish"}).authorize(
        call_for(command, approved=True)
    )
    assert not decision.allowed
    assert not decision.requires_approval
    assert "blocked" in (decision.reason or "")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_shell_pipeline_and_chain_execute(tmp_path):
    result = await manager_for(tmp_path).execute(
        call_for("echo hello | head -n 1 && pwd")
    )
    value = result.tool_call_result
    assert value["stdout"].splitlines() == ["hello", str(tmp_path)]
    assert value["returncode"] == 0
    assert value["shell_script"] == "echo hello | head -n 1 && pwd"
    assert value["cwd"] == str(tmp_path)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_redirection_executes_only_after_approval(tmp_path):
    manager = manager_for(tmp_path)
    script = "echo hello > note.txt && cat note.txt"
    with pytest.raises(ToolPolicyError):
        await manager.execute(call_for(script))
    assert not (tmp_path / "note.txt").exists()
    result = await manager.execute(call_for(script, approved=True))
    assert result.tool_call_result["stdout"] == "hello\n"
    assert (tmp_path / "note.txt").read_text() == "hello\n"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_named_deletion_requires_approval_and_wildcard_never_executes(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("keep")
    manager = manager_for(tmp_path)
    with pytest.raises(ToolPolicyError):
        await manager.execute(call_for("rm *", approved=True))
    assert note.read_text() == "keep"
    with pytest.raises(ToolPolicyError):
        await manager.execute(call_for("rm note.txt"))
    assert note.exists()
    await manager.execute(call_for("rm note.txt", approved=True))
    assert not note.exists()


def test_wrong_call_approval_and_denied_approval_do_not_authorize(tmp_path):
    manager = manager_for(tmp_path)
    call = call_for("rm note.txt", approved=True)
    assert call.approval is not None
    call.approval.tool_call_id = "another-call"
    assert not manager.authorize(call).allowed
    call.approval.tool_call_id = call.tool_call_id
    call.approval.status = ToolApprovalStatus.DENIED
    call.approval.reason = "User declined"
    decision = manager.authorize(call)
    assert not decision.allowed
    assert decision.reason == "User declined"


def test_disabled_tool_stays_disabled(tmp_path):
    manager = manager_for(tmp_path)
    manager.set_tool_policy("restricted_shell", ToolAccessMode.DENY)
    assert not manager.authorize(call_for("pwd", approved=True)).allowed


def test_environment_overrides_cannot_be_approved(tmp_path):
    call = call_for("ls", approved=True)
    call.tool_call["arguments"]["env"] = {"PATH": "/untrusted"}
    decision = manager_for(tmp_path).authorize(call)
    assert not decision.allowed
    assert not decision.requires_approval
    assert decision.reason == "Environment variable overrides are forbidden"
