import sys

import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.registrations.tool.restricted_shell import (
    register_restricted_shell_tool,
)


@pytest.mark.asyncio
async def test_restricted_shell_requires_approval(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        working_directory=tmp_path,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {
                        "command": [
                            sys.executable,
                            "-c",
                            "print('hello')",
                        ]
                    },
                },
            )
        )

    assert exc_info.value.detail == "Tool call requires approval"


@pytest.mark.asyncio
async def test_restricted_shell_can_disable_approval(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        blocked_commands={f"{sys.executable} -c"},
        working_directory=tmp_path,
        requires_approval=False,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {
                    "command": [sys.executable, "--version"],
                },
            },
        )
    )

    assert result.tool_call_result["returncode"] == 0
    assert "Python" in result.tool_call_result["stdout"]


@pytest.mark.asyncio
async def test_restricted_shell_runs_allowlisted_command(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        working_directory=tmp_path,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {
                    "command": [
                        sys.executable,
                        "-c",
                        "print('hello')",
                    ]
                },
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["returncode"] == 0
    assert result.tool_call_result["stdout"].splitlines() == ["hello"]


@pytest.mark.asyncio
async def test_restricted_shell_supports_exact_command_rule(tmp_path) -> None:
    exact_rule = f"{sys.executable} --version"
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={exact_rule},
        working_directory=tmp_path,
        requires_approval=False,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {"command": [sys.executable, "--version"]},
            },
        )
    )

    assert result.tool_call_result["returncode"] == 0
    assert "Python" in result.tool_call_result["stdout"]

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-2",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {
                        "command": [sys.executable, "-c", "print('not allowed')"],
                    },
                },
            )
        )

    assert exc_info.value.detail is not None
    assert "is not allowed" in exc_info.value.detail
    assert result.tool_call_result["stderr"] == ""
    assert result.tool_call_result["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blocked_rule", "command", "requires_approval"),
    [
        (sys.executable, [sys.executable, "--version"], False),
        (
            f"{sys.executable} -c",
            [
                sys.executable,
                "-c",
                "raise RuntimeError('blocked command executed')",
            ],
            True,
        ),
    ],
)
async def test_restricted_shell_rejects_blocked_command_rule(
    tmp_path,
    blocked_rule,
    command,
    requires_approval,
) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        blocked_commands={blocked_rule},
        working_directory=tmp_path,
        requires_approval=requires_approval,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {"command": command},
                },
            )
        )

    assert exc_info.value.detail is not None
    assert "is blocked" in exc_info.value.detail


@pytest.mark.asyncio
async def test_restricted_shell_rejects_unlisted_command(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        working_directory=tmp_path,
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "restricted_shell",
                    "arguments": {"command": ["not-allowed"]},
                },
                metadata={"approved": True},
            )
        )

    assert exc_info.value.detail is not None
    assert "is not allowed" in exc_info.value.detail


@pytest.mark.asyncio
async def test_restricted_shell_truncates_output(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        working_directory=tmp_path,
        max_output_chars=3,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {
                    "command": [
                        sys.executable,
                        "-c",
                        "print('hello')",
                    ]
                },
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["stdout"] == "hel"
    assert result.tool_call_result["truncated"] is True


@pytest.mark.asyncio
async def test_restricted_shell_accepts_cwd_env_and_returns_events(tmp_path) -> None:
    (tmp_path / "nested").mkdir()
    register = ToolRegister()
    register_restricted_shell_tool(
        register,
        allowed_commands={sys.executable},
        working_directory=tmp_path,
        allowed_env_keys={"EVERNIGHT_TEST_VALUE"},
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "restricted_shell",
                "arguments": {
                    "command": [
                        sys.executable,
                        "-c",
                        (
                            "import os, pathlib; "
                            "print(pathlib.Path.cwd().name); "
                            "print(os.environ['EVERNIGHT_TEST_VALUE'])"
                        ),
                    ],
                    "cwd": "nested",
                    "env": {"EVERNIGHT_TEST_VALUE": "ok"},
                    "timeout_seconds": 5,
                },
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["stdout"].splitlines() == ["nested", "ok"]
    assert result.tool_call_result["events"][0]["stream"] == "stdout"
