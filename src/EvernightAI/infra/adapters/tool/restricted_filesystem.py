import fnmatch
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol, ToolPreflightPolicy
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyDecision,
    ToolSafetyLevel,
)
from EvernightAI.infra.adapters.tool.project_roots import ProjectRootResolver


class _ProjectAwareFilesystemTool:
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        self._roots = ProjectRootResolver(
            default_root=root_directory,
            project_directories=project_directories,
        )
        self._root_directory = self._roots.default_root

    def _resolve_root(self, arguments: dict[str, Any]) -> tuple[str | None, Path]:
        return self._roots.resolve(
            arguments.get("project"),
            require_configured=True,
        )

    def _root_metadata(self) -> dict[str, Any]:
        return {
            "root_directory": str(self._root_directory),
            "projects": self._roots.project_names,
        }

    def _project_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "enum": self._roots.project_names,
        }

    def preflight_policy(self) -> ToolPreflightPolicy:
        return self.authorize

    def authorize(
        self,
        _tool: ToolDefinition,
        arguments: dict[str, Any],
    ) -> ToolSafetyDecision | None:
        try:
            self._resolve_root(arguments)
        except ToolInputError as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        return None


class RestrictedReadTextFileTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        max_chars: int = 12000,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._max_chars = max_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_text_file",
            description="Read a UTF-8 text file from the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                **self._root_metadata(),
                "max_chars": self._max_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        text = path.read_text(encoding="utf-8")
        truncated = len(text) > self._max_chars
        if truncated:
            text = text[: self._max_chars]

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "content": text,
                "truncated": truncated,
            },
            project,
        )


class RestrictedWriteTextFileTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._allow_overwrite = allow_overwrite

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_text_file",
            description="Write a UTF-8 text file in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                **self._root_metadata(),
                "allow_overwrite": self._allow_overwrite,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolInputError("The file content must be a string")
        existed = path.exists()
        if existed and not self._allow_overwrite:
            raise ToolInputError(f"The file {path.name} already exists")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "bytes_written": len(content.encode("utf-8")),
                "overwritten": existed,
            },
            project,
        )


class RestrictedAppendTextFileTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="append_text_file",
            description="Append UTF-8 text in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "create": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        content = arguments.get("content")
        create = arguments.get("create", True)
        if not isinstance(content, str):
            raise ToolInputError("The file content must be a string")
        if not isinstance(create, bool):
            raise ToolInputError("The create value must be a boolean")
        existed = path.exists()
        if not existed and not create:
            raise ToolInputError(f"The file {path.name} does not exist")

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(content)

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "bytes_written": len(content.encode("utf-8")),
                "created": not existed,
            },
            project,
        )


class RestrictedListDirectoryTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        max_entries: int = 100,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._max_entries = max_entries

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_directory",
            description="List files and directories in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                },
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                **self._root_metadata(),
                "max_entries": self._max_entries,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        raw_path = arguments.get("path", ".")
        path = _resolve_path(root_directory, raw_path)
        if not path.is_dir():
            raise ToolInputError(f"The directory {path.name} does not exist")

        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
        limited_entries = entries[: self._max_entries]

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "entries": [
                    {
                        "name": entry.name,
                        "path": _relative_path(root_directory, entry),
                        "type": "directory" if entry.is_dir() else "file",
                    }
                    for entry in limited_entries
                ],
                "truncated": len(entries) > self._max_entries,
            },
            project,
        )


class RestrictedFindPathsTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        max_results: int = 100,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._max_results = max_results

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="find_paths",
            description="Find paths by name in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "pattern": {"type": "string"},
                    "type": {"type": "string", "enum": ["file", "directory", "any"]},
                },
                "required": ["pattern"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                **self._root_metadata(),
                "max_results": self._max_results,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        root = _resolve_path(root_directory, arguments.get("path", "."))
        if not root.is_dir():
            raise ToolInputError(f"The directory {root.name} does not exist")

        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ToolInputError("The path pattern must be a non-empty string")
        requested_type = arguments.get("type", "any")
        if requested_type not in {"file", "directory", "any"}:
            raise ToolInputError("The path type must be file, directory, or any")

        matches: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if len(matches) >= self._max_results:
                break
            if not fnmatch.fnmatch(path.name, pattern):
                continue
            path_type = "directory" if path.is_dir() else "file"
            if requested_type != "any" and path_type != requested_type:
                continue
            matches.append(
                {
                    "path": _relative_path(root_directory, path),
                    "type": path_type,
                }
            )

        return _with_project(
            {
                "path": _relative_path(root_directory, root),
                "pattern": pattern,
                "matches": matches,
                "truncated": len(matches) >= self._max_results,
            },
            project,
        )


class RestrictedSearchTextFilesTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        max_results: int = 100,
        max_file_chars: int = 200000,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._max_results = max_results
        self._max_file_chars = max_file_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_text_files",
            description="Search text files in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "pattern": {"type": "string"},
                    "case_sensitive": {"type": "boolean"},
                },
                "required": ["query"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                **self._root_metadata(),
                "max_results": self._max_results,
                "max_file_chars": self._max_file_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        root = _resolve_path(root_directory, arguments.get("path", "."))
        if not root.is_dir():
            raise ToolInputError(f"The directory {root.name} does not exist")

        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise ToolInputError("The search query must be a non-empty string")

        pattern = arguments.get("pattern", "*")
        if not isinstance(pattern, str) or not pattern:
            raise ToolInputError("The search pattern must be a non-empty string")

        case_sensitive = arguments.get("case_sensitive", True)
        if not isinstance(case_sensitive, bool):
            raise ToolInputError("The case_sensitive value must be a boolean")

        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, Any]] = []
        scanned_files = 0
        skipped_files = 0

        for path in sorted(root.rglob("*")):
            if len(matches) >= self._max_results:
                break
            if not path.is_file() or not fnmatch.fnmatch(path.name, pattern):
                continue

            scanned_files += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped_files += 1
                continue

            if len(text) > self._max_file_chars:
                text = text[: self._max_file_chars]

            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.casefold()
                if needle not in haystack:
                    continue
                matches.append(
                    {
                        "path": _relative_path(root_directory, path),
                        "line_number": line_number,
                        "line": line,
                    }
                )
                if len(matches) >= self._max_results:
                    break

        return _with_project(
            {
                "path": _relative_path(root_directory, root),
                "query": query,
                "pattern": pattern,
                "matches": matches,
                "scanned_files": scanned_files,
                "skipped_files": skipped_files,
                "truncated": len(matches) >= self._max_results,
            },
            project,
        )


class RestrictedReadTextFileLinesTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        max_lines: int = 200,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._max_lines = max_lines

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_text_file_lines",
            description="Read text lines from the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "line_count": {"type": "integer"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                **self._root_metadata(),
                "max_lines": self._max_lines,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        start_line = arguments.get("start_line", 1)
        line_count = arguments.get("line_count", self._max_lines)
        if not isinstance(start_line, int) or start_line < 1:
            raise ToolInputError("The start_line value must be a positive integer")
        if not isinstance(line_count, int) or line_count < 1:
            raise ToolInputError("The line_count value must be a positive integer")

        effective_count = min(line_count, self._max_lines)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[start_line - 1 : start_line - 1 + effective_count]
        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "start_line": start_line,
                "line_count": len(selected),
                "lines": [
                    {"line_number": start_line + index, "text": line}
                    for index, line in enumerate(selected)
                ],
                "truncated": line_count > self._max_lines,
            },
            project,
        )


class RestrictedMovePathTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._allow_overwrite = allow_overwrite

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="move_path",
            description="Move a path in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["source_path", "destination_path"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                **self._root_metadata(),
                "allow_overwrite": self._allow_overwrite,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        source = _resolve_path(root_directory, arguments.get("source_path"))
        destination = _resolve_path(
            root_directory,
            arguments.get("destination_path"),
        )
        if not source.exists():
            raise ToolInputError(f"The path {source.name} does not exist")

        overwrite = arguments.get("overwrite", self._allow_overwrite)
        if not isinstance(overwrite, bool):
            raise ToolInputError("The overwrite value must be a boolean")
        if overwrite and not self._allow_overwrite:
            raise ToolInputError("Overwriting moved paths is not enabled")

        existed = destination.exists()
        if existed:
            if not overwrite:
                raise ToolInputError(f"The destination {destination.name} exists")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

        return _with_project(
            {
                "source_path": _relative_path(root_directory, source),
                "destination_path": _relative_path(root_directory, destination),
                "overwritten": existed,
            },
            project,
        )


class RestrictedDeletePathTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="delete_path",
            description="Delete a path in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        recursive = arguments.get("recursive", False)
        if not isinstance(recursive, bool):
            raise ToolInputError("The recursive value must be a boolean")
        if not path.exists():
            raise ToolInputError(f"The path {path.name} does not exist")

        path_type = "directory" if path.is_dir() else "file"
        if path.is_dir():
            if not recursive:
                raise ToolInputError("Directory deletion requires recursive=true")
            shutil.rmtree(path)
        else:
            path.unlink()

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "type": path_type,
                "deleted": True,
            },
            project,
        )


class RestrictedApplyTextPatchTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="apply_text_patch",
            description="Apply a text replacement in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        if not isinstance(old_text, str) or not old_text:
            raise ToolInputError("The old_text value must be a non-empty string")
        if not isinstance(new_text, str):
            raise ToolInputError("The new_text value must be a string")

        replace_all = arguments.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise ToolInputError("The replace_all value must be a boolean")

        text = path.read_text(encoding="utf-8")
        replacements = text.count(old_text)
        if replacements == 0:
            raise ToolInputError("The old_text value was not found")

        if replace_all:
            next_text = text.replace(old_text, new_text)
        else:
            next_text = text.replace(old_text, new_text, 1)
            replacements = 1

        path.write_text(next_text, encoding="utf-8")
        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "replacements": replacements,
                "bytes_written": len(next_text.encode("utf-8")),
            },
            project,
        )


class RestrictedFileHashTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file_hash",
            description="Compute a file hash in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "algorithm": {"type": "string", "enum": ["sha256", "sha1", "md5"]},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        algorithm = arguments.get("algorithm", "sha256")
        if algorithm not in {"sha256", "sha1", "md5"}:
            raise ToolInputError("The hash algorithm must be sha256, sha1, or md5")

        digest = hashlib.new(str(algorithm))
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "algorithm": algorithm,
                "hexdigest": digest.hexdigest(),
            },
            project,
        )


class RestrictedPathInfoTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="path_info",
            description="Inspect a path in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.exists():
            raise ToolInputError(f"The path {path.name} does not exist")

        stat = path.stat()
        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "type": "directory" if path.is_dir() else "file",
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "is_symlink": path.is_symlink(),
            },
            project,
        )


class RestrictedMakeDirectoryTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="make_directory",
            description="Create a directory in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "parents": {"type": "boolean"},
                    "exist_ok": {"type": "boolean"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        parents = arguments.get("parents", True)
        exist_ok = arguments.get("exist_ok", True)
        if not isinstance(parents, bool):
            raise ToolInputError("The parents value must be a boolean")
        if not isinstance(exist_ok, bool):
            raise ToolInputError("The exist_ok value must be a boolean")

        existed = path.exists()
        path.mkdir(parents=parents, exist_ok=exist_ok)
        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "created": not existed,
                "existed": existed,
            },
            project,
        )


class RestrictedCopyPathTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._allow_overwrite = allow_overwrite

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="copy_path",
            description="Copy a path in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["source_path", "destination_path"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                **self._root_metadata(),
                "allow_overwrite": self._allow_overwrite,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        source = _resolve_path(root_directory, arguments.get("source_path"))
        destination = _resolve_path(
            root_directory,
            arguments.get("destination_path"),
        )
        if not source.exists():
            raise ToolInputError(f"The path {source.name} does not exist")

        overwrite = arguments.get("overwrite", self._allow_overwrite)
        if not isinstance(overwrite, bool):
            raise ToolInputError("The overwrite value must be a boolean")
        if overwrite and not self._allow_overwrite:
            raise ToolInputError("Overwriting copied paths is not enabled")

        existed = destination.exists()
        if existed:
            if not overwrite:
                raise ToolInputError(f"The destination {destination.name} exists")
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()

        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
            path_type = "directory"
        else:
            shutil.copy2(source, destination)
            path_type = "file"

        return _with_project(
            {
                "source_path": _relative_path(root_directory, source),
                "destination_path": _relative_path(root_directory, destination),
                "type": path_type,
                "overwritten": existed,
            },
            project,
        )


class RestrictedReadJsonFileTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_json_file",
            description="Read a JSON file from the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata=self._root_metadata(),
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ToolInputError("The file is not valid JSON") from exc

        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "data": data,
            },
            project,
        )


class RestrictedWriteJsonFileTool(_ProjectAwareFilesystemTool):
    def __init__(
        self,
        *,
        root_directory: str | Path,
        project_directories: dict[str, str | Path] | None = None,
        allow_overwrite: bool = False,
    ) -> None:
        super().__init__(
            root_directory=root_directory,
            project_directories=project_directories,
        )
        self._allow_overwrite = allow_overwrite

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_json_file",
            description="Write a JSON file in the default root or a configured project",
            parameters_schema={
                "type": "object",
                "properties": {
                    "project": self._project_schema(),
                    "path": {"type": "string"},
                    "data": {},
                    "indent": {"type": "integer"},
                },
                "required": ["path", "data"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                **self._root_metadata(),
                "allow_overwrite": self._allow_overwrite,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        project, root_directory = self._resolve_root(arguments)
        path = _resolve_path(root_directory, arguments.get("path"))
        data = arguments.get("data")
        indent = arguments.get("indent", 2)
        if not isinstance(indent, int):
            raise ToolInputError("The indent value must be an integer")

        existed = path.exists()
        if existed and not self._allow_overwrite:
            raise ToolInputError(f"The file {path.name} already exists")

        try:
            content = json.dumps(data, ensure_ascii=False, indent=indent)
        except TypeError as exc:
            raise ToolInputError("The data value must be JSON serializable") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{content}\n", encoding="utf-8")
        return _with_project(
            {
                "path": _relative_path(root_directory, path),
                "bytes_written": len(f"{content}\n".encode("utf-8")),
                "overwritten": existed,
            },
            project,
        )


def _resolve_path(root_directory: Path, raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ToolInputError("The path must be a non-empty string")

    path = (root_directory / raw_path).resolve()
    try:
        path.relative_to(root_directory)
    except ValueError as exc:
        raise ToolInputError("The path must stay inside the root directory") from exc

    return path


def _relative_path(root_directory: Path, path: Path) -> str:
    return path.relative_to(root_directory).as_posix()


def _with_project(
    result: dict[str, Any],
    project: str | None,
) -> dict[str, Any]:
    if project is not None:
        result["project"] = project
    return result
