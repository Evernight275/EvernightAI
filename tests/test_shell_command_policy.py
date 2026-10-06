import os
import json
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
    root: Path,
    *,
    blocked: set[str] | None = None,
    env_keys: set[str] | None = None,
    relaxed: bool = False,
) -> ToolManager:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={"python", "uv"},
        blocked_commands=blocked,
        working_directory=root,
        requires_approval=False,
        relaxed_approval=relaxed,
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


def test_environment_overrides_for_deletion_cannot_be_approved(tmp_path):
    call = call_for("rm note.txt", approved=True)
    call.tool_call["arguments"]["env"] = {"PATH": "/untrusted"}
    decision = manager_for(tmp_path).authorize(call)
    assert not decision.allowed
    assert not decision.requires_approval
    assert (
        decision.reason
        == "Environment variable overrides are forbidden for deletion commands"
    )


@pytest.mark.parametrize(
    "command",
    [
        "mkdir output && cp input.txt output/copy.txt",
        "echo hello > note.txt && cat note.txt",
        "curl https://example.com",
        "git fetch origin",
        "uv sync",
        "uv pip install matplotlib",
        "uv run --active --no-sync python -m pytest",
        "python -m pip install matplotlib",
        "pnpm run build",
        "pnpm exec tsc --noEmit",
        ["bash", "-lc", "mkdir output && echo hello > output/note.txt"],
    ],
)
def test_relaxed_mode_allows_routine_development_commands(tmp_path, command):
    assert manager_for(tmp_path, relaxed=True).authorize(call_for(command)).allowed


@pytest.mark.parametrize(
    "command",
    [
        "find fastapi -name '*.py'",
        'find fastapi -name "*.py" -exec grep -l "solve_dependencies" {} + | head -3',
        r"find fastapi -exec grep -l Depends {} \;",
        "find fastapi -execdir grep -l Depends '{}' ';'",
        ["find", "fastapi", "-exec", "grep", "-l", "Depends", "{}", ";"],
        "find fastapi -exec grep -l '+' {} +",
        'echo "--- 1. plain grep ---"; grep -c "Depends" fastapi/params.py; '
        'echo "--- 2. piped grep ---"; grep -rn "cache_key" fastapi/ '
        '| grep -v pycache | wc -l; echo "--- 3. recursive + glob ---"; '
        'find fastapi -name "*.py" -exec grep -l "solve_dependencies" {} + '
        '| head -3; echo "--- 4. with env var ---"; Q="Dependant"; '
        'grep -c "$Q" fastapi/dependencies/models.py',
        'echo "&"; echo ";"; echo "|"',
    ],
)
def test_readonly_find_actions_and_chains_do_not_require_approval(tmp_path, command):
    assert manager_for(tmp_path, relaxed=True).authorize(call_for(command)).allowed


@pytest.mark.parametrize(
    "command",
    [
        "find fastapi -fprint result.txt",
        "find fastapi -fprintf result.txt '%p'",
        "find fastapi -fls result.txt",
        "find fastapi -ok grep Depends '{}' ';'",
        "find fastapi -exec unknown-program {} +",
        "find fastapi -exec python -c 'print(1)' {} +",
        "find fastapi -exec rg --pre=script {} +",
        "find fastapi -exec grep {}",
        "find fastapi -exec grep {} +; python -c 'print(1)'",
        "find fastapi -exec grep {} ; python -c 'print(1)'",
        "find fastapi -exec grep {} + &",
    ],
)
def test_find_write_actions_and_untrusted_children_still_require_approval(
    tmp_path, command
):
    decision = manager_for(tmp_path, relaxed=True).authorize(call_for(command))
    assert not decision.allowed
    assert decision.requires_approval


def test_find_child_commands_follow_configured_blocks(tmp_path):
    manager = manager_for(tmp_path, relaxed=True, blocked={"grep -l"})
    decision = manager.authorize(
        call_for("find fastapi -exec grep -l Depends {} +", approved=True)
    )
    assert not decision.allowed
    assert not decision.requires_approval
    assert "blocked" in (decision.reason or "")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_readonly_find_execution_preserves_escaped_action_terminators(tmp_path):
    (tmp_path / "match.py").write_text("Depends\n")
    (tmp_path / "other.py").write_text("other\n")
    result = await manager_for(tmp_path, relaxed=True).execute(
        call_for(r'''Q="Depends"; find . -name "*.py" -exec grep -l "$Q" {} \; | sort''')
    )
    assert result.tool_call_result["returncode"] == 0
    assert result.tool_call_result["stdout"] == "./match.py\n"


