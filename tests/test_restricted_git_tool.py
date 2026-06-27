import subprocess
from pathlib import Path

import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.registrations.tool.restricted_git import (
    register_restricted_git_tools,
)


@pytest.mark.asyncio
async def test_git_log_and_show_return_repository_output(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    register = ToolRegister()
    register_restricted_git_tools(register, repository_directory=tmp_path)
    manager = ToolManager(register)

    log_result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={"name": "git_log", "arguments": {"limit": 1}},
        )
    )
    show_result = await manager.execute(
        ToolCall(
            tool_call_id="call-2",
            tool_call={"name": "git_show", "arguments": {"revision": "HEAD"}},
        )
    )

    assert log_result.tool_call_result["returncode"] == 0
    assert "initial commit" in log_result.tool_call_result["stdout"]
    assert show_result.tool_call_result["returncode"] == 0
    assert "hello.txt" in show_result.tool_call_result["stdout"]


@pytest.mark.asyncio
async def test_git_checkout_branch_requires_approval_and_switches_branch(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    _git(tmp_path, "branch", "feature")
    register = ToolRegister()
    register_restricted_git_tools(register, repository_directory=tmp_path)
    manager = ToolManager(register)

    result = await manager.execute(
        ToolCall(
            tool_call_id="call-1",
            tool_call={
                "name": "git_checkout_branch",
                "arguments": {"name": "feature"},
            },
            metadata={"approved": True},
        )
    )

    assert result.tool_call_result["returncode"] == 0
    assert _git(tmp_path, "branch", "--show-current").stdout.strip() == "feature"


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Evernight Test")
    (path / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "hello.txt")
    _git(path, "commit", "-m", "initial commit")


def _git(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        text=True,
        capture_output=True,
    )
