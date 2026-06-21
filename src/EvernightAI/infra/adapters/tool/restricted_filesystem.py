from pathlib import Path
from typing import Any

from EvernightAI.core.error.tool import ToolInputError
from EvernightAI.core.protocol.tool import ToolExecutorProtocol
from EvernightAI.core.schema.tool import (
    ToolDefinition,
    ToolPermission,
    ToolSafetyLevel,
)


class RestrictedReadTextFileTool:
    def __init__(
        self,
        *,
        root_directory: str | Path,
        max_chars: int = 12000,
    ) -> None:
        self._root_directory = Path(root_directory).resolve()
        self._max_chars = max_chars

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_text_file",
            description="Read a UTF-8 text file inside a fixed root directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                "root_directory": str(self._root_directory),
                "max_chars": self._max_chars,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_path(self._root_directory, arguments.get("path"))
        if not path.is_file():
            raise ToolInputError(f"The file {path.name} does not exist")

        text = path.read_text(encoding="utf-8")
        truncated = len(text) > self._max_chars
        if truncated:
            text = text[: self._max_chars]

        return {
            "path": _relative_path(self._root_directory, path),
            "content": text,
            "truncated": truncated,
        }


class RestrictedWriteTextFileTool:
    def __init__(
        self,
        *,
        root_directory: str | Path,
        allow_overwrite: bool = False,
    ) -> None:
        self._root_directory = Path(root_directory).resolve()
        self._allow_overwrite = allow_overwrite

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_text_file",
            description="Write a UTF-8 text file inside a fixed root directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            permissions=[ToolPermission.WRITE, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SENSITIVE,
            requires_approval=True,
            metadata={
                "root_directory": str(self._root_directory),
                "allow_overwrite": self._allow_overwrite,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_path(self._root_directory, arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolInputError("The file content must be a string")
        existed = path.exists()
        if existed and not self._allow_overwrite:
            raise ToolInputError(f"The file {path.name} already exists")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return {
            "path": _relative_path(self._root_directory, path),
            "bytes_written": len(content.encode("utf-8")),
            "overwritten": existed,
        }


class RestrictedListDirectoryTool:
    def __init__(
        self,
        *,
        root_directory: str | Path,
        max_entries: int = 100,
    ) -> None:
        self._root_directory = Path(root_directory).resolve()
        self._max_entries = max_entries

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_directory",
            description="List files and directories inside a fixed root directory",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
            permissions=[ToolPermission.READ, ToolPermission.FILESYSTEM],
            safety_level=ToolSafetyLevel.SAFE,
            metadata={
                "root_directory": str(self._root_directory),
                "max_entries": self._max_entries,
            },
        )

    def executor(self) -> ToolExecutorProtocol:
        return self.execute

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_path = arguments.get("path", ".")
        path = _resolve_path(self._root_directory, raw_path)
        if not path.is_dir():
            raise ToolInputError(f"The directory {path.name} does not exist")

        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
        limited_entries = entries[: self._max_entries]

        return {
            "path": _relative_path(self._root_directory, path),
            "entries": [
                {
                    "name": entry.name,
                    "path": _relative_path(self._root_directory, entry),
                    "type": "directory" if entry.is_dir() else "file",
                }
                for entry in limited_entries
            ],
            "truncated": len(entries) > self._max_entries,
        }


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
