import asyncio
import mimetypes
import os
from pathlib import Path
import re
import stat
from typing import Any

from pydantic import ValidationError

from EvernightAI.core.domain.file import MAX_FILE_ARTIFACT_BYTES
from EvernightAI.core.error.tool import ToolExecutionError, ToolInputError
from EvernightAI.core.protocol.file import FileArtifactStoreProtocol
from EvernightAI.core.protocol.workspace import WorkspaceDirectoryProtocol
from EvernightAI.core.schema.file import DisplayFileRequest, FileArtifact
from EvernightAI.core.schema.tool import ToolDefinition, ToolSafetyDecision
from EvernightAI.infra.adapters.tool.project_roots import ProjectRootResolver


class DisplayFileTool:
    def __init__(
        self,
        *,
        root_directory: str | Path,
        store: FileArtifactStoreProtocol,
        workspace_directories: WorkspaceDirectoryProtocol | None = None,
    ) -> None:
        self._roots = ProjectRootResolver(
            default_root=root_directory, workspace_directories=workspace_directories
        )
        self._store = store

    def _request(self, arguments: dict[str, Any]) -> DisplayFileRequest:
        try:
            return DisplayFileRequest.model_validate(
                {
                    key: value
                    for key, value in arguments.items()
                    if key not in {"_working_directory", "_execution_context"}
                }
            )
        except ValidationError as exc:
            raise ToolInputError("展示文件参数无效", cause=exc) from exc

    def _path(self, arguments: dict[str, Any], path: str) -> tuple[Path, Path]:
        root = self._roots.resolve(
            None,
            require_configured=True,
            working_directory=arguments.get("_working_directory"),
        )[1]
        if "\0" in path:
            raise ToolInputError("请输入有效的文件路径")
        if path.startswith("/workspace/"):
            path = path[len("/workspace/") :]
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise ToolInputError("展示文件必须位于当前工作文件夹内")
        if not target.is_file():
            raise ToolInputError("展示文件不存在或不是普通文件")
        return root, target.relative_to(root)

    def preflight(
        self, _tool: ToolDefinition, arguments: dict[str, Any]
    ) -> ToolSafetyDecision | None:
        try:
            self._path(arguments, self._request(arguments).path)
        except (ToolInputError, OSError, ValueError) as exc:
            return ToolSafetyDecision(allowed=False, reason=str(exc))
        return None

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = self._request(arguments)
        context = arguments.get("_execution_context")
        if not isinstance(context, dict) or not context.get("tool_call_id"):
            raise ToolInputError("展示文件需要工具执行上下文")
        root, relative = self._path(arguments, request.path)
        return await asyncio.to_thread(
            self._publish, root, relative, request, context.get("owner_id")
        )

    def _publish(
        self,
        root: Path,
        relative: Path,
        request: DisplayFileRequest,
        owner_id: str | None,
    ) -> dict[str, Any]:
        try:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
            )
            with os.fdopen(_open_file(root, relative, flags), "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ToolExecutionError("只能展示普通文件")
                if info.st_size > MAX_FILE_ARTIFACT_BYTES:
                    raise ToolExecutionError("展示文件过大，最多支持 20 MiB")
                content = source.read(MAX_FILE_ARTIFACT_BYTES + 1)
        except OSError as exc:
            raise ToolExecutionError("无法读取展示文件") from exc
        if len(content) > MAX_FILE_ARTIFACT_BYTES:
            raise ToolExecutionError("展示文件过大，最多支持 20 MiB")
        mime = _image_mime(content)
        mime_type = (
            mime
            or mimetypes.guess_type(relative.name)[0]
            or "application/octet-stream"
        )
        artifact = FileArtifact(
            owner_id=owner_id,
            name=_filename(request.filename or relative.name),
            title=request.title,
            mime_type=mime_type,
            preview_kind="image" if mime else "html" if mime_type == "text/html" else "none",
            size_bytes=len(content),
        )
        self._store.save(artifact, content)
        return {
            "type": "file_display",
            **artifact.info().model_dump(mode="json"),
            "message": "File saved and displayed in the tool card. The user can preview supported images and isolated HTML pages, and download this file. Do not return file content or Base64, or regenerate the file to show it.",
        }


def _open_file(root: Path, relative: Path, flags: int) -> int:
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_DIRECTORY"):
        return os.open(root / relative, flags)
    directory_flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY") | getattr(os, "O_NOFOLLOW", 0)
    )
    directory = os.open(root, directory_flags)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(relative.name, flags, dir_fd=directory)
    finally:
        os.close(directory)


def _image_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _filename(value: str) -> str:
    name = (
        re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")[:200] or "download"
    )
    if re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", name, re.IGNORECASE):
        name = "_" + name
    return name
