import asyncio
from pathlib import Path
from typing import Any

from EvernightAI.core.error.tool import ToolExecutionError, ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


class RestrictedGitStatusTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_status",
            description="Show git status for a fixed repository",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _run_git(
            self._repository_directory,
            ["status", "--short", "--branch"],
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitDiffTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_diff",
            description="Show git diff for a fixed repository",
            parameters_schema={
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean"},
                    "path": {"type": "string"},
                },
            },
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        staged = arguments.get("staged", False)
        if not isinstance(staged, bool):
            raise ToolInputError("The staged value must be a boolean")

        command = ["diff"]
        if staged:
            command.append("--staged")
        path = _parse_optional_repo_path(
            self._repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            self._repository_directory,
            command,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitLogTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_log",
            description="Show recent git commits for a fixed repository",
            parameters_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "path": {"type": "string"},
                },
            },
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 10)
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ToolInputError("The git log limit must be an integer from 1 to 100")

        command = ["log", "--oneline", "--decorate", "-n", str(limit)]
        path = _parse_optional_repo_path(
            self._repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            self._repository_directory,
            command,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitShowTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_show",
            description="Show a git revision or path for a fixed repository",
            parameters_schema={
                "type": "object",
                "properties": {
                    "revision": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        revision = arguments.get("revision", "HEAD")
        if not isinstance(revision, str) or not revision:
            raise ToolInputError("The git revision must be a non-empty string")

        command = ["show", "--stat", "--patch", revision]
        path = _parse_optional_repo_path(
            self._repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            self._repository_directory,
            command,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCommitTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_commit",
            description="Stage selected paths and create a git commit",
            parameters_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["message"],
            },
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        message = arguments.get("message")
        if not isinstance(message, str) or not message:
            raise ToolInputError("The commit message must be a non-empty string")

        paths = _parse_repo_paths(
            self._repository_directory,
            arguments.get("paths", ["."]),
        )
        add_result = await _run_git(
            self._repository_directory,
            ["add", "--", *paths],
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )
        commit_result = await _run_git(
            self._repository_directory,
            ["commit", "-m", message],
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )

        return {
            "paths": paths,
            "add": add_result,
            "commit": commit_result,
        }


class RestrictedGitListBranchesTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_list_branches",
            description="List git branches for a fixed repository",
            parameters_schema={"type": "object", "properties": {}},
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await _run_git(
            self._repository_directory,
            ["branch", "--list"],
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCheckoutBranchTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_checkout_branch",
            description="Check out an existing git branch in a fixed repository",
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = arguments.get("name")
        if not isinstance(name, str) or not name:
            raise ToolInputError("The branch name must be a non-empty string")

        return await _run_git(
            self._repository_directory,
            ["checkout", name],
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCreateBranchTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._repository_directory = Path(repository_directory).resolve()
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_create_branch",
            description="Create a git branch in a fixed repository",
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "start_point": {"type": "string"},
                },
                "required": ["name"],
            },
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = arguments.get("name")
        if not isinstance(name, str) or not name:
            raise ToolInputError("The branch name must be a non-empty string")

        command = ["branch", name]
        start_point = arguments.get("start_point")
        if start_point is not None:
            if not isinstance(start_point, str) or not start_point:
                raise ToolInputError("The start_point value must be a string")
            command.append(start_point)

        return await _run_git(
            self._repository_directory,
            command,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


async def _run_git(
    repository_directory: Path,
    arguments: list[str],
    *,
    timeout_seconds: float,
    max_output_chars: int,
) -> dict[str, Any]:
    _ensure_repository(repository_directory)
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *arguments,
            cwd=repository_directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        if process is not None:
            process.kill()
            await process.wait()
        raise ToolExecutionError("The git command timed out", cause=exc) from exc
    except OSError as exc:
        raise ToolExecutionError("The git command failed to start", cause=exc) from exc

    stdout_text = _decode(stdout)
    stderr_text = _decode(stderr)
    truncated = (
        len(stdout_text) > max_output_chars
        or len(stderr_text) > max_output_chars
    )
    return {
        "command": ["git", *arguments],
        "returncode": process.returncode,
        "stdout": stdout_text[:max_output_chars],
        "stderr": stderr_text[:max_output_chars],
        "truncated": truncated,
    }


def _ensure_repository(repository_directory: Path) -> None:
    if not repository_directory.is_dir():
        raise ToolInputError("The repository directory does not exist")
    if not (repository_directory / ".git").exists():
        raise ToolInputError("The repository directory is not a git repository")


def _parse_optional_repo_path(
    repository_directory: Path,
    raw_path: object,
) -> str | None:
    if raw_path is None:
        return None
    return _parse_repo_paths(repository_directory, [raw_path])[0]


def _parse_repo_paths(repository_directory: Path, raw_paths: object) -> list[str]:
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ToolInputError("The paths value must be a non-empty list")

    paths: list[str] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path:
            raise ToolInputError("Git paths must be non-empty strings")
        path = (repository_directory / raw_path).resolve()
        try:
            relative = path.relative_to(repository_directory)
        except ValueError as exc:
            raise ToolInputError("Git paths must stay inside the repository") from exc
        paths.append(relative.as_posix())
    return paths


def _metadata(tool: Any) -> dict[str, Any]:
    return {
        "repository_directory": str(tool._repository_directory),
        "timeout_seconds": tool._timeout_seconds,
        "max_output_chars": tool._max_output_chars,
    }


def _decode(value: bytes) -> str:
    return value.decode(errors="replace")
