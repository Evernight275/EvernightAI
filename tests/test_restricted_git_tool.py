import subprocess
from pathlib import Path

import pytest

from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.tool import ToolExecutionError, ToolInputError, ToolPolicyError
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


@pytest.mark.asyncio
async def test_git_status_diff_and_branch_list_reflect_repository_state(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "hello.txt").write_text("changed\n", encoding="utf-8")
    manager = _manager(tmp_path)

    status = await manager.execute(_call("git_status"))
    diff = await manager.execute(_call("git_diff", {"path": "hello.txt"}))
    branches = await manager.execute(_call("git_list_branches"))
    _git(tmp_path, "add", "hello.txt")
    staged_diff = await manager.execute(_call("git_diff", {"staged": True}))

    assert "hello.txt" in status.tool_call_result["stdout"]
    assert "-hello" in diff.tool_call_result["stdout"]
    assert "+changed" in diff.tool_call_result["stdout"]
    assert "*" in branches.tool_call_result["stdout"]
    assert "-hello" in staged_diff.tool_call_result["stdout"]
    assert staged_diff.tool_call_result["command"] == ["git", "diff", "--staged"]


@pytest.mark.asyncio
async def test_git_commit_stages_only_selected_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "hello.txt").write_text("changed\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("leave me out\n", encoding="utf-8")
    manager = _manager(tmp_path)

    result = await manager.execute(
        _call(
            "git_commit",
            {"message": "update greeting", "paths": ["hello.txt"]},
            approved=True,
        )
    )

    assert result.tool_call_result["paths"] == ["hello.txt"]
    assert result.tool_call_result["add"]["returncode"] == 0
    assert result.tool_call_result["commit"]["returncode"] == 0
    assert _git(tmp_path, "log", "-1", "--pretty=%s").stdout.strip() == "update greeting"
    assert _git(tmp_path, "status", "--short").stdout.strip() == "?? untracked.txt"


@pytest.mark.asyncio
async def test_git_branch_creation_uses_start_point_and_requires_approval(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    manager = _manager(tmp_path)

    with pytest.raises(ToolPolicyError, match="rejected by policy"):
        await manager.execute(
            _call("git_create_branch", {"name": "blocked", "start_point": "HEAD"})
        )

    created = await manager.execute(
        _call(
            "git_create_branch",
            {"name": "feature", "start_point": "HEAD"},
            approved=True,
        )
    )
    branches = await manager.execute(_call("git_list_branches"))

    assert created.tool_call_result["command"] == [
        "git",
        "branch",
        "feature",
        "HEAD",
    ]
    assert "feature" in branches.tool_call_result["stdout"]


@pytest.mark.asyncio
async def test_git_preserves_nonzero_exit_details(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = await _manager(tmp_path).execute(
        _call("git_show", {"revision": "missing-revision"})
    )

    assert result.tool_call_result["returncode"] != 0
    assert "missing-revision" in result.tool_call_result["stderr"]


@pytest.mark.asyncio
async def test_git_output_is_bounded(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a-very-long-untracked-file-name.txt").write_text("x", encoding="utf-8")

    result = await _manager(tmp_path, max_output_chars=8).execute(
        _call("git_status")
    )

    assert result.tool_call_result["truncated"] is True
    assert len(result.tool_call_result["stdout"]) == 8


@pytest.mark.parametrize(
    ("tool_name", "arguments", "error"),
    [
        ("git_diff", {"staged": "yes"}, "staged value must be a boolean"),
        ("git_diff", {"path": "../outside"}, "must stay inside"),
        ("git_log", {"limit": 0}, "limit must be an integer from 1 to 100"),
        ("git_log", {"path": 1}, "paths must be non-empty strings"),
        ("git_show", {"revision": ""}, "revision must be a non-empty string"),
        ("git_commit", {"message": ""}, "message must be a non-empty string"),
        ("git_commit", {"message": "x", "paths": []}, "non-empty list"),
        ("git_checkout_branch", {"name": 1}, "branch name must be a non-empty string"),
        ("git_create_branch", {"name": ""}, "branch name must be a non-empty string"),
        ("git_create_branch", {"name": "x", "start_point": 1}, "must be a string"),
    ],
)
@pytest.mark.asyncio
async def test_git_tools_reject_invalid_and_escaping_arguments(
    tmp_path: Path,
    tool_name: str,
    arguments: dict[str, object],
    error: str,
) -> None:
    _init_repo(tmp_path)

    with pytest.raises(ToolExecutionError) as exc_info:
        await _manager(tmp_path).execute(
            _call(tool_name, arguments, approved=True)
        )

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert error in str(exc_info.value.cause)


@pytest.mark.parametrize("repository_state", ["missing", "not-git"])
@pytest.mark.asyncio
async def test_git_tools_reject_invalid_repository_roots(
    tmp_path: Path,
    repository_state: str,
) -> None:
    repository = tmp_path / "repository"
    if repository_state == "not-git":
        repository.mkdir()

    with pytest.raises(ToolExecutionError) as exc_info:
        await _manager(repository).execute(_call("git_status"))

    assert isinstance(exc_info.value.cause, ToolInputError)
    assert "repository" in str(exc_info.value.cause)


def _manager(path: Path, *, max_output_chars: int = 12000) -> ToolManager:
    register = ToolRegister()
    register_restricted_git_tools(
        register,
        repository_directory=path,
        max_output_chars=max_output_chars,
    )
    return ToolManager(register)


def _call(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    *,
    approved: bool = False,
) -> ToolCall:
    return ToolCall(
        tool_call_id="call-1",
        tool_call={"name": tool_name, "arguments": arguments or {}},
        metadata={"approved": True} if approved else {},
    )


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
