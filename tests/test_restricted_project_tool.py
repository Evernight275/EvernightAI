import sys

import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolInputError,
    ToolPolicyError,
)
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.registrations.tool.restricted_project import (
    register_restricted_project_tools,
)


@pytest.mark.asyncio
async def test_restricted_project_task_requires_approval(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"hello": [sys.executable, "-c", "print('hello')"]},
    )
    manager = ToolManager(register)

    with pytest.raises(ToolPolicyError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "run_project_task",
                    "arguments": {"task": "hello"},
                },
            )
        )

    assert exc_info.value.detail == "Tool call requires approval"


@pytest.mark.asyncio
async def test_restricted_project_task_runs_allowlisted_task(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={
            "hello": [
                sys.executable,
                "-c",
                "import pathlib; print(pathlib.Path.cwd().name); print('hello')",
            ]
        },
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "run_project_task",
                "arguments": {"task": "hello"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["task"] == "hello"
    assert result.tool_call_result["returncode"] == 0
    assert result.tool_call_result["stdout"].splitlines() == [
        tmp_path.name,
        "hello",
    ]
    assert result.tool_call_result["stderr"] == ""
    assert result.tool_call_result["truncated"] is False


@pytest.mark.asyncio
async def test_restricted_project_task_uses_named_project_command(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"tests": [sys.executable, "-c", "print('global')"]},
        project_commands={
            "EvernightAI": {
                "tests": [sys.executable, "-c", "print('project')"],
            }
        },
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "run_project_task",
                "arguments": {"project": "EvernightAI", "task": "tests"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["project"] == "EvernightAI"
    assert result.tool_call_result["command_scope"] == "project"
    assert result.tool_call_result["stdout"].splitlines() == ["project"]


@pytest.mark.asyncio
async def test_restricted_project_task_uses_configured_project_directory(
    tmp_path,
) -> None:
    project_directory = tmp_path / "other-project"
    project_directory.mkdir()
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"placeholder": ["not-used"]},
        project_commands={
            "OtherProject": {
                "inspect": [
                    sys.executable,
                    "-c",
                    "import pathlib; print(pathlib.Path.cwd().name)",
                ]
            }
        },
        project_directories={"OtherProject": project_directory},
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "run_project_task",
                "arguments": {"project": "OtherProject", "task": "inspect"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["command_scope"] == "project"
    assert result.tool_call_result["working_directory"] == str(project_directory)
    assert result.tool_call_result["stdout"].splitlines() == ["other-project"]


def test_restricted_project_task_requires_existing_absolute_project_directory(
    tmp_path,
) -> None:
    for project_directory in ["relative-project", tmp_path / "missing-project"]:
        register = ToolRegister()

        with pytest.raises(ToolConfigurationError):
            register_restricted_project_tools(
                register,
                working_directory=tmp_path,
                commands={"inspect": [sys.executable, "--version"]},
                project_directories={"OtherProject": project_directory},
            )


@pytest.mark.asyncio
async def test_restricted_project_task_falls_back_to_global_command(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"typecheck": [sys.executable, "-c", "print('global')"]},
        project_commands={
            "EvernightAI": {
                "tests": [sys.executable, "-c", "print('project')"],
            }
        },
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "run_project_task",
                "arguments": {"project": "EvernightAI", "task": "typecheck"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["project"] == "EvernightAI"
    assert result.tool_call_result["command_scope"] == "global"
    assert result.tool_call_result["stdout"].splitlines() == ["global"]


@pytest.mark.asyncio
async def test_restricted_project_task_rejects_unlisted_task(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"hello": [sys.executable, "-c", "print('hello')"]},
    )
    manager = ToolManager(register)

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.execute(
            ToolCall(
                tool_call_id="call-1",
                tool_call={
                    "name": "run_project_task",
                    "arguments": {"task": "missing"},
                },
                metadata={"approved": True},
            )
        )

    assert isinstance(exc_info.value.cause, ToolInputError)


@pytest.mark.asyncio
async def test_restricted_project_task_truncates_output(tmp_path) -> None:
    register = ToolRegister()
    register_restricted_project_tools(
        register,
        working_directory=tmp_path,
        commands={"hello": [sys.executable, "-c", "print('hello')"]},
        max_output_chars=3,
    )
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "run_project_task",
                "arguments": {"task": "hello"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["stdout"] == "hel"
    assert result.tool_call_result["truncated"] is True