@pytest.mark.parametrize(
    "command",
    [
        "rm note.txt",
        "rmdir output",
        "unlink note.txt",
        "shred note.txt",
        "del note.txt",
        "erase note.txt",
        "Remove-Item -LiteralPath note.txt",
        "echo ok && rm note.txt",
        "echo ok > output.txt\nrm note.txt",
        ["bash", "-lc", "rm note.txt"],
        ["uv", "run", "rm", "note.txt"],
        ["uv", "run", "sh", "-c", "rm note.txt"],
        ["python", "-c", "import os; os.remove('note.txt')"],
        "git clean -fd",
        "git rm note.txt",
        "pip uninstall package",
        "npm run clean",
    ],
)
def test_relaxed_mode_keeps_deletion_and_opaque_scripts_under_approval(
    tmp_path, command
):
    manager = manager_for(tmp_path, relaxed=True)
    manager.set_tool_policy("restricted_shell", ToolAccessMode.ALLOW)
    decision = manager.authorize(call_for(command))
    assert not decision.allowed
    assert decision.requires_approval


@pytest.mark.parametrize(
    "command",
    [
        "rm *",
        "uv run rm *",
        "find . -delete",
        "find . -exec rm '{}' ';'",
        "find . -exec bash -c 'rm ./note.txt' {} +",
        ["bash", "-lc", "rm *.txt"],
    ],
)
def test_relaxed_mode_preserves_forbidden_deletion_patterns(tmp_path, command):
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for(command, approved=True)
    )
    assert not decision.allowed
    assert not decision.requires_approval


def test_relaxed_mode_keeps_command_blacklist_and_explicit_ask(tmp_path):
    manager = manager_for(tmp_path, relaxed=True, blocked={"git push"})
    decision = manager.authorize(call_for("git push", approved=True))
    assert not decision.allowed
    assert not decision.requires_approval
    manager.set_tool_policy("restricted_shell", ToolAccessMode.ASK)
    assert manager.authorize(call_for("uv sync")).requires_approval


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_relaxed_execution_writes_without_approval_but_keeps_deletion_gate(
    tmp_path,
):
    manager = manager_for(tmp_path, relaxed=True)
    await manager.execute(call_for("mkdir output && echo hello > output/note.txt"))
    note = tmp_path / "output/note.txt"
    assert note.read_text() == "hello\n"
    with pytest.raises(ToolPolicyError):
        await manager.execute(call_for("rm output/note.txt"))
    assert note.exists()
    await manager.execute(call_for("rm output/note.txt", approved=True))
    assert not note.exists()


@pytest.mark.asyncio
async def test_runtime_configuration_enables_relaxed_command_approval(tmp_path):
    from EvernightAI.bootstrap.config import create_runtime_from_config
    from EvernightAI.interface.cli.config import parse_config

    runtime = create_runtime_from_config(
        parse_config(
            {
                "runtime": {"database_path": str(tmp_path / "runtime.sqlite3")},
                "tools": {
                    "shell": {
                        "enabled": True,
                        "working_directory": str(tmp_path),
                        "allowed_commands": ["python", "uv"],
                        "is_need_approval": False,
                        "relaxed_approval": True,
                    }
                },
            }
        )
    )
    try:
        assert runtime.tools.authorize(call_for("uv sync")).allowed
        deletion = runtime.tools.authorize(call_for("rm note.txt"))
        assert not deletion.allowed
        assert deletion.requires_approval
    finally:
        await runtime.close()


@pytest.mark.parametrize("encoded", [False, True])
def test_command_discovery_inside_login_shell_needs_no_extra_approval(
    tmp_path, encoded
):
    command = ["bash", "-lc", "pwd; ls -la; which uv; uv --version"]
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for(json.dumps(command) if encoded else command)
    )
    assert decision.allowed


@pytest.mark.parametrize(
    "command",
    [
        ["bash", "-lc", "rm note.txt"],
        ["rm", "note.txt"],
        ["uv", "run", "sh", "-c", "rm note.txt"],
    ],
)
def test_serialized_command_arrays_preserve_deletion_approval(tmp_path, command):
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for(json.dumps(command))
    )
    assert not decision.allowed
    assert decision.requires_approval


@pytest.mark.parametrize(
    "command",
    [
        ["bash", "-lc", "rm *.txt"],
        ["uv", "run", "sh", "-c", "rm *.txt"],
    ],
)
def test_serialized_command_arrays_preserve_forbidden_deletion(tmp_path, command):
    decision = manager_for(tmp_path, relaxed=True).authorize(
        call_for(json.dumps(command), approved=True)
    )
    assert not decision.allowed
    assert not decision.requires_approval


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX shell syntax")
async def test_serialized_command_array_executes_as_arguments(tmp_path):
    result = await manager_for(tmp_path, relaxed=True).execute(
        call_for(json.dumps(["sh", "-c", "pwd; echo ready"]))
    )
    value = result.tool_call_result
    assert value["returncode"] == 0, value["stderr"]
    assert value["stdout"].splitlines()[0] == str(tmp_path)
    assert value["stdout"].splitlines()[-1] == "ready"
    assert value["shell_script"] is None
