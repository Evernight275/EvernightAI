import asyncio
from pathlib import Path
from typing import Any

from EvernightAI.core.error.tool import ToolExecutionError, ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol, ToolPreflightPolicy
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.tool.project_roots import ProjectRootResolver


class _ProjectAwareGitTool:
    def __init__(
        self,
        *,
        repository_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        timeout_seconds: float = 10.0,
        max_output_chars: int = 12000,
    ) -> None:
        self._roots = ProjectRootResolver(
            default_root=repository_directory,
            project_directories=project_directories,
        )
        self._repository_directory = self._roots.default_root
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def _resolve_repository(
        self,
        arguments: dict[str, Any],
    ) -> tuple[str | None, Path]:
        return self._roots.resolve(
            arguments.get("project"),
            require_configured=True,
        )

    def _project_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "enum": self._roots.project_names,
        }

    def _parameters_schema(
        self,
        properties: dict[str, Any] | None = None,
        *,
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "project": self._project_schema(),
                **(properties or {}),
            },
        }
        if required:
            schema["required"] = required
        return schema

    def preflight_policy(self) -> ToolPreflightPolicy:
        return self.authorize

    def authorize(
        self,
        _tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> ToolSafetyDecision | None:
        try:
            self._resolve_repository(arguments)
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        return None


class RestrictedGitStatusTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_status",
            description="Show git status for the default or a configured project repository",
            parameters_schema=self._parameters_schema(),
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        return await _run_git(
            repository_directory,
            ["status", "--short", "--branch"],
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitDiffTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_diff",
            description="Show git diff for the default or a configured project repository",
            parameters_schema=self._parameters_schema(
                {
                    "staged": {"type": "boolean"},
                    "path": {"type": "string"},
                }
            ),
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        staged = arguments.get("staged", False)
        if not isinstance(staged, bool):
            raise ToolInputError("The staged value must be a boolean")

        command = ["diff"]
        if staged:
            command.append("--staged")
        path = _parse_optional_repo_path(
            repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            repository_directory,
            command,
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitLogTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_log",
            description="Show recent commits for the default or a configured project repository",
            parameters_schema=self._parameters_schema(
                {
                    "limit": {"type": "integer"},
                    "path": {"type": "string"},
                }
            ),
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        limit = arguments.get("limit", 10)
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ToolInputError("The git log limit must be an integer from 1 to 100")

        command = ["log", "--oneline", "--decorate", "-n", str(limit)]
        path = _parse_optional_repo_path(
            repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            repository_directory,
            command,
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitShowTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_show",
            description="Show a revision or path for the default or a configured project repository",
            parameters_schema=self._parameters_schema(
                {
                    "revision": {"type": "string"},
                    "path": {"type": "string"},
                }
            ),
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        revision = arguments.get("revision", "HEAD")
        if not isinstance(revision, str) or not revision:
            raise ToolInputError("The git revision must be a non-empty string")

        command = ["show", "--stat", "--patch", revision]
        path = _parse_optional_repo_path(
            repository_directory,
            arguments.get("path"),
        )
        if path is not None:
            command.extend(["--", path])

        return await _run_git(
            repository_directory,
            command,
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCommitTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_commit",
            description="Stage selected paths and create a git commit",
            parameters_schema=self._parameters_schema(
                {
                    "message": {"type": "string"},
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                required=["message"],
            ),
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        message = arguments.get("message")
        if not isinstance(message, str) or not message:
            raise ToolInputError("The commit message must be a non-empty string")

        paths = _parse_repo_paths(
            repository_directory,
            arguments.get("paths", ["."]),
        )
        add_result = await _run_git(
            repository_directory,
            ["add", "--", *paths],
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )
        commit_result = await _run_git(
            repository_directory,
            ["commit", "-m", message],
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )

        return {
            "project": project,
            "repository_directory": str(repository_directory),
            "paths": paths,
            "add": add_result,
            "commit": commit_result,
        }


class RestrictedGitListBranchesTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_list_branches",
            description="List branches for the default or a configured project repository",
            parameters_schema=self._parameters_schema(),
            permissions=[ToolPermission.READ],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        return await _run_git(
            repository_directory,
            ["branch", "--list"],
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCheckoutBranchTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_checkout_branch",
            description="Check out a branch in the default or a configured project repository",
            parameters_schema=self._parameters_schema(
                {"name": {"type": "string"}},
                required=["name"],
            ),
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
        name = arguments.get("name")
        if not isinstance(name, str) or not name:
            raise ToolInputError("The branch name must be a non-empty string")

        return await _run_git(
            repository_directory,
            ["checkout", name],
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


class RestrictedGitCreateBranchTool(_ProjectAwareGitTool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="git_create_branch",
            description="Create a branch in the default or a configured project repository",
            parameters_schema=self._parameters_schema(
                {
                    "name": {"type": "string"},
                    "start_point": {"type": "string"},
                },
                required=["name"],
            ),
            permissions=[ToolPermission.WRITE],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=_metadata(self),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, repository_directory = self._resolve_repository(arguments)
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
            repository_directory,
            command,
            project=project,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )


async def _run_git(
    repository_directory: Path,
    arguments: list[str],
    *,
    project: str | None,
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
        len(stdout_text) > max_output_chars or len(stderr_text) > max_output_chars
    )
    return {
        "project": project,
        "repository_directory": str(repository_directory),
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
        "projects": tool._roots.project_names,
        "timeout_seconds": tool._timeout_seconds,
        "max_output_chars": tool._max_output_chars,
    }


def _decode(value: bytes) -> str:
    return value.decode(errors="replace")
